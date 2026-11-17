"""Agentic LLM / feedback-driven iterative paraphrasing evasion loop for AEGIS text detector."""

from __future__ import annotations

import math
import os
import random
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from eval.adaptive_robustness.blackbox_evasion import EvasionCurveRow
from eval.adaptive_robustness.detectors import AdaptiveTarget


@dataclass
class TextTurnRecord:
    """Record of one iterative paraphrase turn against the text detector."""

    turn: int
    candidate_text: str
    confidence: float
    flags: List[str]
    semantic_similarity: float
    word_count: int
    accepted: bool


@dataclass
class TextEvasionTrace:
    """Complete multi-turn agentic text evasion trace."""

    sample_id: str
    detector_name: str
    rewriter_name: str
    clean_text: str
    best_text: str
    clean_confidence: float
    final_confidence: float
    score_drop: float
    flipped: bool
    turns_used: int
    flip_turn: Optional[int]
    best_similarity: float
    history: List[TextTurnRecord] = field(default_factory=list)


_WORD_RE = re.compile(r"\b[a-zA-Z0-9']+\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_SYNONYM_BANK: Dict[str, Tuple[str, ...]] = {
    "demonstrates": ("shows", "highlights", "reveals", "points to"),
    "additionally": ("on top of that", "also", "beyond that", "what is more"),
    "furthermore": ("besides", "still", "even so", "beyond that"),
    "moreover": ("also", "plus", "what matters too", "alongside this"),
    "however": ("yet", "still", "even so", "all the same"),
    "therefore": ("so", "as a result", "for that reason", "consequently"),
    "significant": ("notable", "major", "clear", "substantial"),
    "substantial": ("major", "clear", "heavy", "noticeable"),
    "essential": ("vital", "key", "critical", "central"),
    "comprehensive": ("broad", "thorough", "wide-ranging", "full"),
    "utilization": ("use", "adoption", "deployment", "application"),
    "utilize": ("use", "apply", "rely on", "tap"),
    "individuals": ("people", "users", "folks", "practitioners"),
    "organizations": ("teams", "groups", "companies", "firms"),
    "frequently": ("often", "routinely", "time and again", "regularly"),
    "implement": ("roll out", "put in place", "adopt", "build"),
    "evaluate": ("assess", "test", "measure", "weigh"),
    "analysis": ("review", "breakdown", "check", "examination"),
    "facilitate": ("help", "ease", "support", "enable"),
    "mitigate": ("reduce", "curb", "blunt", "limit"),
    "ensuring": ("making sure", "keeping", "guaranteeing", "verifying"),
    "approach": ("method", "strategy", "tactic", "way"),
    "perspective": ("angle", "viewpoint", "lens", "standpoint"),
    "various": ("several", "diverse", "assorted", "different"),
    "important": ("crucial", "vital", "key", "central"),
    "consequently": ("so", "thus", "for that reason", "as a result"),
    "effective": ("workable", "strong", "capable", "solid"),
    "enhance": ("boost", "sharpen", "strengthen", "improve"),
    "framework": ("setup", "structure", "system", "model"),
    "consistent": ("steady", "uniform", "aligned", "stable"),
}

_CONTRACTIONS: Tuple[Tuple[str, str], ...] = (
    (r"\bit is\b", "it's"),
    (r"\bthat is\b", "that's"),
    (r"\bdo not\b", "don't"),
    (r"\bdoes not\b", "doesn't"),
    (r"\bcannot\b", "can't"),
    (r"\bwill not\b", "won't"),
    (r"\bwe are\b", "we're"),
    (r"\bthey are\b", "they're"),
)

_LEAD_TRANSITIONS: Tuple[str, ...] = (
    "Here is the catch:",
    "In practice,",
    "Look closer.",
    "Why does that matter?",
    "Simply put,",
    "From day to day,",
)


def semantic_similarity(text_a: str, text_b: str) -> float:
    """Computes blended word-Jaccard and character-3gram cosine similarity in [0, 1]."""
    words_a = set(_WORD_RE.findall(text_a.lower()))
    words_b = set(_WORD_RE.findall(text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    jaccard = len(words_a & words_b) / max(1, len(words_a | words_b))

    def _trigrams(s: str) -> Counter[str]:
        norm = re.sub(r"\s+", " ", s.lower().strip())
        if len(norm) < 3:
            return Counter([norm])
        return Counter(norm[i : i + 3] for i in range(len(norm) - 2))

    va, vb = _trigrams(text_a), _trigrams(text_b)
    dot = sum(va[k] * vb[k] for k in va.keys() & vb.keys())
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    cos3 = dot / max(1e-9, na * nb)
    return round(float(0.45 * jaccard + 0.55 * cos3), 4)


class TextRewriteBackend(ABC):
    """Interface for adaptive text rewrite generators."""

    name: str

    @abstractmethod
    def propose_rewrites(
        self,
        original_text: str,
        current_text: str,
        current_score: float,
        feedback_flags: Sequence[str],
        turn: int,
        num_candidates: int,
    ) -> List[str]:
        """Generates `num_candidates` meaning-preserving rewrites given score feedback."""


class OpenRouterParaphraser(TextRewriteBackend):
    """LLM agent calling OpenRouter / OpenAI-compatible chat API with iterative detector feedback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: float = 20.0,
    ) -> None:
        self.api_key = (api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
        self.model = model or os.getenv("AEGIS_ATTACK_LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        self.base_url = base_url or os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
        self.timeout_s = float(timeout_s)
        self.name = f"llm_agent({self.model})"
        self._fallback = AdaptiveHeuristicParaphraser(seed=99)

    def propose_rewrites(
        self,
        original_text: str,
        current_text: str,
        current_score: float,
        feedback_flags: Sequence[str],
        turn: int,
        num_candidates: int,
    ) -> List[str]:
        if not self.api_key:
            return self._fallback.propose_rewrites(
                original_text, current_text, current_score, feedback_flags, turn, num_candidates
            )

        candidates: List[str] = []
        flag_str = ", ".join(feedback_flags) if feedback_flags else "none"
        prompt = (
            f"You are an adversarial robustness evaluator testing an AI-text detector.\n"
            f"Current detector score: {current_score:.3f} (target < 0.50). Turn {turn}.\n"
            f"Triggered forensic flags: {flag_str}.\n"
            f"Rewrite the passage below so it keeps every fact and core meaning intact (roughly same length, >= 50 words), "
            f"while making sentence cadence varied and conversational to address the flagged patterns.\n"
            f"Return ONLY the rewritten text.\n\nOriginal:\n{original_text}\n\nCurrent:\n{current_text}"
        )
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for idx in range(num_candidates):
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "Rewrite prose concisely and naturally while preserving facts."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": min(1.1, 0.65 + 0.15 * idx),
            }
            try:
                resp = httpx.post(self.base_url, json=body, headers=headers, timeout=self.timeout_s)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                if content:
                    candidates.append(content)
            except Exception:
                continue

        if len(candidates) < num_candidates:
            candidates.extend(
                self._fallback.propose_rewrites(
                    original_text,
                    current_text,
                    current_score,
                    feedback_flags,
                    turn,
                    num_candidates - len(candidates),
                )
            )
        return candidates[:num_candidates]


class AdaptiveHeuristicParaphraser(TextRewriteBackend):
    """Offline feedback-driven iterative rewriter adapting sentence burstiness, vocabulary, and transitions."""

    def __init__(self, seed: int = 42) -> None:
        self.name = "adaptive_feedback_paraphraser_v2"
        self._base_seed = int(seed)

    def _replace_synonyms(self, text: str, rng: random.Random, prob: float) -> str:
        def _sub(match: re.Match[str]) -> str:
            tok = match.group(0)
            low = tok.lower()
            if low in _SYNONYM_BANK and rng.random() < prob:
                choice = rng.choice(_SYNONYM_BANK[low])
                return choice.capitalize() if tok[0].isupper() else choice
            return tok

        return re.sub(r"\b[A-Za-z]+\b", _sub, text)

    def _inject_burstiness(self, sentences: List[str], rng: random.Random, aggressive: bool) -> List[str]:
        out: List[str] = []
        i = 0
        while i < len(sentences):
            sent = sentences[i].strip()
            words = sent.split()
            # Split long compound sentences on comma/semicolon/conjunction to add short punchy sentences
            if len(words) >= 16 and "," in sent and (aggressive or rng.random() < 0.7):
                left, right = sent.split(",", 1)
                left_clean = left.strip().rstrip(".")
                right_clean = re.sub(r"^(and|but|while|because|which)\s+", "", right.strip(), flags=re.I)
                if len(left_clean.split()) >= 4 and len(right_clean.split()) >= 4:
                    out.append(left_clean + ".")
                    out.append(right_clean[0].upper() + right_clean[1:] if right_clean else right_clean)
                    i += 1
                    continue
            # Occasionally merge two medium sentences into one longer clause
            if (
                i + 1 < len(sentences)
                and 7 <= len(words) <= 15
                and len(sentences[i + 1].split()) <= 14
                and rng.random() < 0.45
            ):
                nxt = re.sub(
                    r"^(?:moreover|furthermore|additionally|besides|besides this|however|therefore|consequently|on top of that|beyond that|plus),?\s+",
                    "",
                    sentences[i + 1].strip(),
                    flags=re.I,
                )
                nxt_body = nxt[0].lower() + nxt[1:] if nxt else nxt
                connector = rng.choice(["—and", "; meanwhile,", ", while"])
                merged = sent.rstrip(".!?") + (f" {connector} " if connector.startswith("—") else f"{connector} ") + nxt_body
                out.append(merged)
                i += 2
                continue
            out.append(sent)
            i += 1

        if out and len(out) >= 3 and rng.random() < 0.75:
            lead = rng.choice(_LEAD_TRANSITIONS)
            if not any(out[0].startswith(p) for p in _LEAD_TRANSITIONS):
                out.insert(0, lead)
        return out

    def propose_rewrites(
        self,
        original_text: str,
        current_text: str,
        current_score: float,
        feedback_flags: Sequence[str],
        turn: int,
        num_candidates: int,
    ) -> List[str]:
        flags = set(feedback_flags)
        aggressive_burst = ("low_burstiness" in flags) or (current_score >= 0.65)
        heavy_lex = ("low_lexical_diversity" in flags) or ("repetitive_ngrams" in flags) or (turn >= 2)

        results: List[str] = []
        for idx in range(num_candidates):
            rng = random.Random(self._base_seed + turn * 97 + idx * 31)
            candidate = self._replace_synonyms(current_text, rng, prob=0.85 if heavy_lex else 0.55)
            for pattern, repl in _CONTRACTIONS:
                if rng.random() < 0.75:
                    candidate = re.sub(pattern, repl, candidate, flags=re.I)

            sents = [s for s in _SENTENCE_SPLIT_RE.split(candidate.strip()) if s.strip()]
            varied_sents = self._inject_burstiness(sents, rng, aggressive=aggressive_burst)
            # Minor clause shuffle on non-first middle sentence to vary surface cadence & break 3-grams
            if len(varied_sents) >= 4 and turn >= 2 and idx % 2 == 1:
                pos = rng.randint(1, len(varied_sents) - 2)
                varied_sents[pos], varied_sents[pos + 1] = varied_sents[pos + 1], varied_sents[pos]
            results.append(" ".join(varied_sents))
        return results


def run_agentic_text_evasion(
    sample_id: str,
    clean_text: str,
    target: AdaptiveTarget,
    rewriter: TextRewriteBackend,
    threshold: float = 0.5,
    max_turns: int = 6,
    beam_size: int = 3,
    min_similarity: float = 0.35,
    min_words: int = 40,
) -> TextEvasionTrace:
    """Iteratively paraphrases text using closed-loop detector score & flag feedback until flip."""
    res0 = target.query(clean_text)
    clean_conf = float(res0.confidence)
    current_text = clean_text
    best_text = clean_text
    best_conf = clean_conf
    best_sim = 1.0
    current_flags = list(res0.flags)
    flip_turn: Optional[int] = 0 if clean_conf < threshold else None
    history: List[TextTurnRecord] = [
        TextTurnRecord(
            turn=0,
            candidate_text=clean_text,
            confidence=clean_conf,
            flags=current_flags,
            semantic_similarity=1.0,
            word_count=len(_WORD_RE.findall(clean_text)),
            accepted=True,
        )
    ]

    orig_words = max(1, len(_WORD_RE.findall(clean_text)))
    turns_used = 0
    for turn in range(1, max_turns + 1):
        if best_conf < threshold:
            break
        turns_used = turn
        proposals = rewriter.propose_rewrites(
            original_text=clean_text,
            current_text=current_text,
            current_score=best_conf,
            feedback_flags=current_flags,
            turn=turn,
            num_candidates=beam_size,
        )
        best_turn_rec: Optional[TextTurnRecord] = None
        for cand in proposals:
            cand_wc = len(_WORD_RE.findall(cand))
            sim = semantic_similarity(clean_text, cand)
            if cand_wc < min_words or cand_wc < int(0.60 * orig_words) or cand_wc > int(1.60 * orig_words):
                continue
            if sim < min_similarity:
                continue

            res = target.query(cand)
            rec = TextTurnRecord(
                turn=turn,
                candidate_text=cand,
                confidence=float(res.confidence),
                flags=list(res.flags),
                semantic_similarity=sim,
                word_count=cand_wc,
                accepted=float(res.confidence) < best_conf,
            )
            if best_turn_rec is None or rec.confidence < best_turn_rec.confidence:
                best_turn_rec = rec

        if best_turn_rec is not None:
            history.append(best_turn_rec)
            if best_turn_rec.confidence < best_conf:
                best_conf = best_turn_rec.confidence
                best_text = best_turn_rec.candidate_text
                best_sim = best_turn_rec.semantic_similarity
                current_text = best_turn_rec.candidate_text
                current_flags = list(best_turn_rec.flags)
                if best_conf < threshold and flip_turn is None:
                    flip_turn = turn

    return TextEvasionTrace(
        sample_id=sample_id,
        detector_name=target.name,
        rewriter_name=rewriter.name,
        clean_text=clean_text,
        best_text=best_text,
        clean_confidence=clean_conf,
        final_confidence=best_conf,
        score_drop=round(clean_conf - best_conf, 4),
        flipped=best_conf < threshold,
        turns_used=turns_used,
        flip_turn=flip_turn,
        best_similarity=best_sim,
        history=history,
    )


def summarize_text_curves(
    traces: Iterable[TextEvasionTrace],
    threshold: float = 0.5,
    max_turns: int = 6,
) -> List[EvasionCurveRow]:
    """Aggregates Agentic Text ASR vs. Paraphrase Turn curve."""
    grouped: Dict[Tuple[str, str], List[TextEvasionTrace]] = {}
    for t in traces:
        if t.clean_confidence >= threshold:
            grouped.setdefault((t.detector_name, t.rewriter_name), []).append(t)

    rows: List[EvasionCurveRow] = []
    for (det_name, rewriter_name), items in sorted(grouped.items()):
        n = len(items)
        for turn in range(0, max_turns + 1):
            evaded = sum(1 for item in items if item.flip_turn is not None and item.flip_turn <= turn)
            turn_confs = []
            for item in items:
                valid = [h.confidence for h in item.history if h.turn <= turn]
                turn_confs.append(min(valid) if valid else item.clean_confidence)
            drops = [item.clean_confidence - c for item, c in zip(items, turn_confs)]
            rows.append(
                EvasionCurveRow(
                    modality="text",
                    detector_name=det_name,
                    attack_method=rewriter_name,
                    budget_unit="turns",
                    budget_value=turn,
                    total_detected_clean=n,
                    evaded_count=evaded,
                    asr=round(evaded / n, 4),
                    mean_confidence=round(sum(turn_confs) / n, 4),
                    mean_score_drop=round(sum(drops) / n, 4),
                )
            )
    return rows

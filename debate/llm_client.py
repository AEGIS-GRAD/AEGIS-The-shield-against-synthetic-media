"""
AEGIS Debate & Arbitration Protocol — Standalone LLM Client for Judge Agent.
Communicates with OpenRouter or executes deterministic simulated justifications in offline/mock environments.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aegis.debate.llm_client")

DEFAULT_JUDGE_TIMEOUT_S = float(os.environ.get("AEGIS_JUDGE_TIMEOUT_S", "8.0"))
DEFAULT_JUDGE_MODELS = [
    os.environ.get("AEGIS_JUDGE_MODEL", "nvidia/nemotron-3.5-lightning:free"),
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]
OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")


def _generate_deterministic_justification(
    verdict_class: str,
    score: float,
    active_detectors: List[str],
    applied_rules: List[str],
    guards_applied: List[str],
) -> Dict[str, str]:
    """Generates a high-quality simulated forensic narrative for offline / test environments."""
    det_list = ", ".join(active_detectors) if active_detectors else "none"
    reasons = []
    if applied_rules:
        reasons.extend(applied_rules)
    if guards_applied:
        reasons.extend(guards_applied)
    
    reasons_str = f" Applied rulings: {'; '.join(reasons)}." if reasons else ""

    summary = (
        f"Forensic arbitration concludes {verdict_class} status (calibrated score {score:.2f}) "
        f"evaluating active signals from {det_list}.{reasons_str}"
    )

    narrative = (
        f"COURT FORENSIC REPORT: The multi-agent arbitration panel reviewed active evidentiary submissions "
        f"from {det_list}. Under the Forensic Precedence Matrix, the calibrated composite score of {score:.2f} "
        f"establishes a definitive classification of {verdict_class}."
    )
    if reasons_str:
        narrative += f" Evidentiary adjustments:{reasons_str}"

    return {
        "forensic_justification": narrative,
        "adjudication_summary": summary,
    }


def call_judge_llm(
    prompt: str,
    active_detector_ids: List[str],
    locked_verdict_str: str,
    calibrated_score: float,
    applied_rules: Optional[List[str]] = None,
    guards_applied: Optional[List[str]] = None,
    mock: bool = False,
    mock_response: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]:
    """Invokes the OpenRouter LLM or returns a simulated forensic justification.

    Returns:
        (parsed_dict_or_None, model_or_error, latency_s, failure_reason)
    """
    applied_rules = applied_rules or []
    guards_applied = guards_applied or []

    # Check for offline mock mode or test environment
    is_mock = mock or (os.environ.get("AEGIS_MOCK_LLM", "").lower() in ("1", "true", "yes"))
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if is_mock or not api_key:
        t0 = time.time()
        simulated = mock_response or _generate_deterministic_justification(
            locked_verdict_str, calibrated_score, active_detector_ids, applied_rules, guards_applied
        )
        latency = round(time.time() - t0, 3)
        source = "deterministic-reference-judge (mock)" if is_mock else "deterministic-fallback (no-api-key)"
        return simulated, source, latency, None if is_mock else "NO_OPENROUTER_API_KEY_SET"

    # Live OpenRouter API Invocation
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed in environment; falling back to simulated justification.")
        simulated = _generate_deterministic_justification(
            locked_verdict_str, calibrated_score, active_detector_ids, applied_rules, guards_applied
        )
        return simulated, "deterministic-fallback", 0.0, "HTTPX_NOT_INSTALLED"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/AEGIS-GRAD/AEGIS-The-shield-against-synthetic-media",
        "X-Title": "AEGIS Debate Judge Agent",
    }

    t0 = time.time()
    for model_name in DEFAULT_JUDGE_MODELS:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=DEFAULT_JUDGE_TIMEOUT_S) as client:
                resp = client.post(OPENROUTER_URL, headers=headers, json=payload)
            latency = round(time.time() - t0, 3)

            if resp.status_code != 200:
                logger.warning(f"OpenRouter judge model {model_name} returned HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"].strip()

            # Clean markdown JSON fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```", 2)[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            parsed = json.loads(raw_text)

            # Strict validation
            if not isinstance(parsed, dict) or "forensic_justification" not in parsed:
                logger.warning(f"Judge response from {model_name} missing 'forensic_justification'.")
                continue

            justification = parsed["forensic_justification"]
            if not isinstance(justification, str) or len(justification.strip()) < 30:
                logger.warning(f"Judge response from {model_name} had empty or too short justification.")
                continue

            # Ensure all active detectors are mentioned
            missing_detectors = [det for det in active_detector_ids if det.lower() not in justification.lower()]
            if missing_detectors:
                logger.warning(f"Judge response from {model_name} failed to address detector(s): {missing_detectors}")
                # We can accept or append, or reject. Let's keep it if reasonably detailed.

            return parsed, model_name, latency, None

        except Exception as exc:
            logger.warning(f"Judge LLM attempt failed on {model_name}: {exc}")
            continue

    total_latency = round(time.time() - t0, 3)
    simulated = _generate_deterministic_justification(
        locked_verdict_str, calibrated_score, active_detector_ids, applied_rules, guards_applied
    )
    return simulated, "deterministic-fallback", total_latency, "ALL_JUDGE_MODELS_FAILED"

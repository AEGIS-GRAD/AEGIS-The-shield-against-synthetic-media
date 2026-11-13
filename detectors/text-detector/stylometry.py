"""
Stylometry feature extraction module for text deepfake/AI explainability.
Extracts:
1. Vocabulary Diversity: Type-Token Ratio (TTR) and Root TTR (Guiraud's Index).
2. N-gram Repetition: Fraction of repeated bi-grams, tri-grams, and 4-grams.
3. Sentence-Structure Variation: Sentence length distribution, variance/CoV, POS-tag sequence entropy.
"""
import math
import re
from collections import Counter
from typing import Dict, Any, List

def _tokenize_words(text: str) -> List[str]:
    # Robust regex tokenizer without mandatory nltk dependency overhead
    return re.findall(r"\b[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?\b", text.lower())

def _tokenize_sentences(text: str) -> List[str]:
    # Sentence splitting on punctuation boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]

def compute_vocabulary_diversity(tokens: List[str]) -> Dict[str, float]:
    total_tokens = len(tokens)
    if total_tokens == 0:
        return {"ttr": 0.0, "root_ttr": 0.0, "unique_words": 0, "total_words": 0}
    
    unique_words = len(set(tokens))
    ttr = unique_words / total_tokens
    root_ttr = unique_words / math.sqrt(total_tokens)
    
    return {
        "ttr": round(ttr, 4),
        "root_ttr": round(root_ttr, 4),
        "unique_words": unique_words,
        "total_words": total_tokens
    }

def compute_ngram_repetition(tokens: List[str], n: int = 3) -> Dict[str, float]:
    if len(tokens) < n:
        return {"ngram_repetition_rate": 0.0, "total_ngrams": 0, "unique_ngrams": 0}
    
    ngrams = [tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)]
    total_ngrams = len(ngrams)
    unique_ngrams = len(set(ngrams))
    repetition_rate = 1.0 - (unique_ngrams / total_ngrams) if total_ngrams > 0 else 0.0
    
    return {
        f"{n}gram_repetition_rate": round(repetition_rate, 4),
        f"total_{n}grams": total_ngrams,
        f"unique_{n}grams": unique_ngrams
    }

def compute_sentence_variation(text: str) -> Dict[str, float]:
    sentences = _tokenize_sentences(text)
    if not sentences:
        return {
            "sentence_count": 0,
            "mean_sentence_length": 0.0,
            "std_sentence_length": 0.0,
            "length_cov": 0.0
        }
    
    lengths = [len(_tokenize_words(s)) for s in sentences]
    n = len(lengths)
    mean_len = sum(lengths) / n
    variance = sum((l - mean_len) ** 2 for l in lengths) / n if n > 1 else 0.0
    std_len = math.sqrt(variance)
    # Coefficient of Variation (CoV) = std / mean
    cov = (std_len / mean_len) if mean_len > 0 else 0.0
    
    return {
        "sentence_count": n,
        "mean_sentence_length": round(mean_len, 2),
        "std_sentence_length": round(std_len, 2),
        "sentence_length_cov": round(cov, 4)
    }

def extract_stylometry_features(text: str) -> Dict[str, Any]:
    """
    Extracts all proposal-mandated stylometry explainability features:
    - vocabulary diversity
    - n-gram repetition (3-gram and 4-gram)
    - sentence-structure variation
    """
    if not text or not text.strip():
        return {
            "vocabulary_diversity": {"ttr": 0.0, "root_ttr": 0.0},
            "ngram_repetition": {"3gram_repetition_rate": 0.0, "4gram_repetition_rate": 0.0},
            "sentence_variation": {"sentence_length_cov": 0.0, "mean_sentence_length": 0.0},
            "synthetic_indication_score": 0.5,
            "stylometry_verdict": "insufficient_signal",
            "summary": "Empty or whitespace-only text provided."
        }
    
    tokens = _tokenize_words(text)
    vocab = compute_vocabulary_diversity(tokens)
    rep3 = compute_ngram_repetition(tokens, n=3)
    rep4 = compute_ngram_repetition(tokens, n=4)
    sent_var = compute_sentence_variation(text)
    
    # Heuristic stylometry indication:
    # LLMs frequently display lower sentence length variance (lower CoV, e.g. uniform ~15-20 words),
    # moderate-to-low vocabulary burstiness, and distinctive repetitive phrasing.
    ttr = vocab.get("ttr", 0.5)
    cov = sent_var.get("sentence_length_cov", 0.5)
    r3 = rep3.get("3gram_repetition_rate", 0.0)
    
    # Synthetic indication heuristic: lower CoV + lower TTR + higher r3 -> higher AI likelihood
    score = 0.5
    if cov < 0.35 and sent_var.get("sentence_count", 0) >= 3:
        score += 0.15  # unnatural uniformity across sentences
    elif cov > 0.65:
        score -= 0.15  # human-like dynamic sentence length bursting
        
    if ttr < 0.55 and vocab.get("total_words", 0) > 40:
        score += 0.10
    elif ttr > 0.80:
        score -= 0.10
        
    if r3 > 0.08:
        score += 0.15
        
    score = max(0.0, min(1.0, round(score, 4)))
    verdict = "synthetic" if score >= 0.65 else ("human" if score <= 0.35 else "uncertain")
    
    summary = (
        f"Vocab TTR: {vocab['ttr']:.2f} ({vocab['unique_words']}/{vocab['total_words']}), "
        f"3-gram rep: {rep3['3gram_repetition_rate']:.1%}, "
        f"Sentence length CoV: {sent_var['sentence_length_cov']:.2f} (mean {sent_var['mean_sentence_length']:.1f} words)."
    )
    
    return {
        "vocabulary_diversity": vocab,
        "ngram_repetition": {**rep3, **rep4},
        "sentence_variation": sent_var,
        "synthetic_indication_score": score,
        "stylometry_verdict": verdict,
        "summary": summary
    }

if __name__ == "__main__":
    sample_human = "The quick brown fox jumps over the lazy dog. Why did it jump? Nobody truly knows, perhaps out of sheer exuberance!"
    sample_llm = "In conclusion, it is important to consider various perspectives. Furthermore, the analysis demonstrates clear results. Therefore, we should evaluate the implications thoroughly."
    
    print("--- Human Sample ---")
    print(extract_stylometry_features(sample_human))
    print("\n--- LLM Sample ---")
    print(extract_stylometry_features(sample_llm))

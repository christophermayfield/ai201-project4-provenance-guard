"""Detection signals.

Each signal has the contract documented in planning.md:

    signal_*(text: str) -> float   # in [0.0, 1.0]; 0.0 = human-like, 1.0 = AI-like

Returning a calibrated-ish float (not a binary flag) is intentional: the
ensemble combines per-signal scores into a single confidence value, and a float
preserves the strength of each signal's evidence.

Signal 2 (`stylometry`) is a local, dependency-free stylometric heuristic that
combines three sub-metrics, each mapped to an AI-likeness sub-score in [0,1]:

  1. sentence-length burstiness  - coefficient of variation of sentence word
     counts. Human prose is bursty (low score); flat/uniform reads AI-like.
  2. type-token ratio (lexical diversity) - unique tokens / total tokens. Heavy
     repetition (low TTR) reads AI-like/formulaic.
  3. mean word length - longer average word length reads more formal/AI-like.

The three are combined with fixed sub-weights into a single signal score.
"""

from __future__ import annotations

import math
import re

from .chunking import split_sentences, word_count

# --- sub-metric mapping parameters (logistic) ---
_CV_MIDPOINT = 0.5
_CV_STEEPNESS = 6.0

_TTR_MIDPOINT = 0.75
_TTR_STEEPNESS = 8.0

_WORDLEN_MIDPOINT = 4.7
_WORDLEN_STEEPNESS = 1.5

# How the three sub-scores combine into the single signal score.
_SUBWEIGHTS = {"burstiness": 0.50, "type_token_ratio": 0.25, "mean_word_length": 0.25}

_TOKEN_RE = re.compile(r"\b\w+\b")


def _logistic_low_is_ai(value: float, midpoint: float, steepness: float) -> float:
    """value BELOW midpoint -> toward 1 (used where 'low metric' means AI-like)."""
    return 1.0 / (1.0 + math.exp(steepness * (value - midpoint)))


def _logistic_high_is_ai(value: float, midpoint: float, steepness: float) -> float:
    """value ABOVE midpoint -> toward 1 (used where 'high metric' means AI-like)."""
    return 1.0 / (1.0 + math.exp(-steepness * (value - midpoint)))


def _coefficient_of_variation(values: list[int]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance) / mean


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def stylometry_metrics(text: str) -> dict:
    """Compute the raw stylometric metrics and their AI-likeness sub-scores.

    Returned so the independent test harness (and the API explanation) can show
    the breakdown, not just the combined number.
    """
    sentences = split_sentences(text)
    lengths = [word_count(s) for s in sentences]
    toks = _tokens(text)

    # 1. Sentence-length burstiness.
    if len(sentences) < 2 or all(length == 0 for length in lengths):
        cv = _CV_MIDPOINT  # not enough signal -> neutral
    else:
        cv = _coefficient_of_variation(lengths)
    # Low CV (uniform rhythm) reads AI-like.
    burstiness_score = _logistic_low_is_ai(cv, _CV_MIDPOINT, _CV_STEEPNESS)

    # 2. Type-token ratio (lexical diversity). Low TTR (repetitive) reads AI-like.
    ttr = len(set(toks)) / len(toks) if toks else _TTR_MIDPOINT
    ttr_score = _logistic_low_is_ai(ttr, _TTR_MIDPOINT, _TTR_STEEPNESS)

    # 3. Mean word length. High word length (formal) reads AI-like.
    mean_word_len = sum(len(t) for t in toks) / len(toks) if toks else _WORDLEN_MIDPOINT
    wordlen_score = _logistic_high_is_ai(mean_word_len, _WORDLEN_MIDPOINT, _WORDLEN_STEEPNESS)

    combined = (
        _SUBWEIGHTS["burstiness"] * burstiness_score
        + _SUBWEIGHTS["type_token_ratio"] * ttr_score
        + _SUBWEIGHTS["mean_word_length"] * wordlen_score
    )
    return {
        "raw": {
            "sentence_length_cv": round(cv, 4),
            "type_token_ratio": round(ttr, 4),
            "mean_word_length": round(mean_word_len, 4),
        },
        "sub_scores": {
            "burstiness": round(burstiness_score, 4),
            "type_token_ratio": round(ttr_score, 4),
            "mean_word_length": round(wordlen_score, 4),
        },
        "score": round(max(0.0, min(1.0, combined)), 4),
    }


def signal_stylometry(text: str) -> float:
    """Combined stylometric AI-likeness score in [0.0, 1.0]."""
    return stylometry_metrics(text)["score"]


# Registry consumed by the scoring layer. Later milestones append signals here.
SIGNALS = {
    "stylometry": signal_stylometry,
}

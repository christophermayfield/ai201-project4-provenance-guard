"""Confidence scoring and label selection.

Turns per-signal scores into a single calibrated confidence, a label/band, and
the transparency-label text. Implements the threshold table and the
false-positive downgrade guardrail from planning.md.

M3 note: only one signal feeds this, calibration is the documented identity
mapping ("uncalibrated"), and `false_positive_probability` is a provisional
uncertainty proxy. The real Bayesian estimator + multi-signal ensemble arrive
in M4/M6.
"""

from __future__ import annotations

from . import config


def aggregate_confidence(scores: dict[str, float]) -> float:
    """Weighted average of per-signal scores, normalized by present weights.

    Identity calibration for now (confidence == raw aggregate).
    """
    if not scores:
        return 0.5
    total_weight = sum(config.SIGNAL_WEIGHTS.get(name, 0.0) for name in scores)
    if total_weight == 0:
        return sum(scores.values()) / len(scores)
    weighted = sum(config.SIGNAL_WEIGHTS.get(name, 0.0) * s for name, s in scores.items())
    return max(0.0, min(1.0, weighted / total_weight))


def estimate_false_positive(confidence: float) -> float:
    """Probability that an AI attribution would be wrong, i.e. P(not AI).

    Defined as `1 - confidence` (monotonic): a high-confidence AI result has a
    low false-positive risk, a borderline one has a high risk. This keeps the
    FP > 0.30 guardrail from silently overriding the threshold table (it now
    only re-files the borderline 0.60-0.70 band as `uncertain`).

    M6 will refine this with signal-agreement / a Bayesian base-rate estimate.
    """
    return round(max(0.0, 1.0 - confidence), 4)


def classify(confidence: float, false_positive: float) -> tuple[str, str]:
    """Map confidence -> (label, band), applying the FP downgrade guardrail."""
    if confidence >= config.AI_MIN:
        label = "likely_ai"
    elif confidence <= config.HUMAN_MAX:
        label = "likely_human"
    else:
        label = "uncertain"

    # Guardrail: never confidently accuse a human when uncertainty is high.
    if label == "likely_ai" and false_positive > config.FALSE_POSITIVE_DOWNGRADE:
        label = "uncertain"

    band = _confidence_band(confidence)
    return label, band


def _confidence_band(confidence: float) -> str:
    strength = abs(confidence - 0.5) * 2  # 0 (boundary) .. 1 (extreme)
    if strength < 0.2:
        return "weak"
    if strength < 0.6:
        return "moderate"
    return "strong"


def build_label(label: str, confidence: float) -> dict[str, str]:
    """Select the transparency-label text + tone for the result."""
    if label == "likely_ai":
        if confidence >= config.HIGH_CONF_AI:
            return {"text": config.LABEL_TEXT["likely_ai"], "tone": "warning"}
        return {"text": config.LABEL_TEXT["likely_ai_soft"], "tone": "caution"}
    if label == "likely_human":
        if confidence <= config.HIGH_CONF_HUMAN:
            return {"text": config.LABEL_TEXT["likely_human"], "tone": "positive"}
        return {"text": config.LABEL_TEXT["likely_human_soft"], "tone": "caution"}
    return {"text": config.LABEL_TEXT["uncertain"], "tone": "neutral"}


def palette_color(confidence: float) -> str:
    """Ombre red -> yellow -> green mapped from confidence (matches API example)."""
    stops = [(0.0, (231, 76, 60)), (0.5, (241, 196, 15)), (1.0, (46, 204, 113))]
    c = max(0.0, min(1.0, confidence))
    for (lo, lo_rgb), (hi, hi_rgb) in zip(stops, stops[1:]):
        if lo <= c <= hi:
            t = 0 if hi == lo else (c - lo) / (hi - lo)
            rgb = tuple(round(a + (b - a) * t) for a, b in zip(lo_rgb, hi_rgb))
            return "#%02x%02x%02x" % rgb
    return "#f1c40f"

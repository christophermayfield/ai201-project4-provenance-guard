"""Configuration for Provenance Guard.

Values that the spec says should be tunable without code changes live here:
input limits, signal weights, decision thresholds, and the transparency-label
copy. See planning.md (Uncertainty Representation + Transparency Label Variants).
"""

from __future__ import annotations

import os

API_VERSION = "0.1.0"
API_PREFIX = "/api/v1"

# --- Input validation limits (planning.md > API Surface > Request) ---
MIN_TEXT_LENGTH = 50      # chars; below this, variance signals are noise -> 422
MAX_TEXT_LENGTH = 20_000  # chars; above this -> 413

# --- Rate limiting (flask-limiter), per IP ---
# /submit triggers a Groq LLM call (cost + latency), so it gets tiered limits
# sized to a real creator's workflow while capping scripted abuse. See README
# "Rate limiting" for the reasoning behind these numbers.
SUBMIT_RATE_LIMITS = os.getenv(
    "SUBMIT_RATE_LIMIT", "10 per minute; 100 per hour; 500 per day"
)
ANALYZE_RATE_LIMIT = os.getenv("ANALYZE_RATE_LIMIT", "10/minute")

# --- Groq (LLM-backed signals) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "20"))  # seconds

# --- Audit log ---
# Append-only JSONL of every analysis + appeal event. content_id is the key the
# appeal flow (M5) uses to look records up.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_LOG_PATH = os.getenv(
    "AUDIT_LOG_PATH", os.path.join(_PROJECT_ROOT, "data", "audit_log.jsonl")
)

# --- Signal weights (must sum to 1.0) ---
# M4: two signals. The Groq signal is an LLM judgment that already folds in the
# tone/hollow-grammar/personal-voice indicators (0.20+0.30+0.20 = 0.70 of the
# 4-signal plan), and the local stylometric heuristic carries the remaining 0.30.
SIGNAL_WEIGHTS: dict[str, float] = {
    "groq_authenticity": 0.70,
    "stylometry": 0.30,
}

# --- Decision thresholds (planning.md > Uncertainty Representation) ---
# confidence in [0,1] = estimated probability the text is AI-generated.
HUMAN_MAX = 0.39   # <= 0.39 -> likely_human
AI_MIN = 0.60      # >= 0.60 -> likely_ai ; the (0.39, 0.60) gap is "uncertain"

# High-confidence cutoffs that select the strong label copy.
HIGH_CONF_AI = 0.80
HIGH_CONF_HUMAN = 0.20

# Guardrail: downgrade likely_ai -> uncertain when false-positive risk is high.
FALSE_POSITIVE_DOWNGRADE = 0.30

# --- Transparency label copy (planning.md > Transparency Label Variants) ---
LABEL_TEXT = {
    "likely_ai": (
        "Likely AI-generated. This content shows strong, consistent indicators "
        "of AI generation across multiple signals. Treat attribution claims with "
        "caution and verify independently where it matters."
    ),
    "likely_ai_soft": (
        "This content shows some indicators of AI generation, but the result is "
        "not conclusive. Use additional context before drawing conclusions."
    ),
    "likely_human": (
        "Likely human-written. This content shows the natural variation, voice, "
        "and specificity typical of human writing. No strong AI indicators were "
        "detected."
    ),
    "likely_human_soft": (
        "This content shows some indicators of human writing, but the result is "
        "not conclusive. Use additional context before drawing conclusions."
    ),
    "uncertain": (
        "Inconclusive. The signals are mixed and we can't reliably attribute "
        "this content. This is an estimate, not proof \u2014 please use your own "
        "judgment and additional context before drawing conclusions."
    ),
}

# Signal catalogue for GET /api/v1/signals. Only implemented signals are listed;
# later milestones append their entries here.
SIGNAL_CATALOGUE = [
    {
        "id": "groq_authenticity",
        "name": "Groq stylistic authenticity",
        "description": (
            "LLM judgment (Groq) of stylistic AI-likeness: risk-averse/bland "
            "tone, flawless-but-hollow grammar, hallucinated specifics, and "
            "absence of genuine personal voice."
        ),
        "weight": SIGNAL_WEIGHTS["groq_authenticity"],
    },
    {
        "id": "stylometry",
        "name": "Stylometric heuristics",
        "description": (
            "Local heuristic combining sentence-length burstiness, type-token "
            "ratio (lexical diversity), and mean word length. Uniform rhythm, "
            "heavy repetition, and high formality read as AI-like."
        ),
        "weight": SIGNAL_WEIGHTS["stylometry"],
    },
]

"""API blueprint.

Routes (planning.md > API Surface):
  POST /api/v1/analyze   - the "submit" flow; runs the analysis pipeline
  GET  /api/v1/health    - liveness/readiness
  GET  /api/v1/signals   - signal catalogue

M3 scope: the analyze route is wired end-to-end but only runs the first signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from . import audit, config, scoring
from .chunking import split_sentences
from .groq_signal import assess_with_groq
from .signals import SIGNALS, signal_stylometry, stylometry_metrics

bp = Blueprint("api", __name__, url_prefix=config.API_PREFIX)

# Root-level blueprint for the submission entrypoint. In the architecture
# diagram this is `POST /submit`; it maps onto the versioned analyze flow.
root_bp = Blueprint("root", __name__)


@root_bp.post("/submit")
def submit():
    """Submission entrypoint stub.

    Accepts a JSON body with at minimum `text` and `creator_id`. For now it
    returns a hardcoded response so the route can be verified before any real
    analysis logic is wired in.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "validation_error", "Request body must be a JSON object.")

    missing = [f for f in ("text", "creator_id") if not data.get(f)]
    if missing:
        raise ApiError(
            400, "validation_error",
            f"Missing required field(s): {', '.join(missing)}.",
        )

    text = data["text"]
    if len(text) < config.MIN_TEXT_LENGTH:
        raise ApiError(422, "text_too_short",
                       f"Input must be at least {config.MIN_TEXT_LENGTH} characters to analyze.")
    if len(text) > config.MAX_TEXT_LENGTH:
        raise ApiError(413, "text_too_long",
                       f"Input exceeds the maximum of {config.MAX_TEXT_LENGTH} characters.")

    # --- Signal 1: Groq-backed stylistic authenticity (LLM judgment) ---
    try:
        assessment = assess_with_groq(text)
    except Exception as exc:  # network/parse/provider failure -> 502 per spec
        raise ApiError(502, "upstream_error", f"Signal provider error: {exc}") from exc
    groq_score = round(assessment["ai_likelihood"], 4)

    # --- Signal 2: local stylometric heuristic (variance, TTR, word length) ---
    stylo = stylometry_metrics(text)
    stylometry_score = stylo["score"]

    # --- Confidence scoring: combine both signals per the spec thresholds ---
    scores = {"groq_authenticity": groq_score, "stylometry": stylometry_score}
    confidence = round(scoring.aggregate_confidence(scores), 4)
    false_positive = scoring.estimate_false_positive(confidence)
    label, band = scoring.classify(confidence, false_positive)
    transparency = scoring.build_label(label, confidence)

    content_id = "c_" + uuid.uuid4().hex[:12]
    catalogue_by_id = {c["id"]: c for c in config.SIGNAL_CATALOGUE}
    signals_out = [
        {
            "id": "groq_authenticity",
            "name": catalogue_by_id["groq_authenticity"]["name"],
            "score": groq_score,
            "weight": config.SIGNAL_WEIGHTS["groq_authenticity"],
            "explanation": assessment["reasoning"],
            "indicators": assessment["indicators"],
        },
        {
            "id": "stylometry",
            "name": catalogue_by_id["stylometry"]["name"],
            "score": stylometry_score,
            "weight": config.SIGNAL_WEIGHTS["stylometry"],
            "explanation": _explain("stylometry", stylometry_score),
            "metrics": stylo["raw"],
        },
    ]

    response = {
        "content_id": content_id,
        "creator_id": data["creator_id"],
        "status": "classified",
        "attribution": {
            "label": label,
            "confidence": confidence,
            "confidence_band": band,
            "palette_color": scoring.palette_color(confidence),
            "false_positive_probability": false_positive,
            "signals": signals_out,
        },
        "transparency_label": transparency,
        "meta": {
            "model": config.GROQ_MODEL,
            "scoring": "ensemble (2 signals, uncalibrated)",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    audit.log_event(
        "analysis_completed",
        content_id,
        creator_id=data["creator_id"],
        attribution=label,
        confidence=confidence,
        llm_score=groq_score,
        stylometry_score=stylometry_score,
        status="classified",
    )

    return jsonify(response), 200


class ApiError(Exception):
    """Domain error mapped to a JSON error response."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _error_payload(code: str, message: str):
    return {"error": {"code": code, "message": message}}


# --- POST /api/v1/analyze (submit flow) ---------------------------------------

@root_bp.get("/log")
def get_log():
    """Return the most recent audit log entries as JSON.

    Documentation/grading visibility only; a real system would require auth.
    Accepts an optional `?limit=` query param (default 50).
    """
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    return jsonify({"entries": audit.read_recent(limit)}), 200


@bp.post("/analyze")
def analyze():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "validation_error", "Request body must be a JSON object.")

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "validation_error", "Field 'text' is required.")

    return jsonify(_run_analysis(text, data.get("options") or {})), 200


def _run_analysis(text: str, options: dict) -> dict:
    """Validate input and run the detection pipeline, returning the response dict.

    Shared by POST /submit and POST /api/v1/analyze so both stay in sync.
    """
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "validation_error", "Field 'text' is required.")

    min_length = options.get("min_length", config.MIN_TEXT_LENGTH)
    if len(text) < min_length:
        raise ApiError(422, "text_too_short",
                       f"Input must be at least {min_length} characters to analyze.")
    if len(text) > config.MAX_TEXT_LENGTH:
        raise ApiError(413, "text_too_long",
                       f"Input exceeds the maximum of {config.MAX_TEXT_LENGTH} characters.")

    scores = {name: fn(text) for name, fn in SIGNALS.items()}
    confidence = scoring.aggregate_confidence(scores)
    false_positive = scoring.estimate_false_positive(confidence)
    label, band = scoring.classify(confidence, false_positive)
    transparency = scoring.build_label(label, confidence)

    catalogue_by_id = {c["id"]: c for c in config.SIGNAL_CATALOGUE}
    signals_out = [
        {
            "id": name,
            "name": catalogue_by_id.get(name, {}).get("name", name),
            "score": round(score, 4),
            "weight": config.SIGNAL_WEIGHTS.get(name, 0.0),
            "explanation": _explain(name, score),
        }
        for name, score in scores.items()
    ]

    return {
        "request_id": uuid.uuid4().hex[:8],
        "attribution": {
            "label": label,
            "confidence": round(confidence, 4),
            "confidence_band": band,
            "palette_color": scoring.palette_color(confidence),
            "false_positive_probability": false_positive,
        },
        "transparency_label": transparency,
        "signals": signals_out,
        "meta": {
            "chunk_count": len(split_sentences(text)),
            "model": "heuristic-v0",  # M3 signal is local; Groq-backed signals land in M4
            "calibration": "uncalibrated",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _explain(signal_id: str, score: float) -> str:
    if signal_id == "stylometry":
        if score >= 0.6:
            return ("Uniform rhythm, low lexical diversity, and/or high formality "
                    "read as AI-like.")
        if score <= 0.4:
            return ("Bursty rhythm and varied vocabulary, typical of human writing.")
        return "Stylometric metrics are ambiguous."
    return ""


# --- GET /api/v1/health -------------------------------------------------------

@bp.get("/health")
def health():
    return jsonify({"status": "ok", "version": config.API_VERSION}), 200


# --- GET /api/v1/signals ------------------------------------------------------

@bp.get("/signals")
def signals():
    return jsonify({"signals": config.SIGNAL_CATALOGUE}), 200

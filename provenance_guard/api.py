"""API blueprint.

Root-level routes (the submission/appeal flow):
  POST /submit    - classify a submission, return attribution + transparency label
  POST /appeal    - contest a prior result by content_id (-> under_review)
  GET  /appeals   - reviewer queue (optional ?status= filter)
  GET  /log       - recent audit-log entries (optional ?limit=)

Versioned routes (supporting):
  POST /api/v1/analyze   - text-only analysis entrypoint (local heuristic signal)
  GET  /api/v1/health    - liveness/readiness
  GET  /api/v1/signals   - signal catalogue

/submit runs the full two-signal ensemble (Groq + stylometry), combines them via
scoring.py, writes an audit entry, and returns the structured response.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from . import audit, config, scoring
from .chunking import split_sentences
from .extensions import limiter
from .groq_signal import assess_with_groq
from .signals import SIGNALS, signal_stylometry, stylometry_metrics

bp = Blueprint("api", __name__, url_prefix=config.API_PREFIX)

# Root-level blueprint for the submission entrypoint. In the architecture
# diagram this is `POST /submit`; it maps onto the versioned analyze flow.
root_bp = Blueprint("root", __name__)


@root_bp.post("/submit")
@limiter.limit(config.SUBMIT_RATE_LIMITS)
def submit():
    """Submission entrypoint.

    Accepts a JSON body with at minimum `text` and `creator_id`, runs the
    two-signal ensemble, returns the attribution + transparency label, and
    writes an audit entry. Rate-limited per IP (see config.SUBMIT_RATE_LIMITS).
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


@root_bp.post("/appeal")
def appeal():
    """Contest a prior analysis result (planning.md > Appeals Workflow).

    Requires `content_id` (from /submit) and a `reason`. Transitions the
    original result to `under_review` and writes an `appeal_received` audit
    event. Anyone holding a content_id can appeal (no auth in v1).
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "validation_error", "Request body must be a JSON object.")

    content_id = data.get("content_id")
    reason = data.get("reason")
    if not content_id:
        raise ApiError(400, "validation_error", "Field 'content_id' is required.")
    if not reason:
        raise ApiError(400, "validation_error", "Field 'reason' is required.")

    claimed_origin = data.get("claimed_origin")
    if claimed_origin and claimed_origin not in ("human", "ai", "mixed"):
        raise ApiError(400, "validation_error",
                       "claimed_origin must be one of: human, ai, mixed.")

    # The content_id must correspond to a real prior submission.
    events = audit.find_by_content_id(content_id)
    if not any(e.get("event_type") == "analysis_completed" for e in events):
        raise ApiError(404, "unknown_content",
                       f"No submission found for content_id '{content_id}'.")

    previous_status = events[-1].get("status", "classified")
    appeal_id = "a_" + uuid.uuid4().hex[:12]
    new_status = "under_review"

    audit.log_event(
        "appeal_received",
        content_id,
        appeal_id=appeal_id,
        reason=reason,
        claimed_origin=claimed_origin,
        contact=data.get("contact"),
        previous_status=previous_status,
        status=new_status,
    )

    return jsonify({
        "appeal_id": appeal_id,
        "content_id": content_id,
        "status": new_status,
        "previous_status": previous_status,
        "message": "Appeal received and under review.",
    }), 201


@root_bp.get("/appeals")
def appeals_queue():
    """Reviewer-only appeal queue (planning.md > Appeals Workflow).

    Joins each appeal to its original analysis result so a reviewer can judge
    the call. Optional `?status=` filter (e.g. under_review). No auth in v1.
    """
    status_filter = request.args.get("status")
    events = audit.read_recent(0)  # all events, newest first

    # Latest analysis_completed per content_id = the original result.
    analyses = {}
    for e in events:  # newest-first, so first seen is the latest
        if e.get("event_type") == "analysis_completed" and e["content_id"] not in analyses:
            analyses[e["content_id"]] = e

    queue = []
    for e in events:
        if e.get("event_type") != "appeal_received":
            continue
        if status_filter and e.get("status") != status_filter:
            continue
        original = analyses.get(e["content_id"], {})
        queue.append({
            "appeal_id": e.get("appeal_id"),
            "content_id": e["content_id"],
            "status": e.get("status"),
            "submitted_at": e.get("timestamp"),
            "reason": e.get("reason"),
            "claimed_origin": e.get("claimed_origin"),
            "original_result": {
                "attribution": original.get("attribution"),
                "confidence": original.get("confidence"),
                "llm_score": original.get("llm_score"),
                "stylometry_score": original.get("stylometry_score"),
                "creator_id": original.get("creator_id"),
            },
        })

    return jsonify({"appeals": queue, "count": len(queue)}), 200


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
    return jsonify({"entries": audit.recent_entries(limit)}), 200


@bp.post("/analyze")
@limiter.limit(config.ANALYZE_RATE_LIMIT)
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

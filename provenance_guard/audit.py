"""Append-only audit log.

Every submission analysis and appeal writes an event here, keyed by `content_id`
so the appeal flow can look records up. Backed by a simple JSONL file for now;
swappable for a real datastore later without changing call sites.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from . import config


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def log_event(event_type: str, content_id: str, **fields) -> dict:
    """Append an event and return the persisted record."""
    record = {
        "event_id": uuid.uuid4().hex[:12],
        "event_type": event_type,
        "content_id": content_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    _ensure_parent(config.AUDIT_LOG_PATH)
    with open(config.AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def read_recent(limit: int = 50) -> list[dict]:
    """Return the most recent audit entries, newest first."""
    if not os.path.exists(config.AUDIT_LOG_PATH):
        return []
    with open(config.AUDIT_LOG_PATH, encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    recent = lines[-limit:] if limit else lines
    return [json.loads(line) for line in reversed(recent)]


def recent_entries(limit: int = 50) -> list[dict]:
    """Recent entries (newest first) with analysis rows annotated `appeal_filed`.

    The append-only log stores analysis and appeal events separately; this view
    cross-references them so each classification entry shows whether an appeal
    has since been filed for that content_id.
    """
    all_events = read_recent(0)  # everything, newest first
    appealed = {
        e["content_id"] for e in all_events
        if e.get("event_type") == "appeal_received"
    }
    sliced = all_events[:limit] if limit else all_events
    out = []
    for e in sliced:
        e = dict(e)
        if e.get("event_type") == "analysis_completed":
            e["appeal_filed"] = e["content_id"] in appealed
        out.append(e)
    return out


def find_by_content_id(content_id: str) -> list[dict]:
    """Return all events for a content_id (used by the appeal flow)."""
    if not os.path.exists(config.AUDIT_LOG_PATH):
        return []
    events = []
    with open(config.AUDIT_LOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("content_id") == content_id:
                events.append(rec)
    return events

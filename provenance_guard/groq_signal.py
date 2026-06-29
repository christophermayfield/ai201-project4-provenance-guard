"""Groq-backed detection signal.

Sends the text to Groq with a prompt that returns a *structured* JSON
assessment, then maps it to the standard signal contract:

    signal_groq_authenticity(text: str) -> float   # [0.0, 1.0]; 1.0 = AI-like

The model is asked to judge tone/voice authenticity (the "risk-averse, bland,
flawless-but-hollow" indicators from planning.md), which complements the local
rhythm-variance heuristic.
"""

from __future__ import annotations

import json

from groq import Groq

from . import config

_SYSTEM_PROMPT = (
    "You are a forensic writing analyst. Assess how likely a passage was "
    "AI-generated based on stylistic indicators: unnaturally consistent rhythm, "
    "risk-averse/bland 'textbook' tone, flawless-but-hollow grammar, hallucinated "
    "specifics, and an absence of genuine personal voice or anecdote. "
    "You are NOT judging whether the content is true or well-written, only "
    "whether its STYLE reads as machine-generated. "
    "Respond ONLY with a JSON object of the form: "
    '{"ai_likelihood": <float 0.0-1.0>, "reasoning": "<one sentence>", '
    '"indicators": ["<short phrase>", ...]}. '
    "0.0 = clearly human voice, 1.0 = clearly AI-generated."
)

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set; cannot run the Groq signal.")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def assess_with_groq(text: str) -> dict:
    """Call Groq and return the parsed structured assessment.

    Returns a dict: {"ai_likelihood": float, "reasoning": str, "indicators": [str]}.
    Raises on transport/parse errors so callers can map to an upstream error.
    """
    client = _get_client()
    completion = client.chat.completions.create(
        model=config.GROQ_MODEL,
        temperature=0,
        timeout=config.GROQ_TIMEOUT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    raw = completion.choices[0].message.content
    data = json.loads(raw)

    score = float(data.get("ai_likelihood", 0.5))
    return {
        "ai_likelihood": max(0.0, min(1.0, score)),
        "reasoning": str(data.get("reasoning", "")),
        "indicators": list(data.get("indicators", [])),
    }


def signal_groq_authenticity(text: str) -> float:
    """Signal-contract wrapper: return just the [0.0, 1.0] AI-likelihood score."""
    return assess_with_groq(text)["ai_likelihood"]

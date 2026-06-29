"""Independent test for signal 2 (stylometry) + agreement check vs signal 1.

Runs the stylometric signal on the SAME inputs used for signal 1 (the Groq
signal in scripts/try_groq_signal.py), prints the metric breakdown, and compares
the two signals to see where they agree / diverge.

Run: python scripts/try_signal2.py     (Groq comparison needs a valid GROQ_API_KEY)
"""

import json

from dotenv import load_dotenv

load_dotenv(".env")

from provenance_guard.signals import stylometry_metrics  # noqa: E402

# Same inputs as scripts/try_groq_signal.py
SAMPLES = {
    "likely_ai": (
        "Effective time management is essential for productivity. By prioritizing "
        "tasks and setting clear goals, individuals can optimize their workflow. "
        "It is important to minimize distractions and maintain focus. Consistent "
        "habits contribute significantly to long-term success."
    ),
    "likely_human": (
        "I bombed the interview. Spilled coffee on my one good shirt in the lobby, "
        "then blanked on the founder's name mid-handshake. My roommate says it "
        "builds character. My bank account disagrees, loudly, every first of the month."
    ),
    "edge_repetitive_poem": (
        "Rain falls down. Rain falls slow. Rain falls soft. Rain falls cold. "
        "Rain falls now."
    ),
}


def _leaning(score: float) -> str:
    return "AI-like" if score >= 0.6 else "human-like" if score <= 0.4 else "ambiguous"


def main() -> None:
    # Optional: compare against signal 1 (Groq). Degrade gracefully if no network.
    try:
        from provenance_guard.groq_signal import signal_groq_authenticity
        groq_ok = True
    except Exception:  # noqa: BLE001
        groq_ok = False

    for name, text in SAMPLES.items():
        print(f"\n=== {name} ===")
        m = stylometry_metrics(text)
        print("  stylometry metrics:", json.dumps(m["raw"]))
        print("  stylometry sub-scores:", json.dumps(m["sub_scores"]))
        s2 = m["score"]
        print(f"  signal 2 (stylometry): {s2:.3f} -> {_leaning(s2)}")

        if groq_ok:
            try:
                s1 = signal_groq_authenticity(text)
                agree = _leaning(s1) == _leaning(s2)
                print(f"  signal 1 (groq):       {s1:.3f} -> {_leaning(s1)}")
                print(f"  --> signals {'AGREE' if agree else 'DISAGREE'} "
                      f"(|delta| = {abs(s1 - s2):.3f})")
            except Exception as exc:  # noqa: BLE001
                print(f"  signal 1 (groq): unavailable ({type(exc).__name__})")


if __name__ == "__main__":
    main()

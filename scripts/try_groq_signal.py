"""Independent test for the Groq-backed signal.

Calls the signal function directly with a few inputs and inspects the structured
output BEFORE it is wired into the endpoint. Run: python scripts/try_groq_signal.py
Requires a valid GROQ_API_KEY in .env.
"""

import json

from dotenv import load_dotenv

load_dotenv()

from provenance_guard.groq_signal import assess_with_groq  # noqa: E402

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


def main() -> None:
    for name, text in SAMPLES.items():
        print(f"\n=== {name} ===")
        try:
            result = assess_with_groq(text)
            print(json.dumps(result, indent=2))
        except Exception as exc:  # noqa: BLE001 - this is a manual diagnostic
            print(f"ERROR: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()

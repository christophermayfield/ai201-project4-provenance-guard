"""M3 verification harness.

Per planning.md > AI Tool Plan > M3: call the first signal directly on a few
inputs and confirm scores move in the expected direction *before* trusting the
endpoint. Run: python scripts/try_signal.py
"""

from provenance_guard.signals import signal_stylometry

SAMPLES = {
    "uniform_ai_like": (
        "The system processes the request. The system validates the input. "
        "The system returns a response. The system logs the event. The system "
        "updates the record."
    ),
    "bursty_human_like": (
        "I froze. The whole plan, the months of saving, the cheap flight I'd "
        "bragged about to everyone back home, all of it unraveled in the time it "
        "took the agent to say 'cancelled.' Now what?"
    ),
    "repetitive_poem_edge_case": (
        "Rain falls down. Rain falls slow. Rain falls soft. Rain falls cold. "
        "Rain falls now."
    ),
}


def main() -> None:
    print(f"{'sample':<28} {'score':>6}  interpretation")
    print("-" * 60)
    for name, text in SAMPLES.items():
        score = signal_stylometry(text)
        leaning = "AI-like" if score >= 0.6 else "human-like" if score <= 0.4 else "ambiguous"
        print(f"{name:<28} {score:>6.3f}  {leaning}")


if __name__ == "__main__":
    main()

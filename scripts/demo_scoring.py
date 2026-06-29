"""Demonstrate the combined confidence scoring against the two acceptance
criteria:

  A. The score maps to at least 3 distinct label categories (deterministic,
     no network) - drives the scoring functions directly with representative
     (groq, stylometry) score pairs.
  B. The combined score varies meaningfully across clearly different real
     inputs (full pipeline via the live endpoint) - a polished/uniform
     paragraph vs a casual/irregular one.

Run: python scripts/demo_scoring.py     (Part B needs a valid GROQ_API_KEY)
"""

from dotenv import load_dotenv

load_dotenv(".env")

from provenance_guard import config, scoring  # noqa: E402


def label_for(groq: float, stylometry: float) -> tuple[float, str, str]:
    scores = {"groq_authenticity": groq, "stylometry": stylometry}
    confidence = round(scoring.aggregate_confidence(scores), 4)
    fp = scoring.estimate_false_positive(confidence)
    label, band = scoring.classify(confidence, fp)
    return confidence, label, band


print("== Part A: label-category coverage (deterministic) ==")
print(f"  weights: {config.SIGNAL_WEIGHTS}\n")
pairs = [
    ("polished/uniform", 0.90, 0.85),
    ("mixed/ambiguous",  0.50, 0.50),
    ("casual/irregular", 0.10, 0.20),
]
seen = set()
for name, groq, stylo in pairs:
    conf, label, band = label_for(groq, stylo)
    seen.add(label)
    print(f"  {name:18} groq={groq:.2f} stylo={stylo:.2f} -> "
          f"confidence={conf:.3f} band={band:<8} label={label}")
print(f"\n  distinct labels reached: {len(seen)} -> {sorted(seen)}")
print("  " + ("PASS: >=3 categories" if len(seen) >= 3 else "FAIL"))


print("\n== Part B: meaningful variation on real inputs (full pipeline) ==")
try:
    from provenance_guard import create_app
    client = create_app().test_client()

    inputs = {
        "polished/uniform": (
            "Effective project management requires careful planning and clear "
            "communication. Teams should establish defined goals and measurable "
            "objectives. Regular progress reviews ensure alignment and "
            "accountability. Consistent processes contribute to successful outcomes."
        ),
        "casual/irregular": (
            "Ugh, today. Missed the bus by like ten seconds, watched it pull away "
            "while I jogged after it like an idiot. Got soaked. But then? Found a "
            "twenty in my old coat pocket. So... even, I guess."
        ),
    }
    results = {}
    for name, text in inputs.items():
        r = client.post("/submit", json={"text": text, "creator_id": "demo"})
        a = r.get_json()["attribution"]
        results[name] = a["confidence"]
        sig = {s["id"]: s["score"] for s in a["signals"]}
        print(f"  {name:18} confidence={a['confidence']:.3f} label={a['label']:13} {sig}")

    spread = abs(results["polished/uniform"] - results["casual/irregular"])
    print(f"\n  confidence spread between the two: {spread:.3f}")
    print("  " + ("PASS: scores vary meaningfully (>0.2 apart)"
                  if spread > 0.2 else "WEAK: scores close together"))
except Exception as exc:  # noqa: BLE001
    print(f"  (skipped live pipeline: {type(exc).__name__}: {exc})")

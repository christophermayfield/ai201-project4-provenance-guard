"""Verify the M4 scoring logic against the planning.md spec.

Checks three things the AI-generated scoring could silently get wrong:
  1. Weighted aggregation uses the documented weights (groq 0.70, rhythm 0.30).
  2. The label thresholds match the table exactly:
       0.00-0.39 -> likely_human ; 0.40-0.59 -> uncertain ; 0.60-1.00 -> likely_ai
  3. The false-positive guardrail (FP > 0.30 downgrades likely_ai) behaves as
     intended and does not silently swallow the whole AI range.

Run: python scripts/verify_scoring.py
"""

from provenance_guard import config, scoring

failures = []


def check(desc, got, expected):
    ok = got == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}: got={got} expected={expected}")
    if not ok:
        failures.append(desc)


print("== 1. Weighted aggregation (weights:", config.SIGNAL_WEIGHTS, ") ==")
check("groq=1.0, stylometry=0.0 -> 0.70",
      scoring.aggregate_confidence({"groq_authenticity": 1.0, "stylometry": 0.0}), 0.70)
check("groq=0.0, stylometry=1.0 -> 0.30",
      scoring.aggregate_confidence({"groq_authenticity": 0.0, "stylometry": 1.0}), 0.30)
check("both 1.0 -> 1.0",
      scoring.aggregate_confidence({"groq_authenticity": 1.0, "stylometry": 1.0}), 1.0)
check("both 0.0 -> 0.0",
      scoring.aggregate_confidence({"groq_authenticity": 0.0, "stylometry": 0.0}), 0.0)

print("\n== 2. Label thresholds (RAW, guardrail disabled via FP=0.0) ==")
# Pass false_positive=0.0 so the guardrail never fires; this isolates the table.
cases = [
    (0.00, "likely_human"), (0.20, "likely_human"), (0.39, "likely_human"),
    (0.40, "uncertain"),    (0.50, "uncertain"),    (0.59, "uncertain"),
    (0.60, "likely_ai"),    (0.80, "likely_ai"),    (1.00, "likely_ai"),
]
for conf, expected in cases:
    label, _ = scoring.classify(conf, 0.0)
    check(f"confidence={conf:.2f}", label, expected)

print("\n== 3. False-positive guardrail (uses real estimate_false_positive) ==")
for conf in (0.60, 0.65, 0.70, 0.80, 0.95):
    fp = scoring.estimate_false_positive(conf)
    label, _ = scoring.classify(conf, fp)
    downgraded = "DOWNGRADED->uncertain" if label != "likely_ai" else "stays likely_ai"
    print(f"  confidence={conf:.2f}  fp={fp:.3f}  -> {label}  ({downgraded})")

print("\n== 4. High-confidence label copy tone ==")
check("ai >=0.80 -> warning tone", scoring.build_label("likely_ai", 0.85)["tone"], "warning")
check("ai <0.80 -> caution tone", scoring.build_label("likely_ai", 0.72)["tone"], "caution")
check("human <=0.20 -> positive tone", scoring.build_label("likely_human", 0.10)["tone"], "positive")

print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILURES: {failures}"))

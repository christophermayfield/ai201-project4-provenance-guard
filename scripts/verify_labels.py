"""Verify the label-generation function against the planning.md spec.

Produces all three transparency-label variants and confirms the text matches
exactly what was written in planning.md > Transparency Label Variants. The
expected strings below are copied verbatim from planning.md, minus the markdown
bold (`**`) emphasis, which is documentation formatting only - the API payload
carries plain text.

Run: python scripts/verify_labels.py     (no network needed)
"""

from provenance_guard import scoring

# Verbatim from planning.md (bold ** stripped; em dash preserved).
EXPECTED = {
    "likely_ai": (  # high-confidence AI, confidence >= 0.80
        "Likely AI-generated. This content shows strong, consistent indicators "
        "of AI generation across multiple signals. Treat attribution claims with "
        "caution and verify independently where it matters."
    ),
    "likely_human": (  # high-confidence human, confidence <= 0.20
        "Likely human-written. This content shows the natural variation, voice, "
        "and specificity typical of human writing. No strong AI indicators were "
        "detected."
    ),
    "uncertain": (  # 0.40 <= confidence <= 0.59
        "Inconclusive. The signals are mixed and we can't reliably attribute "
        "this content. This is an estimate, not proof \u2014 please use your own "
        "judgment and additional context before drawing conclusions."
    ),
}

# Representative confidences that should select each high-confidence variant.
CASES = [("likely_ai", 0.90), ("uncertain", 0.50), ("likely_human", 0.10)]

failures = []
for expected_category, confidence in CASES:
    result = scoring.generate_label(confidence)
    cat_ok = result["category"] == expected_category
    text_ok = result["text"] == EXPECTED[expected_category]
    print(f"confidence={confidence:.2f} -> category={result['category']} "
          f"tone={result['tone']}")
    print(f"  text: {result['text']}")
    print(f"  [{'PASS' if cat_ok else 'FAIL'}] category == {expected_category}")
    print(f"  [{'PASS' if text_ok else 'FAIL'}] text matches planning.md verbatim\n")
    if not (cat_ok and text_ok):
        failures.append(expected_category)

print("ALL LABEL VARIANTS MATCH SPEC" if not failures else f"FAILURES: {failures}")

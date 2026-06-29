"""Text chunking utilities.

Pipeline step 2 (planning.md > Pipeline mapping): break raw text into
meaningful units the signals can operate on. For the rhythm signal the relevant
unit is the sentence.
"""

from __future__ import annotations

import re

# Split on sentence-ending punctuation followed by whitespace. Deliberately
# simple/heuristic; good enough for length-variance analysis without an NLP dep.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, dropping empties and surrounding whitespace."""
    parts = _SENTENCE_BOUNDARY.split(text.strip())
    return [s.strip() for s in parts if s.strip()]


def word_count(sentence: str) -> int:
    """Count word-like tokens in a sentence."""
    return len(re.findall(r"\b\w+\b", sentence))

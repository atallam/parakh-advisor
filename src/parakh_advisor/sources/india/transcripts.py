"""Checks on a downloaded concall transcript, ported from the old Parakh/Drishti concall engine.

A cover page, a link list or a garbled PDF must never be saved as evidence, because the thesis step would
then cite it and raise confidence. `validate_transcript` returns its reasons so a rejection is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass

TRANSCRIPT_KEYWORDS = (
    "revenue", "growth", "quarter", "management", "analyst", "guidance", "margin", "board",
    "crore", "ebitda", "profit", "operator", "participants", "conference", "results",
)  # fmt: skip
MIN_CHARS = 2_000  # shorter texts were link lists or cover pages in live checks
MIN_KEYWORDS = 3
MAX_NON_ASCII_RATIO = 0.15  # garbled encodings exceed this
WORD_LEN_RANGE = (3.0, 15.0)  # average word length of real English prose
QA_MARKERS = (
    "question and answer", "q&a session", "questions from", "we will now begin",
    "open for questions", "analyst questions", "we will now take questions",
)  # fmt: skip


@dataclass(frozen=True)
class Validation:
    ok: bool
    reasons: tuple[str, ...] = ()


def validate_transcript(text: str) -> Validation:
    """Four heuristics; all must pass."""
    if not text or len(text) < MIN_CHARS:
        return Validation(False, (f"too short ({len(text or '')} characters, need {MIN_CHARS})",))
    reasons = []
    lower = text.lower()
    hits = sum(1 for kw in TRANSCRIPT_KEYWORDS if kw in lower)
    if hits < MIN_KEYWORDS:
        reasons.append(f"only {hits} concall words found (need {MIN_KEYWORDS})")
    non_ascii = sum(1 for c in text if ord(c) > 127) / len(text)
    if non_ascii > MAX_NON_ASCII_RATIO:
        reasons.append(f"{non_ascii:.0%} unreadable characters")
    words = text.split()[:500]
    if words:
        avg = sum(len(w) for w in words) / len(words)
        if not WORD_LEN_RANGE[0] <= avg <= WORD_LEN_RANGE[1]:
            reasons.append(f"average word length {avg:.1f} looks like garbled text")
    return Validation(not reasons, tuple(reasons))


def truncate_transcript(text: str, max_chars: int) -> str:
    """Keep the opening remarks and the whole Q&A when possible, else the first 60% and the last 40%."""
    if len(text) <= max_chars:
        return text
    lower = text.lower()
    for marker in QA_MARKERS:
        pos = lower.find(marker)
        if pos > 0:
            preamble = text[: min(pos, max_chars // 3)]
            return (preamble + "\n\n[...]\n\n" + text[pos:])[:max_chars]
    split = int(max_chars * 0.6)
    head, tail = text[:split], text[-(max_chars - split) :]
    stop = head.rfind(".")
    if stop > split - 200:
        head = head[: stop + 1]
    return head + "\n\n[... truncated ...]\n\n" + tail

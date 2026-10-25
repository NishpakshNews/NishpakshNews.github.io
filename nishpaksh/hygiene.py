"""Source hygiene at ingest (B10): broken text mended, and the language of each sentence known, not guessed from one letter.

repair    mojibake ("à¤¨à¤®à¤¸à¥à¤¤à¥‡" for Hindi, "â€™" for a quote) is undone by ftfy when it is installed; without it, by the
          one repair that is safe on its own: text that is valid UTF-8 read as Latin-1/CP1252, accepted only when the result has
          fewer suspicious characters than the input. Text with none of the marks is returned untouched.
profile   per sentence, the share of Devanagari and Latin letters: a sentence is "hi" (mostly Devanagari), "en" (mostly Latin),
          "mixed" (both in quantity: Hinglish, a name in brackets) or "none" (no letters). A report is the language most of its
          sentences are; `leaks` are the sentences of the OTHER language in it (the Hindi that turned up inside an English page).
Counted, never enforced, except `repair`, which changes the text only when the change is clearly right.
"""
from __future__ import annotations

import collections
import re

STATS = collections.Counter()
_MARKS = re.compile("[\u00c2\u00c3\u00e0\u00e2][\u0080-\u00bf\u2018-\u203a\u20ac\u2122\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u02c6\u02dc]")
_DEVA = re.compile("[\u0900-\u097f]")
_LATIN = re.compile(r"[A-Za-z]")
MIXED = 0.25            # the smaller script's share of a sentence's letters that makes it mixed


def _suspect(t: str) -> int:
    return len(_MARKS.findall(t)) + t.count("�")


def repair(text: str) -> str:
    """The text with mojibake undone, or the text itself."""
    t = text or ""
    if not t or not _suspect(t):
        return t
    try:
        import ftfy
        fixed = ftfy.fix_text(t)
    except ImportError:
        fixed = t
        for enc in ("cp1252", "latin-1"):
            try:
                cand = t.encode(enc).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if _suspect(cand) < _suspect(t):
                fixed = cand
                break
    if fixed != t and _suspect(fixed) < _suspect(t):
        STATS["repaired"] += 1
        return fixed
    return t


def kind(sentence: str) -> str:
    d, l = len(_DEVA.findall(sentence)), len(_LATIN.findall(sentence))
    if d + l == 0:
        return "none"
    small, big = sorted((d, l))
    if small / (d + l) >= MIXED:
        return "mixed"
    return "hi" if d > l else "en"


def profile(text: str) -> dict[str, int]:
    from .fidelity import sentences
    c = collections.Counter(kind(s) for s in sentences(text))
    return {k: c.get(k, 0) for k in ("hi", "en", "mixed", "none")}


def language(text: str) -> str:
    """"hi" / "en" / "mixed" for a report: the language most of its lettered sentences are in."""
    p = profile(text)
    n = p["hi"] + p["en"] + p["mixed"]
    if n == 0:
        return "en"
    if p["hi"] / n >= 0.6:
        return "hi"
    if p["en"] / n >= 0.6:
        return "en"
    return "mixed"


def leaks(text: str, lang: str | None = None) -> list[str]:
    """The sentences of a report that are in the other language than the report's (or than `lang`)."""
    from .fidelity import sentences
    base = lang or language(text)
    if base == "mixed":
        return []
    other = "en" if base == "hi" else "hi"
    return [s for s in sentences(text) if kind(s) == other]

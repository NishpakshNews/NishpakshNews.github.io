"""Evidence spans by sentence number (B3): the reading model POINTS at the source sentence, it does not copy it.

The text of a report is shown to the reading model with its sentences numbered ("[3] Police arrested ..."), and each item
carries `src`: the numbers of the sentence(s) it was read from. Code turns the numbers into the report's own sentences (the
model cannot misquote a number) and keeps the pointer only when the statement and the sentence share an anchor (a figure by
value, a date, a name: `fidelity.anchors`); a statement with no anchor at all has nothing to contradict, so its pointer stands.
A pointer that fails the test is dropped and counted; the older ways of finding the sentence (the copied first words, the
anchors) take over. The span is what the reading check (NLI, QA) and the coverage count compare the statement with.
"""
from __future__ import annotations

import collections

STATS = collections.Counter()
MAX_SRC = 3


def number(text: str) -> tuple[str, list[str]]:
    """(the text with "[n] " in front of every sentence, the sentences). Line breaks between paragraphs are kept."""
    from .fidelity import sentences
    sents = sentences(text)
    return "\n".join(f"[{k + 1}] {s}" for k, s in enumerate(sents)), sents


def pointers(value) -> list[int]:
    out = []
    for v in value if isinstance(value, list) else [value]:
        try:
            n = int(str(v).strip().strip("[]sS"))
        except (TypeError, ValueError):
            continue
        if n >= 1 and n not in out:
            out.append(n)
    return out[:MAX_SRC]


def span(src, sents: list[str], statement: str, lang: str = "en", registry=None) -> str | None:
    """The report's sentence(s) the numbers point at, or None (no pointer, a number outside the report, or no shared anchor)."""
    ns = pointers(src)
    if not ns:
        STATS["no_pointer"] += 1
        return None
    if any(n > len(sents) for n in ns):
        STATS["out_of_range"] += 1
        return None
    text = " ".join(sents[n - 1] for n in sorted(ns))
    from . import figures
    from .fidelity import anchors
    from .people import NAME
    wants = bool(figures.values(statement)) or bool(NAME.search(statement or ""))
    if wants and anchors(statement, text, lang, registry) == 0:
        STATS["no_shared_anchor"] += 1
        return None
    STATS["kept"] += 1
    return text

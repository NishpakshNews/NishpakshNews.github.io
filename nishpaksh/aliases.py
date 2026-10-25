"""Names an outlet itself says are one person (B2): "X alias Y", "X urf Y", "X, also known as Y", "X उर्फ Y".

The cue is a grammatical construction (the alias marker between two names), not a list of people. Both sides must be named
entities the parser calls a PERSON; the pair is then passed to the entity table as explicit evidence (EntityTable.link), which
unifies the two identities. Evidence from one outlet's wording is not a fact about the world: it unifies names inside one story's
table only and is never stored.
"""
from __future__ import annotations

import re

from . import nlp

CUE = r"(?:alias|urf|aka|a\.k\.a\.?|also known as|also called|known as|उर्फ)"
_PAIR = re.compile(rf"(?P<a>[^,.;()\n]{{3,60}}?)\s*,?\s*{CUE}\s+(?P<b>[^,.;()\n]{{3,60}})", re.I)


def find(text: str) -> list[tuple[str, str]]:
    out = []
    for m in _PAIR.finditer(text or ""):
        left, right = m.group("a").strip(), m.group("b").strip()
        # the left name is the last person in its span, the right name the first one
        lp = [e.text for e in nlp.ents(left) if e.label == nlp.PERSON]
        rp = [e.text for e in nlp.ents(right) if e.label == nlp.PERSON]
        if lp and rp and lp[-1].lower() != rp[0].lower():
            out.append((lp[-1], rp[0]))
    return out

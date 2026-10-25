"""Cross-lingual entity linking (B2): a Devanagari mention is the same entity as the English name the registry pairs it with.

The name registry (names.py) holds, part by part, the spelling English outlets use and the spelling Hindi outlets use,
learned only from outlets that covered the same story. A Hindi speaker or Hindi words in a statement are turned into
that English spelling BEFORE they enter the entity table, so "रिम्पोछे" and "Rimpochee" are one entity and one speaker key,
by the table's ordinary rules. Exact lookup only (no similarity): a word the registry does not know stays as written and
links to nothing. No registry in scope = nothing changes.
"""
from __future__ import annotations

import contextvars
import re

DEV = re.compile(r"[ऀ-ॿ]")
_current: contextvars.ContextVar = contextvars.ContextVar("np_registry", default=None)


def use(reg) -> None:
    _current.set(reg)


def current():
    return _current.get()


def to_english(text: str, reg=None) -> str:
    """The Devanagari name runs the registry knows replaced by their English spelling; the rest as written."""
    reg = reg if reg is not None else _current.get()
    if not text or reg is None or not DEV.search(text):
        return text
    from . import namepair
    out = text
    for hindi, english in sorted(namepair.hints(text, reg), key=lambda p: -len(p[0])):
        out = out.replace(hindi, english)
    return out

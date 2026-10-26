"""A speaker is VERIFIED, never typed (Oct 26 2026, story 45108: ", article said." printed five times).

The review model names who said a statement. Its answer is a proposal: the reading step recorded who each report
attributed the statement to (`claims.attributed_to`), and the model was shown those words, but it echoed the
placeholder the reading step uses for "no attribution" (the word "article"), and nothing checked the answer, so the
placeholder became a speaker. The rule, with no list of words: an answer stands only if
  1. it matches a real attribution a report gave for THIS statement (words in common, the placeholder aside), or
  2. it names an organisation, person, place or group (the language analyser) whose words stand in the statement
     itself ("The India Meteorological Department issued a bulletin": the department is the speaker of its own act).
Anything else is no speaker. The placeholder is whatever the reading step stores for "no attribution": the value
every report of the story gives most often when no statement names a person (`placeholder`), plus the words origins.py
already treats as the outlet's own voice.
"""
from __future__ import annotations

import re

from . import origins

_STOP = {"the", "a", "an", "of", "and", "for", "in", "on", "to"}


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _STOP}


def own_voice(s: str) -> bool:
    return re.sub(r"^the ", "", (s or "").strip().lower()) in origins.OWN_WORDS or (s or "").strip().lower() in origins.OWN_WORDS


def verify(candidate: str, offered, text: str = "") -> str | None:
    """The speaker to keep for a statement, or None. `offered`: the attributions the reports gave this statement."""
    cand = (candidate or "").strip()
    if not cand or own_voice(cand):
        return None
    cw = _words(cand)
    if not cw:
        return None
    for o in offered or ():
        if own_voice(o):
            continue
        ow = _words(o)
        if ow and (cw <= ow or ow <= cw or len(cw & ow) >= max(1, min(len(cw), len(ow)) // 2 + (1 if min(len(cw), len(ow)) > 1 else 0))):
            return cand
    from . import nlp
    tw = _words(text)
    for e in nlp.ents(cand):
        if e.label in nlp.NOT_PERSON_LABELS | {nlp.PERSON} and _words(e.text) and _words(e.text) <= tw:
            return cand
    return None

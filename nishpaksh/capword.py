"""Is this capitalised word a name? Asked of the analyser, not of a hand-written word list (owner, Oct 28 2026).

Seven places kept their own sets of "capitalised words that are not names" (worldgate, people, refs, textmatch, recap,
narrative: months, days, pronouns, prepositions, "Police", "Court" ...). Each set was written for the cases seen and each
missed the next ("Authorities", "Some", "Local"). The analyser (spaCy, `nlp.py`) already answers it:
  * a word inside a named entity is a name, unless the entity is a date, a time or a quantity;
  * otherwise the part of speech: PROPN is a name; a determiner, preposition, pronoun, conjunction, auxiliary, adverb,
    number, noun, verb or adjective is not (so "October", "Meanwhile", "Authorities" never need listing);
  * in a HEADLINE-CASE text ("Police Arrest Man After Court Ruling": most words capitalised) the part of speech of a
    capitalised word is not trustworthy, so only the closed classes (determiner, preposition, pronoun, conjunction,
    auxiliary, adverb, number: reliable in any case) and entities count; anything else is not decided here.
Not decided (no analyser, an analyser that gives no part of speech, a headline-case word) = the caller's OLD LIST answers,
which stays as the fallback (owner: "keep them as fallback for audit"). `STATS` counts how often the two disagree, in each
direction, so the audit can read which list was wrong before any list is deleted (`tools/evaluate.py`, section
"capword"). Devanagari words are not judged here.
"""
from __future__ import annotations

import re
from collections import Counter

from . import auditcount, nlp

STATS: Counter = auditcount.counter("capword")
NOT_NAME_ENTS = {"DATE", "TIME", "CARDINAL", "ORDINAL", "PERCENT", "MONEY", "QUANTITY"}
CLOSED = {"DET", "ADP", "PRON", "CCONJ", "SCONJ", "AUX", "ADV", "PART", "INTJ", "NUM", "PUNCT", "SYM"}
HEADLINE_SHARE = 0.6        # of the words of 3+ letters this share capitalised = headline case (untuned)
HEADLINE_MIN = 4
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


def reset() -> None:
    STATS.clear()


def headline_case(text: str) -> bool:
    ws = [w for w in _WORD.findall(text or "") if len(w) >= 3]
    return len(ws) >= HEADLINE_MIN and sum(w[0].isupper() for w in ws) / len(ws) >= HEADLINE_SHARE


def verdicts(text: str) -> dict[int, bool | None] | None:
    """{start offset of a token: True (name) / False (not a name) / None (not decided)} for the Latin words of a text;
    None when the text could not be analysed or the analyser gives no part of speech."""
    toks = nlp.parse(text)
    if not toks or not any(t.pos for t in toks):
        return None
    spans = [(e.start, e.end, e.label) for e in nlp.ents(text)]
    headline = headline_case(text)
    out: dict[int, bool | None] = {}
    for t in toks:
        if not t.text or not t.text[0].isascii() or not t.text[0].isalpha():
            continue
        if not t.pos:                      # no part of speech for this word: not decided
            out[t.start] = None
            continue
        ent = next((lab for a, b, lab in spans if a <= t.start < b), None)
        if ent is not None:
            out[t.start] = ent not in NOT_NAME_ENTS
        elif t.pos in CLOSED:
            out[t.start] = False
        elif headline:
            out[t.start] = None
        else:
            out[t.start] = t.pos == "PROPN"
    return out


def is_name(word: str, text: str, start: int | None = None, listed_name: bool = True) -> bool:
    """Is `word` (capitalised, standing at `start` in `text`) a name? `listed_name` is the old list's answer (True = the
    list does not call it a common word); it is the answer when the analyser does not decide."""
    v = verdicts(text)
    if v is None:
        STATS["unread"] += 1
        return listed_name
    if start is None:
        start = text.find(word)
    s = v.get(start)
    if s is None:
        STATS["undecided"] += 1
        return listed_name
    STATS["asked"] += 1
    if s != listed_name:
        STATS["system_name_list_not" if s else "system_not_list_name"] += 1
    return s


def name_flags(text: str, words: list[tuple[str, int, bool]]) -> list[bool]:
    """is_name for several (word, start, listed_name) of one text."""
    return [is_name(w, text, st, ln) for w, st, ln in words]


def stats() -> dict:
    return dict(STATS)

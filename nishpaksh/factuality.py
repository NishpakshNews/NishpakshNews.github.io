"""Polarity and certainty of a statement, read from the dependency parse (B22): a statement says something is so, is not so, or
may be so. The reading model's stance values (asserts / attributes / denies) say WHO stands behind a statement; these two say
HOW it is put, and code reads them from the sentence's grammar, not from the model:
  polarity   "neg" when a main-clause predicate carries a negation (dependency label `neg`), else "pos"
  certainty  "possible" when a possibility modal (MD tag, lemma may / might / could) governs the main verb, else "stated"
A possible statement is not a fact that could be established: `checkworthy.classify` treats it as a characterisation, so it can
never be green. A parse that cannot run gives "unknown" and changes nothing.
"""
from __future__ import annotations

from . import nlp

POSSIBLE = {"may", "might", "could"}


def read(text: str) -> dict:
    toks = nlp.parse(text or "")
    if not toks:
        return {"polarity": "unknown", "certainty": "unknown"}
    heads = {t.head for t in toks if t.dep == "ROOT"} | {t.i for t in toks if t.dep == "ROOT"}
    neg = any(t.dep == "neg" and t.head in heads for t in toks)
    possible = any(t.tag == "MD" and t.lemma.lower() in POSSIBLE and t.head in heads for t in toks)
    return {"polarity": "neg" if neg else "pos", "certainty": "possible" if possible else "stated"}


def possible(text: str) -> bool:
    return read(text)["certainty"] == "possible"

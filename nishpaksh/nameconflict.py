"""What does it mean when the reports give different names for one fact? (B17) Three cases, decided by code.

  alias        the names are one identity under the entity table (entities.py: same name through spelling, or one an ordered
               part of the other): there is nothing to dispute. The flag may go.
  distinct     the names stand together in one sentence of a statement or report, not joined as aliases ("X alias Y", "X (Y)"):
               two people. The flag goes (as before): the statements are about two people, not one named two ways.
  disagreement everything else: the reports really name different people for one fact, or code cannot tell. The flag STAYS
               (the statement cannot be established; the writer prints whose version is which).

Only evidence that the names are not in conflict can remove a flag, and only structural evidence does: this is never the
way to make a statement more certain by a guess.
"""
from __future__ import annotations

import re

ALIAS = re.compile(r"(?i)\b(?:alias|urf|also known as|a\.?k\.?a\.?|also called|known as|or)\b|[(/]|उर्फ")


def named_together(names: list[str], texts: list[str | None]) -> bool:
    low = [n.lower() for n in names if n and len(n) >= 4]
    for text in texts:
        for sent in re.split(r"(?<=[.!?।])\s+", text or ""):
            s = sent.lower()
            found = sorted((s.find(n), n) for n in low if n in s)
            for (i, a), (j, b) in zip(found, found[1:]):
                if a == b or a in b or b in a:
                    continue
                if not ALIAS.search(sent[i + len(a):j]):
                    return True
    return False


def one_identity(names: list[str]) -> bool:
    """Every name is the same entity in the entity table (spelling, nesting of names, initials)."""
    from .entities import EntityTable
    t = EntityTable()
    for n in names:
        t.add(n, "name", "")
    t.build()
    ents = [t.entity(n) for n in names]
    return all(e is not None for e in ents) and len({e.key for e in ents}) == 1


def classify(names: list[str], texts: list[str | None]) -> str:
    names = [n for n in names if n]
    if len(names) >= 2 and one_identity(names):
        return "alias"
    if named_together(names, texts):
        return "distinct"
    return "disagreement"

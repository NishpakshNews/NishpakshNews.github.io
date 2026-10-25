"""Copy detection between the reports of one story (B28): an article that reproduces another is not another source.

Wire copies and owner groups are already merged by `wire.py`; this finds the rest, a rewritten press note or a re-posted
article, from the TEXT itself: every article is cut into overlapping 5-word shingles, and an article whose shingles are
mostly contained in an EARLIER article's (CONTAINMENT, 0.5) is a copy of it. Containment, not Jaccard, because a copy is
usually shorter than its source. Pure code on the stored text; no model. The copy joins the independence group of the article
it copies, so it can never add an outlet, and it is never original reporting. Both effects can only lower a count.
"""
from __future__ import annotations

import re

SHINGLE = 5
CONTAINMENT = 0.5
MIN_SHINGLES = 20            # a short blurb cannot be judged


def _shingles(text: str) -> set[int]:
    words = re.findall(r"\w+", (text or "").lower())
    return {hash(tuple(words[i:i + SHINGLE])) for i in range(max(0, len(words) - SHINGLE + 1))}


def copies(arts: dict[int, dict]) -> dict[int, int]:
    """{copy article id: id of the earlier article it copies}. `arts`: id -> {text, published_at}."""
    sh = {aid: _shingles(a.get("text")) for aid, a in arts.items()}
    order = sorted(arts, key=lambda i: (arts[i].get("published_at") is None, arts[i].get("published_at"), i))
    out: dict[int, int] = {}
    for n, aid in enumerate(order):
        mine = sh[aid]
        if len(mine) < MIN_SHINGLES:
            continue
        best, best_id = 0.0, None
        for earlier in order[:n]:
            theirs = sh[earlier]
            if len(theirs) < MIN_SHINGLES or earlier in out:
                continue                              # copy the ORIGINAL, not a copy of it
            share = len(mine & theirs) / len(mine)
            if share > best:
                best, best_id = share, earlier
        if best_id is not None and best >= CONTAINMENT:
            out[aid] = best_id
    return out


def merge_groups(groups: dict, copied: dict[int, int]) -> dict:
    """The independence groups with every copy in the group of the article it copies."""
    merged = dict(groups)
    for aid, src in copied.items():
        if src in groups:
            merged[aid] = groups[src]
    return merged

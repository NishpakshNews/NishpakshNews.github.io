"""Hindi loaded words mapped to English concepts, so framing can be compared across languages
("दंगा" and "riot" are the same choice of word). Without it, framing split outlets by language
(real data, Oct 2026). Mappings are cached in `translations` and asked for once per word."""
from __future__ import annotations

import hashlib
import logging
import re

from .router import Router

log = logging.getLogger(__name__)
DEVA = re.compile(r"[ऀ-ॿ]")

def _key(word: str) -> str:
    return hashlib.sha256(("concept|" + word).encode("utf-8")).hexdigest()


def lookup(store, words: set[str]) -> dict[str, str]:
    """Known English concepts for these words (Devanagari only; others map to themselves)."""
    hi = sorted(w for w in words if DEVA.search(w))
    got = store.translation_get([_key(w) for w in hi])
    out = {w: w.lower() for w in words if not DEVA.search(w)}
    for w in hi:
        if _key(w) in got:
            out[w] = got[_key(w)]
    return out


MIN_SIM = 0.62          # a Hindi word is the same wording choice as an English one only when this close in meaning


def map_new(store, router: Router | None, words: set[str], max_calls: int = 3) -> int:
    """Map the Hindi words not yet mapped to the nearest English loaded word, by a multilingual embedding (cross-lingual
    nearest neighbour; `router` and `max_calls` are kept for the callers and unused). The English side is the loaded words
    already in the data and the concepts already mapped. A word with no neighbour close enough stays unmapped (it then
    stands for itself: never a guess). Needs the bi-encoder; the TF-IDF fallback has no cross-lingual space, so nothing is
    mapped. Returns how many were added."""
    from . import embed
    known = lookup(store, words)
    todo = sorted(w for w in words if DEVA.search(w) and w not in known)
    english = sorted({w.lower() for w in words if not DEVA.search(w)} | {v for v in known.values() if not DEVA.search(v)})
    if not todo or not english:
        return 0
    vecs, how = embed.vectors(todo + english)
    if how != "bi-encoder":
        return 0
    hi, en = vecs[:len(todo)], vecs[len(todo):]
    sims = hi @ en.T
    put = {}
    for k, w in enumerate(todo):
        j = int(sims[k].argmax())
        if sims[k, j] >= MIN_SIM:
            put[_key(w)] = english[j]
    if put:
        store.translation_put(put)
    return len(put)

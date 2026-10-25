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
    import datetime as dt
    known = lookup(store, words)
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    fails = _failures(store, [w for w in words if DEVA.search(w) and w not in known])
    # E26: a word that found no neighbour is not tried again at once (each failure doubles the wait); the run takes the
    # words tried least often first, at most MAX_WORDS, so a long tail cannot use up every run
    todo = sorted((w for w in words if DEVA.search(w) and w not in known and fails.get(w, (0, now))[1] <= now),
                  key=lambda w: (fails.get(w, (0, now))[0], w))[:MAX_WORDS]
    pool = {w.lower() for w in words if not DEVA.search(w)} | {v for v in known.values() if not DEVA.search(v)}
    english = _by_stem(pool)
    if not todo or not english:
        return 0
    vecs, how = embed.vectors(todo + english)
    if how != "bi-encoder":
        return 0
    hi, en = vecs[:len(todo)], vecs[len(todo):]
    sims = hi @ en.T
    put, failed = {}, {}
    for k, w in enumerate(todo):
        j = int(sims[k].argmax())
        if sims[k, j] >= MIN_SIM:
            put[_key(w)] = english[j]
        else:
            n = fails.get(w, (0, now))[0] + 1
            failed[_fail_key(w)] = f"{n}|{(now + dt.timedelta(hours=min(24 * 14, 6 * 2 ** n))).isoformat(timespec='minutes')}"
    if put or failed:
        store.translation_put({**put, **failed})
    return len(put)


MAX_WORDS = 300


def _fail_key(word: str) -> str:
    return hashlib.sha256(("conceptfail|" + word).encode("utf-8")).hexdigest()


def _failures(store, words: list[str]) -> dict[str, tuple[int, "object"]]:
    import datetime as dt
    got = store.translation_get([_fail_key(w) for w in words]) if words else {}
    out = {}
    for w in words:
        v = got.get(_fail_key(w))
        if v:
            try:
                n, until = v.split("|", 1)
                out[w] = (int(n), dt.datetime.fromisoformat(until))
            except ValueError:
                continue
    return out


def _by_stem(words: set[str]) -> list[str]:
    """One English word per stem (the shortest), so "riots" and "rioting" do not both stand as separate concepts to map to."""
    from .frames import words as roots
    best: dict[str, str] = {}
    for w in sorted(words):
        r = roots(w)
        k = sorted(r)[0] if r else w
        if k not in best or len(w) < len(best[k]):
            best[k] = w
    return sorted(best.values())

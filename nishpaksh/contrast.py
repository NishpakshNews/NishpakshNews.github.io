"""Words that mark "another event" (S14): learned from the newsroom's own answers, not listed by hand.

When two lines say nearly the same words and the twice-asked question calls them DIFFERENT, the words one has and the other
lacks are what told them apart ("another", "earlier", "second", "again", "also", "last year", ...). `learn` counts, over the kept
answers (`pair_labels`), for every word standing on only one side of a pair: in how many pairs it did, and how many of those
the answer was "different". A word is a contrast cue when it was a difference in at least MIN_PAIRS pairs and at least RATIO of
them were "different". Daily, with the other fitted state (`dupescore.refresh`), kept in `model_state` under "contrast".
`relate.Profile.contrast` asks `has(text)`: the learned words, plus SEED, the closed-class cues (determiners and adverbs of
sequence, not content words) the learning starts from and which no one extends by hand. A line with a cue the other lacks is never
"covered" by code alone: the model is asked.
"""
from __future__ import annotations

import re

NAME = "contrast"
MIN_PAIRS = 8
RATIO = 0.85
MAX_WORDS = 200

SEED = re.compile(r"(?i)\b(another|other|earlier|previous|previously|former|formerly|last year|last month|"
                  r"separate|different|second|again|also|before|after)\b")

_learned: frozenset[str] = frozenset()


def set_learned(words) -> None:
    global _learned
    _learned = frozenset(words or ())


def learned() -> frozenset[str]:
    return _learned


def has(text: str) -> bool:
    t = text or ""
    if SEED.search(t):
        return True
    if not _learned:
        return False
    from .frames import words
    return bool(set(words(t)) & _learned)


def learn(rows: list[dict]) -> list[str]:
    """Contrast words from labelled pairs [{a, b, label}] (label True = same fact)."""
    from .frames import words
    seen: dict[str, list[int]] = {}
    for r in rows:
        wa, wb = set(words(r["a"])), set(words(r["b"]))
        if not wa or not wb or len(wa & wb) / min(len(wa), len(wb)) < 0.5:      # only pairs that are alike otherwise
            continue
        for w in wa ^ wb:
            c = seen.setdefault(w, [0, 0])
            c[0] += 1
            c[1] += 0 if r["label"] else 1
    out = [(c[1], w) for w, c in seen.items() if c[0] >= MIN_PAIRS and c[1] / c[0] >= RATIO and len(w) > 2]
    return [w for _n, w in sorted(out, reverse=True)[:MAX_WORDS]]

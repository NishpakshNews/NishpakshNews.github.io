"""Corpus word weights (B13): which words carry a subject is learned from the texts, not listed by hand.

A word every statement of a story has ("police", "delhi") says little about what two statements share; a word few
have says a lot. Weight = inverse document frequency scaled to 0..1 (sklearn's stop-word list is the only fixed list:
function words, a published standard). Used by plan.py (paragraph subjects), threads.py (thread candidates),
narrative._subject_words (shared subject).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

_WORD = re.compile(r"[a-z0-9]{3,}")
MIN_DOCS = 6        # under this a document set says nothing about commonness: every word weighs 1


def tokens(text: str | None) -> set[str]:
    """Content words of a text: lower case, 3+ letters, not a function word."""
    return {w for w in _WORD.findall((text or "").lower()) if w not in ENGLISH_STOP_WORDS}


class Weights:
    def __init__(self, docs: list[str] | list[set[str]]):
        sets = [d if isinstance(d, set) else tokens(d) for d in docs]
        self.n = len(sets)
        self.df: Counter = Counter()
        for s in sets:
            self.df.update(s)
        self._norm = math.log(1 + self.n) if self.n else 1.0

    def w(self, word: str) -> float:
        """0 for a word in every document, near 1 for a word in one."""
        if self.n < MIN_DOCS:
            return 1.0
        df = self.df.get(word, 0)
        return math.log((1 + self.n) / (1 + df)) / self._norm if df else 1.0

    def shared(self, a: set[str], b: set[str]) -> float:
        return sum(self.w(x) for x in a & b)

    def related(self, a: set[str], b: set[str], need: float = 0.5) -> bool:
        """Do two word sets share enough weight to be one subject?"""
        return self.shared(a, b) >= need


def rank(query: str, docs: list[str], k: int = 5) -> list[tuple[int, float]]:
    """The k documents most like the query, by TF-IDF cosine (candidate retrieval for thread links)."""
    if not docs or not (query or "").strip():
        return []
    from sklearn.feature_extraction.text import TfidfVectorizer
    try:
        m = TfidfVectorizer(stop_words="english", sublinear_tf=True).fit_transform([query] + list(docs))
    except ValueError:                       # nothing but stop words
        return []
    sims = (m[1:] @ m[0].T).toarray().ravel()
    order = sims.argsort()[::-1][:k]
    return [(int(i), float(sims[i])) for i in order if sims[i] > 0]

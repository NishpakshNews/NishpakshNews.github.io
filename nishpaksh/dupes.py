"""Finding the same fact told in other words, and the topics of a story, by code (B6 / B14 / B16 / B21).

Before (owner, Oct 8 2026, story 13970) one Gemini call sorted the statements into topics and another proposed repeated
pairs per topic; a quota or a refusal removed both, and the paragraph plan fell back to shared words (F50). Now both come
from sentence similarity (embed.py: a local multilingual bi-encoder, TF-IDF when it cannot load) and a clustering
library: no quota, the same answer every run.

    topics()   statements -> groups of one subject (agglomerative clustering on cosine distance), at most TOPIC_MAX each
    propose()  pairs similar enough to be worth asking about: (same-fact candidates, (detailed, short) covers candidates)

PROPOSALS ONLY. Every pair still goes through the deciders: relate.py (numbers, names, negation, dates) and then the NLI
model (nli.py, both directions). A wrong proposal costs a computation; it never merges two facts.
"""
from __future__ import annotations

import numpy as np

from . import embed

TOPIC_MAX = 12
TOPIC_LINK = 0.45         # cosine similarity (average linkage) under which two groups are different subjects
COVER_RATIO = 1.25        # a covering line is at least this much longer than the line it covers


def topics(router, texts: dict[int, str], cache: dict | None = None) -> list[list[int]]:
    """The statements grouped by subject, in the order their first member appears; groups cut at TOPIC_MAX."""
    ids = sorted(texts)
    if not ids:
        return []
    if len(ids) == 1:
        return [ids]
    from sklearn.cluster import AgglomerativeClustering
    sim, _ = embed.similarity([texts[i] for i in ids])
    dist = np.clip(1 - sim, 0, 2)
    lab = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                  distance_threshold=1 - TOPIC_LINK).fit_predict(dist)
    groups: dict[int, list[int]] = {}
    for i, l in zip(ids, lab):
        groups.setdefault(int(l), []).append(i)
    ordered = sorted(groups.values(), key=lambda g: g[0])
    return [g[k:k + TOPIC_MAX] for g in ordered for k in range(0, len(g), TOPIC_MAX)]


def propose(router, texts: dict[int, str], cache: dict | None = None) -> tuple[set[tuple[int, int]], list[tuple[int, int]]]:
    """(pairs that may say the same fact, (detailed, short) pairs where the first may say all of the second)."""
    ids = sorted(texts)
    same: set[tuple[int, int]] = set()
    covers: list[tuple[int, int]] = []
    if len(ids) < 2:
        return same, covers
    sim, threshold = embed.similarity([texts[i] for i in ids])
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            if sim[a, b] < threshold:
                continue
            x, y = ids[a], ids[b]
            lx, ly = len(texts[x]), len(texts[y])
            if lx >= COVER_RATIO * ly:
                covers.append((x, y))
            elif ly >= COVER_RATIO * lx:
                covers.append((y, x))
            else:
                same.add((x, y))
    return same, covers

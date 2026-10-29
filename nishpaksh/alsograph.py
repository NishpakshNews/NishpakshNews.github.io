"""What keeps a line in the article: a graph, not a chain of gates (owner, Oct 29 2026; no model, no quota).

The gates of `insert.py` judge each line alone against a threshold. The cause of the losses is that a line's worth depends on
the others: a DETAIL of the story is tied to the written lines by rare names several of them share; a SIBLING (another scheme in
the same cabinet decision, another event on a roundup page) is tied to the story only by generic words and comes with OTHER also
lines that share a name the story does not have. So:
  1. a graph over the written lines and the also lines; an edge's weight is the idf weight of the names / words the two lines share
     (names count double, a name in over a third of the lines is the setting and ties nothing);
  2. PERSONALISED PAGERANK from the headline + lead: the mass an also line receives is how well it is tied to the story through
     the lines already written (the standard way to score closeness to a seed in a graph);
  3. FOREIGN CLUSTERS: also lines that share a rare name the story lacks form a cluster (connected components over such names);
     a cluster of 2+ lines whose shared foreign name outweighs the line's best tie to the story is another event, cut as a block;
     a foreign name that only ONE line has is a new detail, not a cluster.
`scores()` returns, per also line: {"ppr", "foreign": cluster id or None, "tie": best shared story-name weight}.
"""
from __future__ import annotations

import numpy as np

from . import tidy
from .relate import Profile

DAMP = 0.15            # restart probability toward the headline + lead
SETTING = 1 / 3        # a name in more than this share of the story's lines is its setting


def _weights(p: Profile, q: Profile, W, banned: set[str]) -> float:
    s = 0.0
    for n in p.names & q.names:
        if n not in banned:
            s += 2 * W.w(n)
    for r in (p.roots & q.roots) - p.names - q.names:
        s += W.w(r)
    return s


def scores(written: list[str], also: list[str], headline: str, W=None) -> list[dict]:
    wp = [Profile(t) for t in written]
    ap = [Profile(t) for t in also]
    anchor = Profile((headline + " " + " ".join(written[:2])).strip())
    W = W or tidy.weights(wp + ap + [anchor])
    count: dict[str, int] = {}
    for p in wp:
        for n in p.names:
            count[n] = count.get(n, 0) + 1
    setting = {n for n, c in count.items() if c > max(2, int(len(wp) * SETTING))}
    story_names = set().union(*(p.names for p in wp)) if wp else set()

    nodes = [anchor] + wp + ap
    N = len(nodes)
    A = np.zeros((N, N))
    for i in range(N):
        for j in range(i + 1, N):
            w = _weights(nodes[i], nodes[j], W, setting)
            A[i, j] = A[j, i] = w
    deg = A.sum(1)
    P = np.divide(A, deg[:, None], out=np.zeros_like(A), where=deg[:, None] > 0)
    r0 = np.zeros(N)
    r0[0] = 1.0
    r = r0.copy()
    for _ in range(60):
        r = DAMP * r0 + (1 - DAMP) * (P.T @ r)

    # foreign clusters: also lines that share a rare name the story does not have
    k = len(ap)
    parent = list(range(k))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_name: dict[str, list[int]] = {}
    for i, p in enumerate(ap):
        for n in p.names:
            if n not in story_names and n not in setting:
                by_name.setdefault(n, []).append(i)
    foreign_w = [0.0] * k
    for n, idx in by_name.items():
        if len(idx) >= 2:
            for i in idx[1:]:
                parent[find(i)] = find(idx[0])
            for i in idx:
                foreign_w[i] = max(foreign_w[i], W.w(n))
    out = []
    for i, p in enumerate(ap):
        tie = max([W.w(n) for n in p.names & story_names if n not in setting] or [0.0])
        root = find(i)
        size = sum(1 for j in range(k) if find(j) == root)
        foreign = root if size >= 2 and foreign_w[i] > tie else None
        out.append({"ppr": float(r[1 + len(wp) + i]), "foreign": foreign, "tie": tie, "foreign_w": foreign_w[i], "cluster": size})
    return out

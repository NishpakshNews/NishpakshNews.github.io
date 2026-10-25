"""Probabilistic record linkage for statements (B2/B21; Fellegi & Sunter 1969, the Splink way): no labels needed.

Each pair of statements is compared field by field into AGREEMENT LEVELS (words, names, figures, negation, date). For
every field the model holds two probabilities per level: m = how often a true match shows that level, u = how often a
non-match does. EM estimates them from the pairs themselves (unsupervised); a pair's MATCH WEIGHT is the sum of
log2(m/u) over its fields. Weight above `UPPER` = likely the same, below `LOWER` = likely different, the band between is
the middle that only a model should be asked about (Chow's reject option). Here it ORDERS the questions (likeliest first)
and reports the size of the middle band; it never merges and never skips a pair, the same rule as dupescore.py.
Used when dupescore has no fitted model, and by the offline comparison (tools/claim_matching_eval.py).
"""
from __future__ import annotations

import math

LEVELS = {"words": 4, "names": 3, "nums": 4, "neg": 2, "date": 3}
FIELDS = list(LEVELS)
UPPER, LOWER = 6.0, -4.0
MIN_PAIRS = 30


def gamma(pa, pb) -> tuple[int, ...]:
    """Agreement levels, higher = more alike. Profile pairs (relate.Profile)."""
    wa, wb = set(pa.roots), set(pb.roots)
    jac = len(wa & wb) / len(wa | wb) if wa | wb else 0.0
    words = 3 if jac >= 0.8 else 2 if jac >= 0.5 else 1 if jac >= 0.25 else 0
    if not (pa.names or pb.names):
        names = 1
    elif pa.names == pb.names:
        names = 2
    else:
        names = 2 if pa.names <= pb.names or pb.names <= pa.names else 0
    if not (pa.nums or pb.nums):
        nums = 2
    elif pa.nums == pb.nums:
        nums = 3
    elif pa.nums & pb.nums:
        nums = 1
    else:
        nums = 0
    neg = 1 if pa.neg == pb.neg else 0
    da, db = getattr(pa, "date", None), getattr(pb, "date", None)
    date = 1 if (da is None or db is None) else 2 if da == db else 0
    return (words, names, nums, neg, date)


class Model:
    def __init__(self, p: float, m: list[list[float]], u: list[list[float]]):
        self.p, self.m, self.u = p, m, u

    def weight(self, g: tuple[int, ...]) -> float:
        return sum(math.log2(self.m[f][lv] / self.u[f][lv]) for f, lv in enumerate(g))

    def prob(self, g: tuple[int, ...]) -> float:
        w = self.weight(g) + math.log2(self.p / (1 - self.p))
        return 1 / (1 + 2 ** -max(-60.0, min(60.0, w)))


def fit(gammas: list[tuple[int, ...]], iters: int = 40) -> Model | None:
    """EM for p, m, u. Initial belief: matches agree highly (the usual Splink start). None when there are too few pairs."""
    if len(gammas) < MIN_PAIRS:
        return None
    k = [LEVELS[f] for f in FIELDS]

    def init(top: float) -> list[list[float]]:
        out = []
        for n in k:
            w = [top ** i for i in range(n)]
            t = sum(w)
            out.append([x / t for x in w])
        return out

    m, u = init(3.0), init(1 / 3.0)
    p = 0.1
    for _ in range(iters):
        post = []
        for g in gammas:
            lm = p * math.prod(m[f][lv] for f, lv in enumerate(g))
            lu = (1 - p) * math.prod(u[f][lv] for f, lv in enumerate(g))
            post.append(lm / (lm + lu) if lm + lu else 0.0)
        tot = sum(post)
        if tot < 1e-6 or tot > len(gammas) - 1e-6:
            break
        p = min(0.9, max(0.001, tot / len(gammas)))
        for f, n in enumerate(k):
            cm, cu = [1e-3] * n, [1e-3] * n          # a little smoothing, so no level is impossible
            for g, w in zip(gammas, post):
                cm[g[f]] += w
                cu[g[f]] += 1 - w
            sm, su = sum(cm), sum(cu)
            m[f] = [x / sm for x in cm]
            u[f] = [x / su for x in cu]
    # keep the labels meaning "match": a match must agree on words at least as often as a non-match
    if sum(i * m[0][i] for i in range(k[0])) < sum(i * u[0][i] for i in range(k[0])):
        m, u, p = u, m, 1 - p
    return Model(p, m, u)


def fit_story(prof: dict) -> Model | None:
    ids = sorted(prof)
    return fit([gamma(prof[a], prof[b]) for i, a in enumerate(ids) for b in ids[i + 1:]])


def order(pairs: list[tuple[int, int]], prof: dict) -> list[tuple[int, int]]:
    """The same pairs, highest weight first (stable). Unchanged when the story is too small to fit."""
    model = fit_story(prof)
    if model is None or len(pairs) < 2:
        return list(pairs)
    scored = [(model.weight(gamma(prof[a], prof[b])), k, (a, b)) for k, (a, b) in enumerate(pairs)]
    return [p for _w, _k, p in sorted(scored, key=lambda t: (-t[0], t[1]))]


def bands(pairs: list[tuple[int, int]], prof: dict) -> dict:
    """How many of the pairs fall above UPPER, below LOWER and in the middle: the share a model must still be asked."""
    model = fit_story(prof)
    if model is None:
        return {}
    ws = [model.weight(gamma(prof[a], prof[b])) for a, b in pairs]
    return {"upper": sum(w >= UPPER for w in ws), "lower": sum(w <= LOWER for w in ws),
            "middle": sum(LOWER < w < UPPER for w in ws), "pairs": len(ws)}

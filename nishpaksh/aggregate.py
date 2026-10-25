"""Several imperfect judges, one answer (S12): Dawid-Skene aggregation.

A "same fact?" question has several weak judges: the NLI model (both directions read, one vote), the sentence embedding
(only when the bi-encoder is loaded: TF-IDF is no judge across languages), and code's own word comparison (`relate`).
Each can be wrong in its own way. Dawid-Skene (1979) estimates each judge's sensitivity and specificity from the
disagreements among them on the SAME batch (EM, no labels), then weighs every vote by how much that judge is worth.
Fewer than `MIN_ITEMS` pairs cannot teach it anything, so the judges start from a prior accuracy (`PRIOR`) and stay there.
A judge that did not vote (None) is simply absent for that pair.

Use: an extra AND gate (`match.same_facts`): a pair the NLI model calls the same fact stays "same" only when the
aggregate probability is at least `POSTERIOR_MIN`; it can turn a yes into a no, never a no into a yes, so a colour can only
become more cautious. Untuned: PRIOR, POSTERIOR_MIN (read in the single audit).
"""
from __future__ import annotations

PRIOR = 0.8             # a judge's accuracy before the data has said anything
PRIOR_WEIGHT = 4.0      # pseudo-answers behind that prior
POSTERIOR_MIN = 0.9
MIN_ITEMS = 30
ITERATIONS = 25

Vote = int | None


def fit(votes: list[list[Vote]]) -> tuple[list[float], list[tuple[float, float]], float]:
    """(P(true) per item, [(sensitivity, specificity) per judge], prior of true). `votes[item][judge]` in {0, 1, None}."""
    n_items = len(votes)
    n_judges = len(votes[0]) if votes else 0
    sens = [PRIOR] * n_judges
    spec = [PRIOR] * n_judges
    pi = 0.5

    def posterior(row: list[Vote]) -> float:
        lp1, lp0 = pi, 1 - pi
        for j, v in enumerate(row):
            if v is None:
                continue
            lp1 *= sens[j] if v else 1 - sens[j]
            lp0 *= (1 - spec[j]) if v else spec[j]
        tot = lp1 + lp0
        return lp1 / tot if tot > 0 else 0.5

    post = [posterior(r) for r in votes]
    if n_items < MIN_ITEMS:
        return post, list(zip(sens, spec)), pi
    for _ in range(ITERATIONS):
        pi = min(max(sum(post) / n_items, 0.05), 0.95)
        for j in range(n_judges):
            a1 = a0 = b1 = b0 = 0.0          # votes 1 when true / items true / votes 0 when false / items false
            for p, row in zip(post, votes):
                v = row[j]
                if v is None:
                    continue
                a0 += p
                b0 += 1 - p
                a1 += p * v
                b1 += (1 - p) * (1 - v)
            sens[j] = (a1 + PRIOR * PRIOR_WEIGHT) / (a0 + PRIOR_WEIGHT)
            spec[j] = (b1 + PRIOR * PRIOR_WEIGHT) / (b0 + PRIOR_WEIGHT)
            if sens[j] + spec[j] <= 1.0:      # worse than a coin: keep the label from flipping
                sens[j], spec[j] = PRIOR, PRIOR
        post = [posterior(r) for r in votes]
    return post, list(zip(sens, spec)), pi


def same_votes(pairs: list[tuple[str, str]], nli_same: list[bool | None]) -> list[list[Vote]]:
    """Votes per pair: [nli, embedding, code]."""
    from . import embed
    from .relate import relate
    rows: list[list[Vote]] = [[None if s is None else int(bool(s)), None, None] for s in nli_same]
    try:
        texts = sorted({t for p in pairs for t in p})
        if texts:
            v, how = embed.vectors(texts)
            if how == "bi-encoder":
                ix = {t: i for i, t in enumerate(texts)}
                for k, (a, b) in enumerate(pairs):
                    rows[k][1] = int(float(v[ix[a]] @ v[ix[b]]) >= embed.PROPOSE[how])
    except Exception:
        pass
    for k, (a, b) in enumerate(pairs):
        r = relate(a, b)
        rows[k][2] = 1 if r == "same" else None      # "different" is not a vote: a proposal reaches the question BECAUSE code split them
    return rows


def gate(pairs: list[tuple[str, str]], nli_same: list[bool | None]) -> list[bool | None]:
    """nli's answers, with a yes turned into a no where the judges together do not reach POSTERIOR_MIN. A pair with only
    one judge's vote has nobody to disagree with it: the NLI answer stands."""
    if not pairs or not any(nli_same):
        return list(nli_same)
    try:
        votes = same_votes(pairs, nli_same)
        post, _, _ = fit(votes)
    except Exception:
        return list(nli_same)
    return [s if s is None or not s or sum(v is not None for v in row) < 2 else p >= POSTERIOR_MIN
            for s, p, row in zip(nli_same, post, votes)]

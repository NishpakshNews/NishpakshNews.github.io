"""Truth discovery (B25): how much to believe a statement, from WHO supports and denies it, not only how many.

The established algorithm family (TruthFinder / "Sums"): a source is as reliable as the statements it supports are believed,
and a statement is as believed as its supporters are reliable, solved by iterating both. Here, per story:
  * the sources are independence groups (wire copies and owners merged by wire.py, copies merged by independence.py);
  * a source's reliability starts at PRIOR and moves to the mean belief of the statements it supports (shrunk to the prior by
    a pseudo-count, so a source with one statement stays near the prior);
  * belief(statement) = 1 - prod(1 - reliability) over its supporters, multiplied by (1 - the same quantity over its deniers):
    supporters raise it, independent deniers cut it, a denier is counted like a supporter, no more.
The belief never makes a statement green. It is an extra gate in verify.base_verdicts: a statement the rule would establish is
kept at "unverified" unless its belief reaches BELIEF_MIN. So it can only make a page more cautious.
"""
from __future__ import annotations

PRIOR = 0.7
PSEUDO = 2.0
ITERATIONS = 20
BELIEF_MIN = 0.85


def beliefs(support: dict[int, set], deny: dict[int, set]) -> dict[int, float]:
    """{statement: belief 0..1} from {statement: set of supporting groups}, {statement: set of denying groups}."""
    cids = sorted(set(support) | set(deny))
    groups = {g for s in list(support.values()) + list(deny.values()) for g in s}
    rel = {g: PRIOR for g in groups}
    belief = {c: 0.0 for c in cids}
    for _ in range(ITERATIONS):
        for c in cids:
            p_wrong_for = 1.0
            for g in support.get(c, ()):
                p_wrong_for *= 1 - rel[g]
            p_wrong_against = 1.0
            for g in deny.get(c, ()):
                p_wrong_against *= 1 - rel[g]
            belief[c] = (1 - p_wrong_for) * p_wrong_against
        new = {}
        for g in groups:
            backed = [belief[c] for c in cids if g in support.get(c, ())]
            denied = [1 - belief[c] for c in cids if g in deny.get(c, ())]
            seen = backed + denied
            new[g] = (sum(seen) + PRIOR * PSEUDO) / (len(seen) + PSEUDO)
        rel = new
    return belief

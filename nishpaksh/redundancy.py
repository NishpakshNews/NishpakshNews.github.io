"""Repeats as clustering with constraints (B16 steps 4-6): entity resolution applied to statements.

STRICT point (corroboration; colours change): two statements are one only when code says "same" or the model said "same"
both times; this is `consolidate`'s merge. LOOSE point (redundancy; colours never change): a statement whose fact another
statement already tells is not written again, one model "yes" plus the arithmetic check (`consolidate.tells`) is enough.
Both points are made from the same pairs; this module holds the parts they share:

    constrained     union-find over the "same" pairs in order of confidence, refusing a union that would put a
                    cannot-link pair into one cluster (a dispute, a figure that was updated, a pair the model or code
                    called different): A = B, B = C, A != C is settled by the stronger pairs, not by the order of the loop
    survivor        the statement that stays (best supported, then the longer) and the VARIANTS the others carry in each
                    slot (a different rounding, another spelling, another time), kept, not thrown away
    number_pairs    one card per (subject, measure): lines with the same figures and most of the same words, offered to the
                    twice-asked question (proposals only; they decide nothing)
"""
from __future__ import annotations


class Clusters:
    def __init__(self, cannot: set[tuple[int, int]] | None = None):
        self.parent: dict[int, int] = {}
        self.members: dict[int, set[int]] = {}
        self.cannot = {tuple(sorted(p)) for p in (cannot or set())}
        self.refused = 0

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        self.members.setdefault(x, {x})
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def blocked(self, ra: int, rb: int) -> bool:
        small, big = sorted((self.members[ra], self.members[rb]), key=len)
        return any(tuple(sorted((a, b))) in self.cannot for a in small for b in big)

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if self.blocked(ra, rb):
            self.refused += 1
            return False
        self.parent[rb] = ra
        self.members[ra] |= self.members.pop(rb)
        return True

    def groups(self) -> list[list[int]]:
        roots: dict[int, list[int]] = {}
        for x in list(self.parent):
            roots.setdefault(self.find(x), []).append(x)
        return [sorted(g) for g in roots.values() if len(g) > 1]


def constrained(pairs: list[tuple[int, int]], cannot: set[tuple[int, int]] | None = None) -> tuple[list[list[int]], int]:
    """(clusters of size 2+, unions refused). `pairs` come strongest first."""
    c = Clusters(cannot)
    for a, b in pairs:
        c.union(a, b)
    return c.groups(), c.refused


def survivor(cluster: list[int], support: dict[int, int], texts: dict[int, str]) -> tuple[int, dict[int, list[str]]]:
    """(the statement that stays, {other id: its text when it differs in a slot}). A slot is the figures or the
    capitalised words; wording alone is no variant."""
    from .relate import Profile
    lead = max(cluster, key=lambda x: (support.get(x, 0), len(texts[x]), -x))
    pl = Profile(texts[lead])
    variants: dict[int, list[str]] = {}
    for x in cluster:
        if x == lead:
            continue
        px = Profile(texts[x])
        if px.nums != pl.nums or px.names != pl.names or _label(texts[x]) != _label(texts[lead]):
            variants[x] = [texts[x]]
    return lead, variants


def _label(text: str) -> tuple:
    """S10: attribution is a LABEL on the proposition, not noise to strip: who says it and how hedged. Two lines that tell the
    same thing, one flatly and one as someone's claim, are one fact with two labels; the difference is stored as a variant."""
    try:
        from . import attribution, factuality
        sp = attribution.read(text)
        who = (sp.speaker or "").lower() if sp else ""
        return (who, factuality.read(text)["certainty"])
    except Exception:  # noqa: BLE001
        return ("", "unknown")


def number_pairs(profiles: dict, min_overlap: float = 0.5) -> list[tuple[int, int]]:
    """Pairs of lines that give the same figures about nearly the same words and agree on negation: one number card each.
    Proposals for the twice-asked question."""
    ids = sorted(i for i, p in profiles.items() if p.nums)
    out = []
    for k, a in enumerate(ids):
        pa = profiles[a]
        for b in ids[k + 1:]:
            pb = profiles[b]
            if pa.nums != pb.nums or pa.neg != pb.neg:
                continue
            wa, wb = set(pa.roots), set(pb.roots)
            if wa and wb and len(wa & wb) / min(len(wa), len(wb)) >= min_overlap:
                out.append((a, b))
    return out

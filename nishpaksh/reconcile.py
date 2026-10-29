"""Reconciling the differences between two lines about one thing (B9 step 2b; owner, Oct 29 2026).

A gate that says "a figure / date / name / negation differs: never fold" is right about the dangerous cases and wrong about
the many harmless ones: "7,395.55 crore" and "7,395 crore", "December 2014" and "2014", "Pradhan Mantri Viksit Gram Swaraj
Yojana" and "PM Viksit Gram Swaraj Yojana", "rather than an amendment" and "not an amendment". This module replaces the
yes/no gates with ONE typed reading of how two lines differ, by algorithm and no word list of cases:

  figures   every figure becomes a QUANTITY: an interval on the number line. "50" is exact to its own precision; "about 50"
            is wider; "at least 50" / "over 50" runs up; "up to 50" runs down; "125-135" is a range. Two quantities are
            `equal` (the same interval), `within` (one lies inside the other: a point in a range, a rounded figure beside the
            precise one), `near` (the intervals do not touch but the gap is under NEAR of the size: two readings of one
            figure; never for small whole counts, where 19 and 20 are different counts), or `disjoint`. Figures are paired
            across the lines by compatibility first, then by the word that follows them (the SLOT: "kmph", "flights"); a
            disjoint pair in one slot is a conflict; a figure with no partner is detail on one side only. A smaller count of
            the same thing in a narrower place ("15 flights at Vijayawada" / "at least 21 at Vijayawada and Visakhapatnam")
            is a PART of the larger, not a conflict.
  dates     every date is an interval too (a year contains its months, a month its days; `when.date_values`). Dates pair by
            compatibility; two unpaired dates of the same size are a conflict; a date list beside one of its members is
            fine. A weekday that is not the day of its date is reported (`tidy.weekday_errors`), as evidence, not as a ruling.
  clocks    two clock times either side of the same slot but not equal: conflict.
  names     two names are the same when one is the other's prefix, its acronym (SCO = Shanghai Cooperation Organisation),
            a part of it, or a near spelling. What stays on both sides after that is a real difference of names.
  negation  a negation is read with its SCOPE: the few words it governs. Two lines agree when they negate the same thing
            ("not an amendment, but a separate document" / "a separate document rather than an amendment"). A negation on
            something the other line never mentions is an extra detail. A negation of what the other line plainly asserts is
            a conflict. A denial verb answers an allegation: it is a RESPONSE, never a conflict with the allegation.

Result: `difference(...)` returns the facets and a `status`: `identical`, `reconcilable` (figures are readings of one value;
carries notes the writer may put in brackets), `differs` (each line adds something: a merge candidate), `conflict` (one
question answered two ways, with the kind) or `part`. Nothing here changes a text or a colour. `tidy` decides.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import figures
from .frames import _stem, words as _words

NEAR = 0.03        # two figures this close (and not small whole counts) are two readings of one figure
APPROX = 0.05      # "about 50" stands for 47.5 to 52.5
SMALL_COUNT = 1000 # a whole number below this is a count: 19 and 20 are two counts, not one rounded figure
SCOPE_MAX = 8      # a negation governs at most this many words
NAME_FUZZ = 0.88   # spelling similarity from which two names are one

_LOWER = re.compile(r"(?i)(?:at least|no fewer than|not less than|more than|over|above|exceed(?:s|ing)?|in excess of|upwards? of|minimum(?: of)?)\s*(?:rs\.?\s*|₹\s*|\$\s*)?$")
_UPPER = re.compile(r"(?i)(?:up to|upto|at most|no more than|not more than|under|below|less than|maximum(?: of)?|capped at|nearly|almost)\s*(?:rs\.?\s*|₹\s*|\$\s*)?$")
_APPROX = re.compile(r"(?i)(?:about|around|approximately|approx\.?|roughly|nearly|almost|some|estimated at|~)\s*(?:rs\.?\s*|₹\s*|\$\s*)?$")
_RANGE_JOIN = re.compile(r"^\s*(?:to|-|–|—|and)\s*(?:rs\.?\s*|₹\s*|\$\s*)?$", re.I)
_SLOT = re.compile(r"^\W*([A-Za-z]+)")
_SLOT_SKIP = {"per", "percent", "cent", "crore", "lakh", "million", "billion", "thousand", "of", "the", "a", "an", "and", "to"}
_PCT = re.compile(r"^\s*(?:%|per\s*cent|percent)", re.I)

_CUES = re.compile(r"(?i)\b(not|no|never|nobody|none|neither|nor|without|rather than|instead of|n't)\b|n't\b")
_DENIAL = re.compile(r"(?i)\b(denied|denies|deny|refused|refuses|rejected|rejects|dismissed|dismisses)\b")
_SCOPE_END = re.compile(r"(?i)[,;:.]|\b(?:but|and|while|whereas|although|though|if|when|unless|where|because|since|said|says|"
                        r"which|that is|however|only)\b")


# --- quantities ------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Quantity:
    lo: float
    hi: float
    text: str            # as written (a range: both ends)
    value: float         # the point value (a range: its low end)
    slot: str            # the word the figure counts or measures ("kmph", "flights", "%"); "" when none
    precision: float     # width of the written precision (smaller = more precise)
    whole: bool          # a small whole count
    bound: str = ""      # "lower" | "upper" | "approx" | "range" | ""
    pos: int = 0


def _span_taken(text: str) -> list[tuple[int, int]]:
    """Places that are times, not figures: dates, weekdays, clock times (their numerals belong to `when`)."""
    from .when import find
    return [(m.start, m.end) for m in find(text)]


def quantities(text: str) -> list[Quantity]:
    t = (text or "")
    taken = _span_taken(t.translate(figures.DIGIT_MAP))
    fs = [f for f in figures.find(t) if f.kind in ("digits", "words") and not any(s <= f.start < e for s, e in taken)]
    out: list[Quantity] = []
    i = 0
    while i < len(fs):
        f = fs[i]
        u = figures.unit(f)
        lo, hi, bound, shown = f.value - u / 2, f.value + u / 2, "", f.text
        if f.kind != "digits":
            lo, hi = f.value, f.value
        before = t[max(0, f.start - 28):f.start]
        # a range: "125 to 135", "20-22"
        if i + 1 < len(fs) and _RANGE_JOIN.match(t[f.end:fs[i + 1].start]) and fs[i + 1].value >= f.value:
            g = fs[i + 1]
            ug = figures.unit(g)
            lo, hi, bound, shown = f.value - u / 2, g.value + ug / 2, "range", t[f.start:g.end]
            end = g.end
            i += 1
        else:
            end = f.end
            if _LOWER.search(before):
                hi, bound = float("inf"), "lower"
            elif _UPPER.search(before):
                lo, bound = 0.0, "upper"
            if _APPROX.search(before):
                lo, hi, bound = lo * (1 - APPROX), hi * (1 + APPROX), bound or "approx"
        after = t[end:end + 24]
        if _PCT.match(after):
            slot = frozenset({"%"})
        else:
            toks = [w.lower() for w in re.findall(r"[A-Za-z]+", after)][:3]
            slot = frozenset(_stem(w) for w in toks if w not in _SLOT_SKIP)
        mant_whole = f.kind == "digits" and "." not in f.text and f.value == int(f.value) and abs(f.value) < SMALL_COUNT
        out.append(Quantity(lo, hi, shown, f.value, slot, u, mant_whole or f.kind == "words" and abs(f.value) < SMALL_COUNT,
                            bound, f.start))
        i += 1
    return out


def _touch(a: Quantity, b: Quantity) -> bool:
    if a.lo == a.hi == b.lo == b.hi:
        return True
    return a.lo < b.hi and b.lo < a.hi or (a.lo <= b.lo <= a.hi and a.lo <= b.hi <= a.hi) or (b.lo <= a.lo <= b.hi)


def quantity_relation(a: Quantity, b: Quantity) -> str:
    """equal | within (a inside b) | covers (b inside a) | near | disjoint."""
    if a.bound == b.bound and a.bound in ("lower", "upper"):
        # "up to 150" and "up to 140" are two claims about the top: compared as the values they name
        a = Quantity(a.value - a.precision / 2, a.value + a.precision / 2, a.text, a.value, a.slot, a.precision, a.whole, "", a.pos)
        b = Quantity(b.value - b.precision / 2, b.value + b.precision / 2, b.text, b.value, b.slot, b.precision, b.whole, "", b.pos)
    if abs(a.value - b.value) <= 1e-9 * max(abs(a.value), abs(b.value), 1.0) and a.bound == b.bound:
        return "equal"
    if a.lo >= b.lo - 1e-9 and a.hi <= b.hi + 1e-9 and (b.bound or b.precision >= a.precision):
        return "within"
    if b.lo >= a.lo - 1e-9 and b.hi <= a.hi + 1e-9 and (a.bound or a.precision >= b.precision):
        return "covers"
    if _touch(a, b) and not (a.bound in ("lower", "upper") and b.bound in ("lower", "upper") and a.bound != b.bound and False):
        # the intervals overlap without one holding the other: the figures can both be true readings of one value
        return "within" if (a.precision <= b.precision) else "covers"
    gap = max(a.lo - b.hi, b.lo - a.hi)
    big = max(abs(a.value), abs(b.value), 1e-9)
    if gap >= 0 and gap / big <= NEAR and not (a.whole and b.whole):
        return "near"
    return "disjoint"


@dataclass
class FigurePair:
    relation: str            # equal | within | covers | near | disjoint | part
    a: Quantity
    b: Quantity


_RANK = {"equal": 0, "within": 1, "covers": 1, "near": 2}


def _slot_ok(a: Quantity, b: Quantity, single: bool) -> bool:
    """Do the two figures count or measure the same thing? Two different words after them are two different questions
    ("three years" / "five states"); a missing word is no evidence either way, so a lone figure on each side pairs."""
    if a.slot and b.slot:
        return bool(a.slot & b.slot)
    return single or (not a.slot and not b.slot)


def pair_figures(qa: list[Quantity], qb: list[Quantity], names_a: frozenset = frozenset(),
                 names_b: frozenset = frozenset()) -> tuple[list[FigurePair], list[Quantity], list[Quantity]]:
    """Pairs of compatible figures first (best relation first, one to one); then the leftover pairs that count the same thing
    (same slot) as `disjoint` or `part`. Returns (pairs, only_a, only_b)."""
    cand = []
    for i, a in enumerate(qa):
        for j, b in enumerate(qb):
            rel = quantity_relation(a, b)
            if rel in _RANK and (rel == "equal" or _slot_ok(a, b, False) or not a.slot or not b.slot):
                cand.append((_RANK[rel], 0 if (a.slot and a.slot & b.slot) else 1, i, j, rel))
    cand.sort()
    pairs, used_a, used_b = [], set(), set()
    for _, _, i, j, rel in cand:
        if i in used_a or j in used_b:
            continue
        pairs.append(FigurePair(rel, qa[i], qb[j]))
        used_a.add(i)
        used_b.add(j)
    left_a = [(i, q) for i, q in enumerate(qa) if i not in used_a]
    left_b = [(j, q) for j, q in enumerate(qb) if j not in used_b]
    for mine, theirs, used_m, used_t in ((left_a, qb, used_a, used_b), (left_b, qa, used_b, used_a)):
        # one figure of the other line equal to the sum of two or three of these: a total, not a disagreement
        for k in (2, 3):
            if len(mine) < k:
                continue
            from itertools import combinations
            for combo in combinations(mine, k):
                total = sum(q.value for _, q in combo)
                for t_idx, t in enumerate(theirs):
                    if t_idx in used_t:
                        continue
                    if total and abs(total - t.value) <= 0.02 * max(total, t.value):
                        pairs.append(FigurePair("sum", combo[0][1], t) if mine is left_a else FigurePair("sum", t, combo[0][1]))
                        used_t.add(t_idx)
                        for ix, _ in combo:
                            used_m.add(ix)
                        break
    left_a = [(i, q) for i, q in left_a if i not in used_a]
    left_b = [(j, q) for j, q in left_b if j not in used_b]
    single = len(qa) == 1 and len(qb) == 1
    for i, a in list(left_a):
        for j, b in list(left_b):
            if (i in used_a) or (j in used_b) or not _slot_ok(a, b, single):
                continue
            rel = quantity_relation(a, b)
            if rel in _RANK:
                pairs.append(FigurePair(rel, a, b))
                used_a.add(i)
                used_b.add(j)
                continue
            rel = "disjoint"
            small, large = (a, b) if a.value <= b.value else (b, a)
            narrower = (names_a < names_b) if a is small else (names_b < names_a)
            # a smaller count of the same thing in a narrower place is a part of the larger count
            if narrower and (large.bound == "lower" or small.value < large.value) and small.slot & large.slot:
                rel = "part"
            pairs.append(FigurePair(rel, a, b))
            used_a.add(i)
            used_b.add(j)
    return (pairs, [q for i, q in enumerate(qa) if i not in used_a], [q for j, q in enumerate(qb) if j not in used_b])


# --- dates -----------------------------------------------------------------------------------------------------------
def _dates(text: str) -> list[tuple]:
    from .when import date_values
    try:
        return [d for d in (date_values(text) or []) if d]
    except Exception:  # noqa: BLE001
        return []


def _date_agree(x: tuple, y: tuple) -> bool:
    return all(p is None or q is None or p == q for p, q in zip(x, y))


def _size(d: tuple) -> int:
    return sum(1 for p in d if p is not None)


def compare_dates(da: list[tuple], db: list[tuple]) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """(agreeing pairs, conflicting pairs, ...). A date pairs with any compatible date of the other line; two leftover dates
    of the same size (both days, both months) are a conflict; a leftover with no like-sized partner is detail on one side."""
    left_b = list(db)
    agree, conflict = [], []
    rest_a = []
    for x in da:
        hit = next((y for y in left_b if _date_agree(x, y)), None)
        if hit is not None:
            agree.append((x, hit))
            left_b.remove(hit)
        else:
            rest_a.append(x)
    for x in rest_a:
        mate = next((y for y in left_b if _size(y) == _size(x)), None)
        if mate is not None:
            conflict.append((x, mate))
            left_b.remove(mate)
    return agree, conflict, left_b


def _weekday_wrong(text: str) -> bool:
    from .tidy import weekday_errors
    return bool(weekday_errors(text))


# --- names -----------------------------------------------------------------------------------------------------------
def _initials(words: list[str]) -> str:
    return "".join(w[0] for w in words if w)


def names_alias(x: str, y: str) -> bool:
    """x and y (stems, lower case) are one name written two ways: equal, one the prefix / end / part of the other, or a
    near spelling."""
    if x == y:
        return True
    lo, hi = sorted((x, y), key=len)
    if len(lo) >= 4 and (hi.startswith(lo) or hi.endswith(lo) or lo in hi):
        return True
    try:
        from rapidfuzz import fuzz
        return len(lo) >= 5 and fuzz.ratio(x, y) / 100 >= NAME_FUZZ
    except Exception:  # noqa: BLE001
        import difflib
        return len(lo) >= 5 and difflib.SequenceMatcher(None, x, y).ratio() >= NAME_FUZZ


def compare_names(na: frozenset, nb: frozenset) -> tuple[set, set]:
    """(names only line a has, names only line b has) once aliases and acronyms are matched."""
    only_a = {x for x in na if not any(names_alias(x, y) for y in nb)}
    only_b = {y for y in nb if not any(names_alias(x, y) for x in na)}
    for short, other in ((only_a, only_b), (only_b, only_a)):
        for ac in sorted(short, key=len):
            if 2 <= len(ac) <= 6 and len(other) >= len(ac):
                letters = sorted(ac)
                words = [w for w in other]
                # a set of the other side's words whose first letters make the acronym (any order)
                found = _acronym_hit(letters, words)
                if found:
                    short.discard(ac)
                    other -= found
    return only_a, only_b


def _acronym_hit(letters: list[str], words: list[str]) -> set:
    need = list(letters)
    hit = set()
    for w in sorted(words):
        if w[0] in need:
            need.remove(w[0])
            hit.add(w)
    return hit if not need else set()


# --- negation --------------------------------------------------------------------------------------------------------
def negated_scopes(text: str) -> tuple[list[frozenset], list[frozenset]]:
    """(scopes of plain negations, scopes of denial verbs): the root words each governs."""
    t = text or ""
    plain, denial = [], []
    for rx, bucket in ((_CUES, plain), (_DENIAL, denial)):
        for m in rx.finditer(t):
            rest = t[m.end():]
            end = _SCOPE_END.search(rest)
            frag = rest[:end.start()] if end else rest
            frag = " ".join(frag.split()[:SCOPE_MAX])
            roots = frozenset(_words(frag))
            if m.group(0).lower() in ("rather than", "instead of"):
                bucket.append(roots)
            elif roots:
                bucket.append(roots)
    return plain, denial


def _cov(small: frozenset, big: frozenset) -> float:
    return len(small & big) / len(small) if small else 0.0


def compare_negation(ta: str, tb: str, ra: frozenset, rb: frozenset) -> str:
    """same | extra | response | conflict, from the negations' scopes and what the other line plainly says."""
    pa, da = negated_scopes(ta)
    pb, db = negated_scopes(tb)
    if not (pa or pb or da or db):
        return "same"
    # both negate the same things: agreement
    if pa and pb and all(any(_cov(x, y) >= 0.5 or _cov(y, x) >= 0.5 for y in pb) for x in pa):
        return "same"
    status = "same"
    for scopes, other_roots, other_scopes in ((pa, rb, pb), (pb, ra, pa)):
        for s in scopes:
            if not s:
                continue
            asserted = _cov(s, other_roots)
            if asserted >= 0.7 and not any(_cov(s, o) >= 0.5 for o in other_scopes):
                return "conflict"
            status = "extra"
    if da or db:
        status = "response" if status == "same" else status
    return status


# --- the difference ----------------------------------------------------------------------------------------------------
@dataclass
class Difference:
    status: str = "identical"                       # identical | reconcilable | differs | conflict | part
    conflicts: list = field(default_factory=list)    # [(facet, detail)]
    notes: list = field(default_factory=list)       # [(facet, kept, other)]: a second reading of a value the line keeps
    soft: list = field(default_factory=list)        # [(facet, detail)]: what keeps it from being a plain repeat
    extra_a: list = field(default_factory=list)     # [(facet, detail)]: what line a says and line b does not
    extra_b: list = field(default_factory=list)
    pairs: list = field(default_factory=list)       # figure pairs

    @property
    def kind(self) -> str:
        return self.conflicts[0][0] if self.conflicts else ""

    def adds_nothing(self, which: str) -> bool:
        """Line `which` ('a' or 'b') says nothing the other does not, as far as these facets can read."""
        return not self.conflicts and not (self.extra_a if which == "a" else self.extra_b) and not self.soft


def difference(ta: str, tb: str, pa, pb) -> Difference:
    from .relate import core_names, FILLER
    d = Difference()
    # figures
    qa, qb = quantities(ta), quantities(tb)
    d.pairs, only_a, only_b = pair_figures(qa, qb, core_names(pa), core_names(pb))
    for p in d.pairs:
        if p.relation == "disjoint":
            d.conflicts.append(("figure", f"{p.a.text} / {p.b.text}"))
        elif p.relation == "part":
            small, large = sorted((p.a, p.b), key=lambda q: q.value)
            d.soft.append(("figure", f"{small.text} is a part of {large.text}"))
        elif p.relation == "sum":
            d.soft.append(("figure", f"{p.b.text if p.a.value < p.b.value else p.a.text} is a total of figures in the other line"))
        elif p.relation == "near":
            d.notes.append(("figure", p.a.text, p.b.text))
        elif p.relation in ("within", "covers") and not (p.a.bound or p.b.bound) and p.a.precision != p.b.precision \
                and abs(p.a.value - p.b.value) > 1e-9 * max(abs(p.a.value), 1.0):
            d.notes.append(("figure", p.a.text, p.b.text))       # a rounded figure beside the precise one
    d.extra_a += [("figure", q.text) for q in only_a]
    d.extra_b += [("figure", q.text) for q in only_b]
    # dates
    agree, clash, rest_b = compare_dates(_dates(ta), _dates(tb))
    for x, y in clash:
        bad = [side for side, t in (("a", ta), ("b", tb)) if _weekday_wrong(t)]
        d.conflicts.append(("date", f"{x} / {y}" + (f" (the weekday written in line {' and '.join(bad)} is not the day of its date)" if bad else "")))
    matched_a = {x for x, _ in agree} | {x for x, _ in clash}
    d.extra_a += [("date", str(x)) for x in _dates(ta) if x not in matched_a]
    d.extra_b += [("date", str(y)) for y in rest_b]
    # clock times
    if pa.clocks and pb.clocks and not pa.clocks & pb.clocks:
        d.conflicts.append(("clock", f"{sorted(pa.clocks)} / {sorted(pb.clocks)}"))
    elif pa.clocks and not pb.clocks:
        d.extra_a.append(("clock", str(sorted(pa.clocks))))
    elif pb.clocks and not pa.clocks:
        d.extra_b.append(("clock", str(sorted(pb.clocks))))
    # names
    oa, ob = compare_names(core_names(pa), core_names(pb))
    oa, ob = {x for x in oa if x not in FILLER}, {y for y in ob if y not in FILLER}
    if oa and ob:
        d.soft.append(("names", f"{sorted(oa)[:3]} / {sorted(ob)[:3]}"))
    d.extra_a += [("name", x) for x in sorted(oa)]
    d.extra_b += [("name", y) for y in sorted(ob)]
    # negation
    neg = compare_negation(ta, tb, pa.roots, pb.roots)
    if neg == "conflict":
        d.conflicts.append(("negation", "one line negates what the other asserts"))
    elif neg in ("extra", "response"):
        d.soft.append(("negation", neg))
    if d.conflicts:
        d.status = "conflict"
    elif any(p.relation == "part" for p in d.pairs):
        d.status = "part"
    elif d.soft or d.extra_a or d.extra_b:
        d.status = "differs"
    elif d.notes:
        d.status = "reconcilable"
    return d


# --- disputes: what exactly is disputed ------------------------------------------------------------------------------
KIND_OF = {"figure": "number", "date": "date", "clock": "date", "negation": "negation"}      # `disputes.candidate`'s kinds
QUESTION_COS = 0.55


def describe(ta: str, tb: str, d: Difference | None = None) -> dict:
    """What a dispute between two lines is about, in data the writer and the site can show: the facet (number / date /
    negation), the two values as written, and the question they answer (the words both lines share)."""
    from .relate import Profile
    pa, pb = Profile(ta), Profile(tb)
    d = d or difference(ta, tb, pa, pb)
    facet, detail = (d.conflicts[0] if d.conflicts else ("", ""))
    values = [v.strip() for v in re.split(r"\s+/\s+", re.sub(r"\s*\(the weekday.*$", "", detail), maxsplit=1)] if detail else []
    shared = pa.roots & pb.roots
    question = " ".join(w for w in re.findall(r"[A-Za-z][\w'’-]*", ta) if _stem(w.lower()) in shared)
    out = {"facet": facet, "kind": KIND_OF.get(facet, facet), "values": values, "question": question}
    if "weekday" in detail:
        out["note"] = "a weekday written beside one of the dates is not the day of that date"
    return out


def conflict_candidates(texts: dict[int, str], min_cos: float = QUESTION_COS) -> dict[tuple[int, int], dict]:
    """Pairs of statements of one story that answer one question two ways, by the typed reading above: {(a, b): descriptor}.
    A pair whose names differ on both sides is another subject, not a dispute. Proposals only: the dispute gate and the
    model asked 'can both be true?' decide."""
    from . import tidy
    from .relate import Profile
    ids = sorted(texts)
    prof = {i: Profile(texts[i]) for i in ids}
    W = tidy.weights(list(prof.values()))
    out = {}
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            cos = tidy.measures(W, tidy.bag(prof[a]), tidy.bag(prof[b]))[0]
            if cos < min_cos:
                continue
            d = difference(texts[a], texts[b], prof[a], prof[b])
            if d.conflicts and not any(f == "names" for f, _ in d.soft) and tidy.ordinals(texts[a]) == tidy.ordinals(texts[b]):
                out[(a, b)] = describe(texts[a], texts[b], d)
    return out

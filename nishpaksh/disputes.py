"""Two statements that cannot both be true: one place decides it (owner, Oct 7 2026).

Replaces the disputes made in nine places (frames adding a contradiction on arrival with no check, the
frames deciding pairs during review, a one-shot "contradict" question, the consolidation model's own list
filtered by real_difference / typed_difference, ...). Two of those paths had no check at all: "17 of the
19 crew are Indian" and "11 of the 12 injured crew are Indian" were shown as sources disagreeing.

A dispute is the SAME QUESTION with a DIFFERENT ANSWER. Judges, in this order:

  1. code finds candidates: take the answer out of both lines (numbers, dates, "not"); what remains
     must be nearly the same words (with the synonym list, relate.SYNONYM) and the same names. Code
     clears the known non-disputes itself: rounding, bounds ("at least 40" / "50"), counts of different
     groups ("17 of 19" / "11 of 12"). Proposals from the consolidation model and the frames, and
     disputes marked earlier, are candidates only through this same gate.
  2. figures over time: when every report giving one figure was published clearly after every report
     giving the other, it is an UPDATE, not a dispute ("the toll rose to 50; earlier reports put it at
     40"): each line keeps its own colour
  2a. a figure that MOVED A LITTLE ("series": 82.10 / 82.35 written at two precisions-apart, 40 / 42; `relate.numbers_near`
     says within 5% where `numbers_close` says they are not one rounded figure): an update only when something orders
     the two (the reports' publish times, or one clock time in each line); otherwise nothing, as before, never asked
     of the model and never a dispute (two outlets quoting a moving price minutes apart are not in disagreement)
  2b. a STATE that changed ("an orange alert" on Sunday, "a red alert" today): the same question with another answer in
     words, no figure or date involved. Code finds the candidate (`_state`); only when the model, asked twice, says both
     cannot be true is it anything: an update when the reports are clearly ordered in time, else a dispute. Never doubtful.
  3. the model answers "can both be true?" twice, A/B swapped: two "cannot" make a dispute (amber, both
     versions and whose), however many outlets are on each side and whether a side is an official or
     an outlet; any "unsure" or the two answers disagreeing: doubtful (never amber, never green)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from .frames import LOWER, UPPER, date_of
from . import embed, figures
from .relate import NEGATION, Profile, numbers_close, numbers_near

MONTH_DAY = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b|"
                       r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
OF_TOTAL = re.compile(r"(?i)\b(\d+)\s+(?:out\s+)?of\s+(?:the\s+)?(?:total\s+|all\s+)?(\d+)\b")
QUESTION_SIM = {"bi-encoder": 0.72, "tfidf": 0.5}     # cosine of the two claims: the same question (embed.py)
UPDATE_GAP = dt.timedelta(hours=1)
# reconcile.py reads figures / dates as intervals, names by alias and a negation by what it governs. Its conflicts are
# extra CANDIDATES here (the model, asked "can both be true?" twice, still decides). Counted always, used only when switched
# on, as the build charter asks: a system is adopted when it beats the one it replaces (read `STATS` in the audit).
RECONCILE_PROPOSALS = False
STATS = {"reconcile_pairs": 0, "reconcile_new": 0, "staged_different": 0, "staged_unresolved": 0}
STAGED_ASK = None      # the one-word model question of `conflict_judge` (router call); None = the staged check is not used
STATE_COMMON = 3       # content words two lines share when they ask one question about a state ("orange alert for Odisha")
STATE_MAX = 2          # words that differ on either side: the answer ("orange" / "red")


def _question(p: Profile, text: str) -> tuple[frozenset, frozenset]:
    """The words and names of a line with its answer taken out (numbers, dates, negation)."""
    from .frames import _stem
    drop = {_stem(w.lower()) for w in re.findall(r"[A-Za-z]+", " ".join(m.group(0) for m in MONTH_DAY.finditer(text)))}
    drop |= {_stem(w.lower()) for w in NEGATION.findall(text) if isinstance(w, str)}
    drop |= {_stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w in figures.NUMBER_WORDS}     # "forty"
    return p.roots - drop - p.names, p.names - drop


SPEAKER = re.compile(r"(?i)^.{0,80}?\b(?:said|says|stated|states|claimed|claims|alleged|alleges|told reporters|"
                     r"reported|announced|confirmed)\b(?:\s+that)?,?\s+")

def _without_times(text: str) -> str:
    """The text with every time expression taken out (today, Sunday, 5 pm, 12 October): a state said on another day is the same
    question (when.py finds them in both languages; no list of words here)."""
    from . import when
    t = text
    for m in sorted(when.find(t), key=lambda m: -m.start):
        t = t[:m.start] + " " + t[m.end:]
    return t


def _state(a: str, b: str) -> bool:
    """Two lines that ask one question about a STATE and answer it with different words: "an orange alert is in force for the
    coast" / "a red alert is in force for the coast". No figure, date or negation differs (those are the other kinds), the names
    are the same, they share STATE_COMMON content words, and each has 1 to STATE_MAX words the other lacks (the roots are the
    synonym list's: injured / hurt are one word). It is only a CANDIDATE: the model decides whether both can be true."""
    ta, tb = _without_times(a), _without_times(b)
    pa, pb = Profile(ta), Profile(tb)
    if pa.neg != pb.neg or pa.nums != pb.nums:
        return False
    qa, na = _question(pa, ta)
    qb, nb = _question(pb, tb)
    if na != nb:
        return False
    da, db = qa - qb, qb - qa
    return bool(da) and bool(db) and len(da) <= STATE_MAX and len(db) <= STATE_MAX and len(qa & qb) >= STATE_COMMON


ACCORDING = re.compile(r"(?i),?\s+according to [^,.;]+")


def claim_body(text: str) -> str:
    """The claim without who says it: "Police said 40 died" and "The family said 50 died" ask one
    question (an official against an outlet or a family is a dispute too, owner Oct 7 2026)."""
    t = ACCORDING.sub("", text or "")
    m = SPEAKER.match(t)
    return t[m.end():] if m and len(t) - m.end() > 15 else t


def candidate(a: str, b: str, pa: Profile | None = None, pb: Profile | None = None, sim: float | None = None,
              need: float | None = None) -> str | None:
    """'number', 'date', 'negation' or 'state' when a and b look like the same question answered differently;
    None when code can tell they are not a dispute. `sim` is the claims' sentence similarity (computed here for one
    pair when not given; judge() passes it from one matrix)."""
    a, b = claim_body(a), claim_body(b)
    pa, pb = Profile(a), Profile(b)
    qa, na = _question(pa, a)
    qb, nb = _question(pb, b)
    if na != nb or not (qa | qb):
        return None
    if sim is None:
        m, thr = embed.similarity([a, b])
        sim, need = float(m[0, 1]), QUESTION_SIM[embed.vectors([a])[1]]
    if sim < (need if need is not None else QUESTION_SIM["tfidf"]):
        return None
    if pa.neg != pb.neg:
        return "negation" if numbers_close(pa, pb) else None
    wa = {m.group(2).lower() for m in MONTH_DAY.finditer(a) if m.group(2)}
    wb = {m.group(2).lower() for m in MONTH_DAY.finditer(b) if m.group(2)}
    if wa and wb and not wa & wb:
        return "date"                     # "on Friday" / "on Saturday"
    da, db = date_of(a), date_of(b)
    if da and db and any(x is not None and y is not None and x != y for x, y in zip(da, db)):
        return "date"
    if pa.nums and pb.nums and not numbers_close(pa, pb):
        # "17 of 19" and "11 of 12": counts of two different groups
        ta, tb = OF_TOTAL.search(a), OF_TOTAL.search(b)
        if ta and tb and ta.group(2) != tb.group(2):
            return None
        # a bound is not a figure: "at least 40" agrees with 50, "up to 50" with 40
        if (LOWER.search(a) and max(pb.nums) >= min(pa.nums)) or (LOWER.search(b) and max(pa.nums) >= min(pb.nums)):
            return None
        if (UPPER.search(a) and min(pb.nums) <= max(pa.nums)) or (UPPER.search(b) and min(pa.nums) <= max(pb.nums)):
            return None
        if numbers_near(pa, pb):
            return "series"               # the same figure a little changed (82.10 / 82.35, 40 / 42): an update, or nothing
        return "number"
    if _state(a, b):
        return "state"                    # same question about a state, another answer: an update or a dispute, by time and the model
    return None


def is_update(times_a: list[dt.datetime], times_b: list[dt.datetime]) -> int:
    """1 when every report of b came clearly after every report of a (b updates a), -1 the other way,
    0 when the reports overlap in time (then it is a question for the model)."""
    if not times_a or not times_b:
        return 0
    if min(times_b) - max(times_a) >= UPDATE_GAP:
        return 1
    if min(times_a) - max(times_b) >= UPDATE_GAP:
        return -1
    return 0


def series_order(text_a: str, text_b: str, times_a: list, times_b: list) -> int:
    """For a figure that moved a little (a candidate of kind "series"): 1 when b is the later reading, -1 when a is, 0 when
    nothing says. Evidence, in this order: the reports' publish times (the same gap as any update), then the outlets' own
    clock times when each line names exactly one ("at 10:05" / "at 10:40"). Two outlets quoting a moving figure minutes
    apart with no time in the text prove nothing about its order: nothing is said, and the pair stays two lines as before."""
    u = is_update(times_a, times_b)
    if u:
        return u
    ca, cb = Profile(text_a).clocks, Profile(text_b).clocks
    if len(ca) == 1 and len(cb) == 1 and ca != cb:
        return 1 if next(iter(cb)) > next(iter(ca)) else -1
    return 0


def _key(a: str, b: str) -> str:
    return hashlib.sha256(json.dumps([a, b]).encode()).hexdigest()[:16]


def judge(router, texts: dict[int, str], times: dict[int, list], proposals: set[tuple[int, int]],
          exclude: set[tuple[int, int]], cache: dict, max_ask: int = 30
          ) -> tuple[set[tuple[int, int]], set[int], dict[int, int]]:
    """For one story's statements: (disputes, doubtful statement ids, {older figure: newer figure}).
    `proposals` (pairs from models, frames, earlier marks) are checked by the same gate as code's own;
    `exclude` holds claim/response pairs (never a dispute). `cache` keeps the model's answers per text pair."""
    from .match import check_conflicts
    prof = {i: Profile(t) for i, t in texts.items()}
    ids = sorted(texts)
    cands: dict[tuple[int, int], str] = {}
    if len(ids) >= 2:
        bodies = [claim_body(texts[i]) for i in ids]
        mat, _ = embed.similarity(bodies)
        need = QUESTION_SIM[embed.vectors(bodies[:1])[1]]
        row = {i: n for n, i in enumerate(ids)}
        for k, a in enumerate(ids):
            for b in ids[k + 1:]:
                kind = candidate(texts[a], texts[b], prof[a], prof[b], float(mat[k, row[b]]), need)
                if kind:
                    cands[(a, b)] = kind
        for a, b in proposals:                      # proposals from frames and earlier marks face the same gate
            p = (min(a, b), max(a, b))
            if p not in cands and a in texts and b in texts:
                kind = candidate(texts[p[0]], texts[p[1]], prof[p[0]], prof[p[1]], float(mat[row[p[0]], row[p[1]]]), need)
                if kind:
                    cands[p] = kind
    try:
        from . import reconcile
        for p, desc in reconcile.conflict_candidates(texts).items():
            STATS["reconcile_pairs"] += 1
            if p not in cands:
                STATS["reconcile_new"] += 1
                if RECONCILE_PROPOSALS:
                    if STAGED_ASK is not None:
                        from . import conflict_judge
                        res = conflict_judge.judge(texts[p[0]], texts[p[1]], STAGED_ASK)
                        if res["outcome"] == "different":
                            STATS["staged_different"] += 1
                            continue
                        if res["outcome"] == "unresolved":
                            STATS["staged_unresolved"] += 1
                            continue
                    cands[p] = reconcile.KIND_OF.get(desc["facet"], "number")
    except Exception:  # noqa: BLE001
        pass
    cands = {p: k for p, k in cands.items() if p not in exclude}
    updates: dict[int, int] = {}
    ask = []
    for (a, b), kind in sorted(cands.items(), key=lambda kv: kv[1] == "state"):    # the sure kinds first: the asking is capped
        if kind == "series":              # a little change: only an update, only with evidence of order; never asked, never a dispute
            u = series_order(texts[a], texts[b], times.get(a) or [], times.get(b) or [])
            if u:
                old, new = (a, b) if u == 1 else (b, a)
                updates[old] = new
            continue
        if kind == "number":
            u = is_update(times.get(a) or [], times.get(b) or [])
            if u:
                old, new = (a, b) if u == 1 else (b, a)
                updates[old] = new
                continue
        ask.append((a, b))
    todo = []
    for a, b in ask:
        for x, y in ((a, b), (b, a)):
            if _key(texts[x], texts[y]) not in cache:
                todo.append((x, y))
    todo = todo[:2 * max_ask]
    for (x, y), ans in zip(todo, check_conflicts(router, [(texts[x], texts[y]) for x, y in todo])):
        if ans is not None:               # a pair that could not be asked is not remembered (F94)
            cache[_key(texts[x], texts[y])] = ans
    disputes, doubtful = set(), set()
    for a, b in ask:
        first, second = cache.get(_key(texts[a], texts[b])), cache.get(_key(texts[b], texts[a]))
        state = cands.get((a, b)) == "state"    # a broad candidate: it never makes a statement doubtful, only a dispute or an update
        if first is None or second is None:
            if not state:
                doubtful |= {a, b}        # not asked, or the asking failed (quota): no amber, no green; asked again next run
            continue
        if first == second == "cannot_both_be_true":
            u = is_update(times.get(a) or [], times.get(b) or []) if state else 0
            if u:                         # the state changed between the reports: the later one is the update
                old, new = (a, b) if u == 1 else (b, a)
                updates[old] = new
            else:
                disputes.add((a, b))
        elif not state and ("unsure" in (first, second) or first != second):
            doubtful |= {a, b}
    return disputes, doubtful, updates

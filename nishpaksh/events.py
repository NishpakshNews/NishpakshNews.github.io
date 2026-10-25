"""Event types, learned and read by the parser (B15): one structure for ordering and for "is this a decisive act".

* THE VERB. A statement's event is its main verb, found by the dependency parse (nlp.parse), as a lemma ("was arrested" ->
  "arrest"). No list of verbs.
* THE USUAL COURSE OF EVENTS (ordering). For every verb lemma, the average place, between 0 (start) and 1 (end), at which
  statements with that verb sit in the dated stories we have stored: a person is detained, then charged, then released
  because that is the order the dated reports tell them in. Learned once a day from the claims of the newsroom
  (`refresh`), kept in the table `event_ranks`, used by order.py for events of one day with no clock time. A lemma seen
  fewer than MIN_N times has no rank (no edge from it).
* DECISIVE OR NOT (acts). Zero-shot natural-language inference, as in checkworthy.py: the statement is tested against three
  fixed descriptions (a death, a decisive act, routine activity). It replaces the verb lists of news.py.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict

from . import nli, nlp

log = logging.getLogger("nishpaksh.events")

MIN_N = 8                 # statements a verb needs before its rank counts
MARGIN = 0.15             # two verbs are ordered only when their ranks differ by this much
MIN_DAYS = 2              # a story needs this many distinct days for its statements to say anything about order
META = "__refreshed__"
REFRESH_HOURS = 20

_ranks: dict[str, float] = {}
_lemma_cache: dict[str, str | None] = {}


def verb_lemma(text: str) -> str | None:
    """The lemma of the main verb of one statement, or None (not analysed / no verb)."""
    if not text:
        return None
    if text in _lemma_cache:
        return _lemma_cache[text]
    toks = nlp.parse(text)
    out = None
    if toks:
        verbs = [t for t in toks if t.pos in ("VERB", "AUX") and t.lemma not in ("be", "have", "do")]
        root = next((t for t in verbs if t.dep == "ROOT"), None) or (verbs[0] if verbs else None)
        out = root.lemma if root else None
    if len(_lemma_cache) > 5000:
        _lemma_cache.clear()
    _lemma_cache[text] = out
    return out


def rank_of(text: str) -> float | None:
    lem = verb_lemma(text)
    return _ranks.get(lem) if lem else None


def earlier(a: float | None, b: float | None) -> bool | None:
    """True if a's event usually comes before b's, False if after, None when the data cannot say."""
    if a is None or b is None or abs(a - b) < MARGIN:
        return None
    return a < b


def set_ranks(ranks: dict[str, float]) -> None:
    _ranks.clear()
    _ranks.update(ranks)


# ------------------------------------------------------------------ learning the order
def learn(rows: list[dict]) -> dict[str, tuple[float, int]]:
    """{lemma: (mean place in its story 0..1, count)} from claim rows {story_id, text, time:{start}}."""
    per_story: dict[int, list[tuple[dt.datetime, str]]] = defaultdict(list)
    for r in rows:
        t = (r.get("time") or {}).get("start")
        try:
            when = dt.datetime.fromisoformat(t).replace(tzinfo=None) if t else None
        except (TypeError, ValueError):
            when = None
        lem = verb_lemma(r.get("text") or "")
        if when and lem:
            per_story[r["story_id"]].append((when, lem))
    acc: dict[str, list[float]] = defaultdict(list)
    for items in per_story.values():
        days = {w.date() for w, _ in items}
        if len(days) < MIN_DAYS:
            continue
        lo, hi = min(w for w, _ in items), max(w for w, _ in items)
        span = (hi - lo).total_seconds() or 1.0
        for w, lem in items:
            acc[lem].append((w - lo).total_seconds() / span)
    return {lem: (sum(v) / len(v), len(v)) for lem, v in acc.items() if len(v) >= MIN_N}


def load(store) -> int:
    from sqlalchemy import select
    from .db import event_ranks
    try:
        rows = store.rows(select(event_ranks.c.lemma, event_ranks.c.rank).where(event_ranks.c.lemma != META))
    except Exception as e:  # noqa: BLE001
        log.info("events: no event_ranks table yet (%s)", str(e)[:80])
        return 0
    set_ranks({r["lemma"]: float(r["rank"]) for r in rows})
    return len(rows)


def refresh(store) -> dict | None:
    """Once a day: learn the ranks from the stored claims and keep them. None when it ran recently."""
    from sqlalchemy import delete, insert, select
    from .db import claims, event_ranks
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    last = store.one(select(event_ranks.c.updated_at).where(event_ranks.c.lemma == META))
    if last and last["updated_at"] and now - last["updated_at"] < dt.timedelta(hours=REFRESH_HOURS):
        return None
    if not nlp.available():
        return None
    rows = store.rows(select(claims.c.story_id, claims.c.text, claims.c.time).where(claims.c.kind == "event",
                                                                                 claims.c.time.is_not(None)))
    learned = learn(rows)
    with store.route(insert(event_ranks)).engine.begin() as c:
        c.execute(delete(event_ranks))
        c.execute(insert(event_ranks), [dict(lemma=l, rank=r, n=n, updated_at=now) for l, (r, n) in learned.items()]
                  + [dict(lemma=META, rank=0.0, n=len(rows), updated_at=now)])
    set_ranks({l: r for l, (r, _n) in learned.items()})
    return {"claims": len(rows), "lemmas": len(learned)}


# ------------------------------------------------------------------ decisive acts, by meaning
DEATH = "Someone died or was killed."
DECISIVE = "An authority or a person took a decisive action: an arrest, an order, a ruling, a decision, a resignation, an announcement, a signing or a launch."
ROUTINE = "This describes a meeting, a speech, a hearing or other routine activity, or something that did not happen."
SURE = 0.6
_act_cache: dict[str, int] = {}


def act_score(text: str) -> int:
    """3 for a death, 2 for another decisive act, -1 for routine activity or what did not happen, 0 when unsure or
    when the NLI model cannot run (0 ranks it with the undecided, never as an act)."""
    if not text:
        return 0
    if text in _act_cache:
        return _act_cache[text]
    res = nli.predict([(text, DEATH), (text, DECISIVE), (text, ROUTINE)])
    if any(r is None for r in res):
        return 0
    d, a, r = (x[0] for x in res)
    score = 3 if d >= SURE else 2 if a >= SURE and r < SURE else -1 if r >= SURE and a < SURE else 0
    if len(_act_cache) > 5000:
        _act_cache.clear()
    _act_cache[text] = score
    return score

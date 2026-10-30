"""The writing desk: a job of its own, separate from the hourly pipeline (owner, Oct 6 2026).

The pipeline (run.py, at :05 UTC) reads, analyses and prepares stories; this step (right after it, hourly.yml)
only writes. Publishing used to come last in a 20-50 minute run and was squeezed out (Oct 6: one run
spent 50 minutes reading and never asked the writer), and reading spent the Flash-Lite the writer
needed as its fallback.

Each run: the settled stories (editions.settled), most important first (priority.value), are
written one by one until this clock hour has `desk_per_hour` articles (owner: at least one an hour,
at most two), `desk_tries` stories were tried, or the time is up. The quality bar is unchanged:
no good essay, no article.

Seats (owner, Oct 9 2026): at most three an hour, two for any story and one (`desk_beat_seat`) only for
a Domains or Sport story (priority.is_beat). A beat story takes the beat seat first, so the two others
stay for the rest; with no beat story ready the beat seat stays EMPTY (never a third general article).

    python -m nishpaksh.desk
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import time

from sqlalchemy import func

from . import carry
from .config import SETTINGS, database_url, gemini_api_keys, load_yaml
from .db import Store, articles, diagnostics, insert, published, select, stories, story_links, utcnow
from .router import GeminiBackend, Router

log = logging.getLogger("nishpaksh.desk")
DESK_LOOK = 25      # stories looked at per run at most (each costs a few cheap page calls)


REVIEW_SHARE = 0.6        # of the desk's time, at most this much goes to reviews; the rest is kept for writing (Oct 27 2026:
                          # reviews used the whole 28 minutes every run and few articles were written)
REVIEW_HOLDS = 2          # desk looks a story may wait for its review to finish


def _note_headline(stats: dict, sid) -> None:
    """Keep the headline step's numbers of a published story (rank among the outlets', retry, scores) for the ledger."""
    try:
        from .news import headline_record
        stats.setdefault("headlines", {})[str(sid)] = headline_record()
    except Exception:  # noqa: BLE001 - tuning data never stops a publication
        pass


def _review_open(store, sid: int) -> bool:
    """True while the story's review still has unasked questions and has been waited for fewer than REVIEW_HOLDS times."""
    try:
        from sqlalchemy import select as _sel
        from .db import stories as _st
        row = store.one(_sel(_st.c.analysis).where(_st.c.id == sid))
        an = dict((row or {}).get("analysis") or {})
        if not an.get("unanswered_asks"):
            if an.get("review_holds"):
                an.pop("review_holds")
                store.exec(_st.update().where(_st.c.id == sid).values(analysis=an))
            return False
        n = int(an.get("review_holds") or 0)
        if n >= REVIEW_HOLDS:
            return False
        an["review_holds"] = n + 1
        store.exec(_st.update().where(_st.c.id == sid).values(analysis=an))
        return True
    except Exception:  # noqa: BLE001
        return False

def _hour_start(now: dt.datetime) -> dt.datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def _beats(store: Store, ids: list[int]) -> set[int]:
    """The Domains and Sport stories among `ids`: the rating's beat or their feeds' (priority.is_beat)."""
    from .priority import _feed_beat, beat_feeds, is_beat
    if not ids:
        return set()
    bf = beat_feeds(store)
    tags: dict[int, list] = {}
    if bf:
        for r in store.rows(select(articles.c.story_id, articles.c.feed_id).where(articles.c.story_id.in_(ids))):
            tags.setdefault(r["story_id"], []).append(bf.get(r["feed_id"]))
    # an express story (express.py) shares the beat seat
    return {r["id"] for r in store.rows(select(stories.c.id, stories.c.analysis).where(stories.c.id.in_(ids)))
            if is_beat({"beat_feed": _feed_beat(tags.get(r["id"], []))}, r["analysis"] or {})
            or (r["analysis"] or {}).get("qualified_by") == "express"}


def _beat_order(store: Store, queue: list[int], beats: set[int]) -> list[int]:
    """`queue` with its beat stories put in the strict order (express.order: companies and tech express, then the
    Domains desk, then Sport (the Sport desk and express sport are one place), then entertainment express; an India
    story before a "world" one inside a place; same place: the queue's own order). Non-beat stories keep their
    positions, so only the beat seats follow this order (owner, Oct 13 2026)."""
    from . import express
    from .priority import _feed_beat, beat_feeds
    ids = [s for s in queue if s in beats]
    if len(ids) < 2:
        return list(queue)
    bf = beat_feeds(store)
    tags: dict[int, list] = {}
    if bf:
        for r in store.rows(select(articles.c.story_id, articles.c.feed_id).where(articles.c.story_id.in_(ids))):
            tags.setdefault(r["story_id"], []).append(bf.get(r["feed_id"]))
    key: dict[int, tuple] = {}
    for r in store.rows(select(stories.c.id, stories.c.analysis).where(stories.c.id.in_(ids))):
        a = r["analysis"] or {}
        desk = _feed_beat(tags.get(r["id"], [])) or (a.get("beat") or {}).get("desk") or (a.get("priority") or {}).get("beat")
        lane = a.get("express_lane") if a.get("qualified_by") == "express" else None
        key[r["id"]] = (express.tier(lane, desk), 0 if lane is None or a.get("express_sig") == "india" else 1)
    ordered = iter(sorted(ids, key=lambda s: key.get(s, (99, 1))))     # stable: the queue's order breaks ties
    return [next(ordered) if s in beats else s for s in queue]


def _express_ids(store: Store, ids: list[int]) -> set[int]:
    """The express stories among `ids` (qualified by the express rule, express.py)."""
    if not ids:
        return set()
    return {r["id"] for r in store.rows(select(stories.c.id, stories.c.analysis).where(stories.c.id.in_(ids)))
            if (r["analysis"] or {}).get("qualified_by") == "express"}


def write_allowance(ready_n: int) -> int | None:
    """How many articles one desk run may publish with `ready_n` stories ready (owner, Oct 29 2026): the fewer ready, the fewer
    written, so the pool is not emptied in one hour and the hours stay even. None = no limit beyond the seats (the pool is at or
    above `desk_write_all_from`: every banked seat may be used)."""
    if ready_n >= SETTINGS.desk_write_all_from:
        return None
    for at_least, n in SETTINGS.desk_write_steps:
        if ready_n >= at_least:
            return n
    return 0


def seats(store: Store, now: dt.datetime | None = None) -> tuple[int, int]:
    """(general seats left, beat seats left) for this run. Beat articles published fill the beat seat first.

    Unused seats carry (carry.py, owner Oct 11 2026): every hour of the quota day (Pacific, as Google's quotas)
    adds `desk_per_hour` general and `desk_beat_seat` beat seats; the articles published since the day began
    use them up, and a run may take what is left of all hours so far (at most `desk_carry_burst_hours` hours'
    worth in one run). With carry-over off the seats are the current clock hour's, as before."""
    now = now or utcnow()
    if not carry.enabled():
        ids = [r["story_id"] for r in store.rows(select(published.c.story_id)
                                                 .where(published.c.updated_at >= _hour_start(now)))]
        beat_used = min(len(_beats(store, ids)), SETTINGS.desk_beat_seat)
        return SETTINGS.desk_per_hour - (len(ids) - beat_used), SETTINGS.desk_beat_seat - beat_used
    ids = [r["story_id"] for r in store.rows(select(published.c.story_id)
                                             .where(published.c.updated_at >= carry.day_start(now)))]
    beat_cap, general_cap = carry.cap(SETTINGS.desk_beat_seat, now), carry.cap(SETTINGS.desk_per_hour, now)
    beat_used = min(len(_beats(store, ids)), beat_cap)
    hours = SETTINGS.desk_carry_burst_hours
    return (min(general_cap - (len(ids) - beat_used), carry.burst(SETTINGS.desk_per_hour, hours)),
            min(beat_cap - beat_used, carry.burst(SETTINGS.desk_beat_seat, hours)))


def published_this_hour(store: Store, now: dt.datetime | None = None) -> int:
    now = now or utcnow()
    row = store.one(select(func.count().label("n")).select_from(published)
                    .where(published.c.updated_at >= _hour_start(now)))
    return int(row["n"]) if row else 0


def _topic_roots(store: Store, ids: set[int]) -> dict[int, int]:
    """{story id: the oldest story of its topic}: a development is followed up its parents' links
    (story_links, or the candidate's own `edition.follows`) to the first article of the topic."""
    links: dict[int, list[int]] = {}
    for r in store.rows(select(story_links.c.parent_id, story_links.c.child_id)):
        links.setdefault(r["child_id"], []).append(r["parent_id"])
    follows = {r["id"]: ((r["analysis"] or {}).get("edition") or {}).get("follows")
               for r in store.rows(select(stories.c.id, stories.c.analysis).where(stories.c.id.in_(list(ids) or [-1])))}
    roots: dict[int, int] = {}
    for sid in ids:
        cur, seen = sid, {sid}
        while True:
            ups = [p for p in links.get(cur, []) if p not in seen]
            if not ups and follows.get(cur) and follows[cur] not in seen:
                ups = [follows[cur]]
            if not ups:
                break
            cur = min(ups)              # the oldest parent: story ids only grow
            seen.add(cur)
            follows.setdefault(cur, None)
        roots[sid] = cur
    return roots


def covered_topics(store: Store, now: dt.datetime | None = None) -> set[int]:
    """Topics (root story ids) that already have an article published today (Indian date)."""
    from .editions import IST
    now = now or utcnow()
    day = now.replace(tzinfo=dt.timezone.utc).astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day.astimezone(dt.timezone.utc).replace(tzinfo=None)
    today = {r["story_id"] for r in store.rows(select(published.c.story_id).where(published.c.updated_at >= start))}
    if not today:
        return set()
    return set(_topic_roots(store, today).values())


def fresh_topics(store: Store, ids: list[int], now: dt.datetime | None = None) -> set[int]:
    """Among `ids`, the stories whose topic has NO article published today: a new event, or a development
    of an earlier article whose topic has not been written about today."""
    covered = covered_topics(store, now)
    if not covered:
        return set(ids)
    roots = _topic_roots(store, set(ids))
    return {sid for sid in ids if roots.get(sid, sid) not in covered}


def ready(store: Store, now: dt.datetime | None = None, refused_out: set | None = None) -> list[int]:
    """Settled, qualifying, unpublished stories. There is no limit on articles per topic per day (owner,
    Oct 10 2026), but a story whose topic has no article yet today goes first (most important first);
    stories on a topic already written about today follow, in the same order, so they are written
    whenever no new topic is waiting and are never held back."""
    from . import editions, priority
    from .wire import independence_groups, independent
    now = now or utcnow()
    closed = editions.frozen_ids(store)
    rows = store.rows(select(stories.c.id, stories.c.analysis).where(stories.c.qualifies.is_(True)))
    out = []
    refused: set[int] = set()
    for r in rows:
        sid = r["id"]
        if sid in closed or not editions.settled(store, sid, now):
            continue
        # a follow-up with nothing new in it and no new outlet since: it waits for coverage, not for another look.
        # A refusal recorded under the old gate (no `v`; Oct 27 2026) is not one: those stories are looked at again.
        fu = ((r["analysis"] or {}).get("edition") or {}).get("followup") or {}
        if fu.get("v") != editions.RECORD_VERSION:
            fu = {}
        if fu.get("ok") is False and fu.get("at"):
            last = editions.last_new_source(store, sid)
            try:
                if last is not None and last <= dt.datetime.fromisoformat(fu["at"]):
                    continue
            except ValueError:
                pass
        arts = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency,
                                 articles.c.wire_group, articles.c.lang).where(articles.c.story_id == sid))
        groups = len(independent(independence_groups(arts))) if arts else 0
        p = (r["analysis"] or {}).get("priority")
        if p and p.get("filler"):
            continue
        out.append((priority.value(p, groups, len({a["lang"] for a in arts})), groups, sid))
        if fu.get("ok") is False:
            refused.add(sid)
    fresh = fresh_topics(store, [sid for _, _, sid in out], now)
    # a follow-up refused before goes after every other story (owner, Oct 16 2026: 6-11 a run were looked at
    # first and turned away again, before stories that could be written)
    out.sort(key=lambda t: (t[2] not in refused, t[2] in fresh, t[0], t[1], t[2]), reverse=True)
    if refused_out is not None:
        refused_out.update(refused)
    return [sid for _, _, sid in out]


def refused_last_run(store: Store, now: dt.datetime | None = None) -> set[str]:
    """Models that refused on every key (dropped for overload) in the previous desk run, if it was
    within the last 75 minutes: this run goes straight to the next model in the tier (Oct 7 2026: each
    run spent ~15 refused Flash calls, which seem to count against Google's daily limit, and most of
    its time before Flash-Lite wrote). The run after a skip tries them again."""
    now = now or utcnow()
    row = store.one(select(diagnostics.c.created_at, diagnostics.c.report).where(diagnostics.c.kind == "desk")
                    .order_by(diagnostics.c.created_at.desc()).limit(1))
    if not row or not row["created_at"] or now - row["created_at"] > dt.timedelta(minutes=75):
        return set()
    return set((row["report"] or {}).get("dropped") or [])


RUN_TRIES = 3             # a story is written at most this often in one run: the first try and up to two retries


def _write_with_retries(store: Store, router: Router, sid: int, until: float | None, stats: dict, fill: bool = False) -> bool:
    """Write the story; if the try ends "written short" (owner, Oct 28 2026), try again at once in the same run. The saved
    draft is continued, never started again (publish_story resumes it), and the failed try has lowered the bar one step
    (narrative.publish_bar; the first draft's bar stays 80%). Basic rules, a retry is made only while:
    the story is short on coverage (a lower bar can help it), the bar can still go lower than the one just tried
    (not at the floor, and not after a model error that used no try), it has had fewer than RUN_TRIES tries (the run may overrun its
    time for this: owner, Oct 28 2026, pace matters more than the clock). Retries are counted apart from the desk's tries
    (`stats["retries"]`), so they do not crowd other stories out. When the tries are used the draft is kept and the story
    waits for the next run, as before.
    `fill` (the second desk run, owner Oct 30 2026): the bar falls by whole statements and the tries are bounded by the
    bar reaching its floor (FILL_TRIES at most), not by RUN_TRIES."""
    from . import compose
    ok = compose.publish_story(store, router, sid)
    tries = 1
    limit = FILL_TRIES if fill else RUN_TRIES
    while not ok and tries < limit:
        out = compose.LAST_OUTCOME
        short = out.get("detail") or {}
        if out.get("outcome") != "written short" or short.get("why") != "coverage":
            break
        if compose.bar_for(compose._writer_tries(store, sid), int(short.get("total") or 0)) >= float(short.get("bar") or 0):
            break
        tries += 1
        stats.setdefault("retries", {})[str(sid)] = tries - 1
        ok = compose.publish_story(store, router, sid)
    stats.setdefault("tries_used", {})[str(sid)] = tries
    return ok


FILL_TRIES = 8        # most writer tries one story gets in a fill run (the bar reaches its floor well before this)


def story_size(store: Store, sid: int) -> int:
    """How many statements a story will carry, estimated before writing (owner, Oct 30 2026): its canonical statements
    that are not relations, less the lines another line already says in full (`analysis.covered`). The writer's own item
    list is built later (follow-up drops, the cap), so this orders stories; it does not set the bar."""
    from .db import canonical
    n = store.one(select(func.count().label("n")).select_from(canonical)
                  .where(canonical.c.story_id == sid, canonical.c.kind != "relation"))
    an = (store.one(select(stories.c.analysis).where(stories.c.id == sid)) or {}).get("analysis") or {}
    return max(1, int((n or {}).get("n") or 0) - len(an.get("covered") or {}))


def minutes_since_last_publication(store: Store, now: dt.datetime) -> int | None:
    row = store.one(select(func.max(published.c.updated_at).label("t")).select_from(published))
    t = (row or {}).get("t")
    return round((now - t).total_seconds() / 60) if t else None


def fill_work(store: Store, router: Router, now: dt.datetime | None = None) -> dict:
    """The job's second desk run (owner, Oct 30 2026): ONE article has to be published, quickly. The ready stories are
    taken smallest first (a refused follow-up last), the first is written completely, and the run ends with the first
    article published. No time stopper and no write allowance. The rules are the usual ones (checks, coherence guard,
    headline); only the bar falls by whole statements on a retry, which a small story needs. A story that cannot be
    published (coherence guard, headline failed, a model error) is passed over for the next smallest. The run is bounded by
    COUNT: each ready story gets its tries, and it ends without an article only if every ready story used them."""
    from . import compose, consolidate, verify
    now = now or utcnow()
    t_work = time.time()
    compose.STAGE_SECONDS.clear()
    compose.FILL_MODE = True
    stats: dict = {"mode": "fill", "already_this_hour": published_this_hour(store, now), "tried": 0, "published": [],
                   "skipped": {}, "write_allowance": None}
    try:
        refused: set[int] = set()
        queue = ready(store, now, refused_out=refused)
        stats["ready"] = len(queue)
        sizes = {sid: story_size(store, sid) for sid in queue}
        order = sorted(queue, key=lambda sid: (sid in refused, sizes[sid], queue.index(sid)))
        stats["fill"] = {"order": [[sid, sizes[sid]] for sid in order[:12]], "passed_over": {}}
        review_s = write_s = 0.0
        for sid in order:
            t0 = time.time()
            consolidate.consolidate_story(store, router, sid)
            review_s += time.time() - t0
            if _review_open(store, sid):
                stats["skipped"]["review not finished"] = stats["skipped"].get("review not finished", 0) + 1
                stats["fill"]["passed_over"][str(sid)] = "review not finished"
                continue
            verify.base_verdicts(store, sid)
            t1 = time.time()
            try:
                ok = _write_with_retries(store, router, sid, None, stats, fill=True)
            except Exception as e:  # noqa: BLE001
                log.exception("desk fill: story %s crashed while being written", sid)
                stats.setdefault("crashed", {})[str(sid)] = f"{type(e).__name__}: {str(e)[:200]}"
                ok = False
            write_s += time.time() - t1
            stats["tried"] += 1
            if ok:
                stats["published"].append(sid)
                stats["fill"].update(story=sid, statements=sizes[sid], tries=stats["tries_used"].get(str(sid), 1),
                                     seconds_to_publish=round(time.time() - t_work))
                if (compose.LAST_OUTCOME.get("detail") or {}).get("lowered_bar"):
                    stats.setdefault("lowered_bar", {})[str(sid)] = compose.LAST_OUTCOME["detail"]["lowered_bar"]
                _note_headline(stats, sid)
                break
            why = compose.LAST_OUTCOME.get("outcome", "?")
            detail = compose.LAST_OUTCOME.get("detail") or {}
            if why == "written short" and detail:
                stats.setdefault("short", {})[str(sid)] = detail
                why = f"written short ({detail.get('why')}{': ' + str(detail.get('guard')) if detail.get('guard') else ''})"
            stats["fill"]["passed_over"][str(sid)] = why
            stats["skipped"][why] = stats["skipped"].get(why, 0) + 1
        stats["review_seconds"], stats["write_seconds"] = round(review_s), round(write_s)
        stats["stage_seconds"] = dict(compose.STAGE_SECONDS)
    finally:
        compose.FILL_MODE = False
    return stats


def work(store: Store, router: Router, now: dt.datetime | None = None, until: float | None = None) -> dict:
    from . import compose, consolidate, verify
    now = now or utcnow()
    t_work = time.time()
    compose.STAGE_SECONDS.clear()
    stats = {"already_this_hour": published_this_hour(store, now), "tried": 0, "published": []}
    room, beat_room = seats(store, now)
    room, beat_room = max(0, room), max(0, beat_room)
    stats["seats"] = {"general": room, "beat": beat_room}
    if room <= 0 and beat_room <= 0:
        return stats
    # banked seats need more tries than one hour's: two more stories per seat beyond the hour's own
    extra = max(0, room - SETTINGS.desk_per_hour) + max(0, beat_room - SETTINGS.desk_beat_seat)
    max_tries = SETTINGS.desk_tries + 2 * extra
    queue = ready(store, now)
    beats = _beats(store, queue)
    queue = _beat_order(store, queue, beats)
    express_ids = _express_ids(store, queue)
    stats["ready"] = len(queue)
    stats["ready_beat"] = len(beats)
    allowed = write_allowance(len(queue))                      # None: every seat may be used
    stats["write_allowance"] = allowed
    stats["skipped"] = {}
    stats["startup_seconds"] = round(time.time() - t_work)       # before the first story: the queue, beats, order (owner, Oct 28 2026: 5 silent minutes)
    t_start = time.time()
    review_until = (t_start + REVIEW_SHARE * (until - t_start)) if until else None
    # stories whose review is already finished are written first (they cost no review time); the rest keep their order
    try:
        done = {sid for sid in queue if consolidate.is_current(store, sid)}
        queue = [s for s in queue if s in done] + [s for s in queue if s not in done]
    except Exception:  # noqa: BLE001
        pass
    # one express story is written first, outside the write allowance and the tries (owner, Oct 30 2026): express stories are
    # short and were crowded out by the queue. Only if it can take a beat seat; a failure just moves on to the normal queue.
    guaranteed: int | None = None
    if beat_room > 0:
        guaranteed = next((s for s in queue if s in express_ids), None)
        if guaranteed is not None:
            queue = [guaranteed] + [s for s in queue if s != guaranteed]
            stats["express_first"] = guaranteed
    review_s = write_s = 0.0
    for n, sid in enumerate(queue):
        # a try is a story the writer was asked to write; stories turned away before that (not a
        # follow-up yet, no headline) do not use one up, but at most DESK_LOOK stories are looked at
        if (room <= 0 and beat_room <= 0) or stats["tried"] >= max_tries or n >= DESK_LOOK + 5 * extra \
                or (allowed is not None and len(stats["published"]) - (guaranteed in stats["published"]) >= allowed) \
                or (until and time.time() > until):
            break
        beat = sid in beats
        if not (beat and beat_room > 0) and room <= 0:
            continue                                # only the beat seat is left: a beat story is needed
        if sid in express_ids and beat_room <= 0:
            continue                                # an express story has the beat seats only, never a general seat
        # written only from the current analysis: a story reviewed under older rules (Oct 8 2026, story
        # 11867: dispute marks from before the dispute gate were published) is reviewed again first;
        # when nothing changed this costs nothing (consolidate_story returns at once)
        t0 = time.time()
        if review_until and t0 > review_until and not consolidate.is_current(store, sid):
            stats["skipped"]["review deferred"] = stats["skipped"].get("review deferred", 0) + 1
            continue                                # no review time left this run: the review goes on next hour
        consolidate.consolidate_story(store, router, sid, until=review_until)
        review_s += time.time() - t0
        # a review with questions still unasked (cap, quota, error) is finished first: the article would repeat facts
        # the review has not yet compared. Held at most REVIEW_HOLDS desk looks, then written with what is known.
        if _review_open(store, sid):
            stats["skipped"]["review not finished"] = stats["skipped"].get("review not finished", 0) + 1
            continue
        verify.base_verdicts(store, sid)            # the 6-hour clock moved since it was analysed
        t1 = time.time()
        try:
            ok = _write_with_retries(store, router, sid, until, stats)
        except Exception as e:  # noqa: BLE001   one story's crash must not end the desk (Oct 30 2026: a TypeError in polish ended a 28-minute desk run)
            log.exception("desk: story %s crashed while being written", sid)
            stats.setdefault("crashed", {})[str(sid)] = f"{type(e).__name__}: {str(e)[:200]}"
            stats["tried"] += 1
            ok = False
        write_s += time.time() - t1
        if ok:
            stats["published"].append(sid)
            _note_headline(stats, sid)
            if (compose.LAST_OUTCOME.get("detail") or {}).get("lowered_bar"):      # published below 80%: marked for reading
                stats.setdefault("lowered_bar", {})[str(sid)] = compose.LAST_OUTCOME["detail"]["lowered_bar"]
            if sid in express_ids:
                stats.setdefault("express", []).append(sid)
            if sid != guaranteed:
                stats["tried"] += 1
            if beat and beat_room > 0:
                beat_room -= 1
                stats.setdefault("beat_seat", []).append(sid)
            else:
                room -= 1
            continue
        why = compose.LAST_OUTCOME.get("outcome", "?")
        if why in ("written short", "headline failed"):
            if sid != guaranteed:
                stats["tried"] += 1
            if why == "written short" and compose.LAST_OUTCOME.get("detail"):    # which check failed, with the numbers
                stats.setdefault("short", {})[str(sid)] = compose.LAST_OUTCOME["detail"]
        else:
            stats["skipped"][why] = stats["skipped"].get(why, 0) + 1
    stats["review_seconds"], stats["write_seconds"] = round(review_s), round(write_s)
    stats["stage_seconds"] = dict(compose.STAGE_SECONDS)      # where the write time went: thread_check, follow_up, writer, headline, ...
    if beat_room > 0:       # the seat stays empty (owner): say why
        why = "empty: no Domains or Sport story ready" if not beats else "empty: none could be written"
        if stats.get("beat_seat"):
            # some beat seats were filled (there are two since Oct 13 2026): keep the list of who took them and say how
            # many stayed empty beside it (the empty note used to overwrite the list)
            stats["beat_seat_empty"] = f"{beat_room} {why}"
        else:
            stats["beat_seat"] = why
    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=SETTINGS.desk_minutes)
    p.add_argument("--fill", action="store_true",
                   help="the job's second run: publish ONE article, the smallest ready story, with no time limit")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t0 = time.time()
    store = Store(database_url())
    store.init()
    keys = gemini_api_keys()
    if not keys:
        raise SystemExit("GEMINI_API_KEY is not set")
    router = Router(load_yaml("models.yaml")["tiers"], [GeminiBackend(k) for k in keys], store)
    router.resolve()
    skipping = refused_last_run(store)
    router.skip_models(skipping)
    gap = minutes_since_last_publication(store, utcnow())       # how long the site has been without a new article
    stats = fill_work(store, router) if a.fill else work(store, router, until=t0 + a.minutes * 60)
    stats.setdefault("mode", "first")
    stats["gap_minutes"] = gap
    # how many articles this run published, for the workflow: the job's first desk run publishes the feed at once only if
    # there is something new in it (hourly.yml, Oct 29 2026)
    if os.environ.get("GITHUB_OUTPUT"):
        try:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"published={len(stats.get('published') or [])}\n")
        except OSError:
            pass
    from .compose import finish_translations
    steps: dict[str, int] = {}                                   # seconds of each step after the writing, to see where the rest of the run went

    def timed(name, fn):
        t = time.time()
        try:
            return fn()
        finally:
            steps[name] = round(time.time() - t)
    stats["translated"] = timed("translated", lambda: finish_translations(store, router))    # half-translated Hindi pages (story 15429)
    from .categories import fill_live
    stats["sectioned"] = timed("sectioned", lambda: fill_live(store, router))                # live articles from before sections (Oct 9 2026)
    # readers (owner, Oct 9 2026): places and people of older live articles, videos of new ones, then notifications
    # and the day's recap. None of these may stop the desk's record from being written.
    from . import notify, videos
    from .categories import fill_places
    for name, step in (("placed", lambda: fill_places(store, router)),
                       ("videos", lambda: videos.fetch_new(store, router=router)),
                       ("notify", lambda: notify.run(store, router=router, send=False))):
        try:
            stats[name] = timed(name, step)
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", name, e)
            stats[name] = f"failed: {str(e)[:200]}"
    from . import embed
    from . import auditcount
    stats.update(step_seconds=steps, embed_cache=embed.cache_stats(), systems=auditcount.snapshot())
    stats.update(seconds=round(time.time() - t0), trigger=os.environ.get("RUN_TRIGGER", "manual"),
                 tier_calls={k: dict(v) for k, v in sorted(router.tier_log.items())},
                 dropped=sorted(router.dropped), rested=sorted(router.rested), skipping=sorted(skipping))
    log.info("desk: %s", stats)
    # the desk's record goes to diagnostics, not runs: runs is what spaces the pipeline's own runs
    store.exec(insert(diagnostics).values(created_at=utcnow(), kind="desk", report=stats))


if __name__ == "__main__":
    main()

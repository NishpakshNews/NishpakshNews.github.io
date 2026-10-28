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


def ready(store: Store, now: dt.datetime | None = None) -> list[int]:
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


def work(store: Store, router: Router, now: dt.datetime | None = None, until: float | None = None) -> dict:
    from . import compose, consolidate, verify
    now = now or utcnow()
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
    stats["skipped"] = {}
    t_start = time.time()
    review_until = (t_start + REVIEW_SHARE * (until - t_start)) if until else None
    # stories whose review is already finished are written first (they cost no review time); the rest keep their order
    try:
        done = {sid for sid in queue if consolidate.is_current(store, sid)}
        queue = [s for s in queue if s in done] + [s for s in queue if s not in done]
    except Exception:  # noqa: BLE001
        pass
    review_s = write_s = 0.0
    for n, sid in enumerate(queue):
        # a try is a story the writer was asked to write; stories turned away before that (not a
        # follow-up yet, no headline) do not use one up, but at most DESK_LOOK stories are looked at
        if (room <= 0 and beat_room <= 0) or stats["tried"] >= max_tries or n >= DESK_LOOK + 5 * extra \
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
        ok = compose.publish_story(store, router, sid)
        write_s += time.time() - t1
        if ok:
            stats["published"].append(sid)
            if sid in express_ids:
                stats.setdefault("express", []).append(sid)
            stats["tried"] += 1
            if beat and beat_room > 0:
                beat_room -= 1
                stats.setdefault("beat_seat", []).append(sid)
            else:
                room -= 1
            continue
        why = compose.LAST_OUTCOME.get("outcome", "?")
        if why in ("written short", "headline failed"):
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
    stats = work(store, router, until=t0 + a.minutes * 60)
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

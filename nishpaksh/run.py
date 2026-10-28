"""Hourly pipeline run.

    python -m nishpaksh.run                 # full run
    python -m nishpaksh.run --no-ingest     # reprocess what is stored
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from collections import Counter

from .config import SETTINGS, database_url, gemini_api_keys, load_yaml
from sqlalchemy import func

from .db import Store, select, stories, update
from .router import GeminiBackend, Router

log = logging.getLogger("nishpaksh")


def _light_pick(store: Store, queue_ids: list[int], allowance: int) -> list[int]:
    """The stories a LIGHT run still reads and analyses: the best-rated stories of the queue that have work waiting (new
    or changed articles, `dirty`), at most `allowance`. A story that already has everything it needs is not touched."""
    if allowance <= 0 or not queue_ids:
        return []
    dirty = {r["id"] for r in store.rows(select(stories.c.id).where(stories.c.dirty.is_(True), stories.c.id.in_(list(queue_ids))))}
    return [sid for sid in queue_ids if sid in dirty][:allowance]


def _parallel(items: list, fn, until: float, workers: int) -> list:
    """Apply fn to items with a few threads, starting nothing after `until`. One story failing
    is logged and skipped; it stays dirty and is retried next run."""
    import threading
    it = iter(items)
    lock = threading.Lock()
    done: list = []

    def worker():
        while time.time() < until:
            with lock:
                item = next(it, None)
            if item is None:
                return
            try:
                fn(item)
                with lock:
                    done.append(item)
            except Exception as e:  # noqa: BLE001
                log.warning("story %s failed: %s", item, str(e)[:300])

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return done


def run(store: Store | None = None, backend=None, time_budget_min: float = 40, ingest_news: bool = True,
        verify_budget: dict | None = None, search_news: bool | None = None, then_write: bool = False) -> dict:
    """One pipeline run. `then_write` runs the writing desk right after (local runs and tests; in
    production the desk is its own workflow)."""
    from . import extract, ingest, match, perspectives, priority, stories as story_mod, verify, wire
    search_news = ingest_news if search_news is None else search_news

    t0 = time.time()
    deadline = t0 + time_budget_min * 60
    store = store or Store(database_url())
    store.init()
    if backend is None:
        keys = gemini_api_keys()
        if not keys:
            raise SystemExit("GEMINI_API_KEY is not set")
        backend = [GeminiBackend(k) for k in keys]
        log.info("using %d Gemini API key(s)", len(keys))
    from .db import insert as _insert, runs as _runs, utcnow as _now
    run_id = store.insert_returning_id(_runs, dict(started_at=_now(), trigger=os.environ.get("RUN_TRIGGER", "manual")))
    router = Router(load_yaml("models.yaml")["tiers"], backend, store)
    router.resolve()
    stats: dict = {}

    from . import discover
    from .tavily import Tavily
    tavily = Tavily(store, daily_cap=SETTINGS.tavily_daily_cap) if search_news else None
    from . import carry
    bank = carry.Bank(store)       # our own hourly limits, unused shares carried to later hours (carry.py)

    def step(name, fn):
        """A failing optional step is recorded and skipped, never the end of the run."""
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            log.exception("step %s failed", name)
            stats.setdefault("errors", []).append(f"{name}: {str(e)[:200]}")
            return None

    import contextlib
    seconds: dict = {}
    stats["step_seconds"] = seconds         # where the run's time went (owner, Oct 28 2026: nothing in the pipeline was timed)

    @contextlib.contextmanager
    def timed(name):
        t = time.time()
        try:
            yield
        finally:
            seconds[name] = round(seconds.get(name, 0) + time.time() - t, 1)

    # LIGHT run (owner, Oct 28 2026): with many stories already ready the desk is the bottleneck, so the pipeline fetches,
    # groups and rates (the news stays fresh, new articles join their stories) but does not prepare more stories than
    # `light_read_allowance`; the search for more outlets, the blocked-page reads and the picture look-ups wait.
    light = False
    if SETTINGS.light_ready_min > 0:
        try:
            from . import desk as _desk
            ready_n = len(_desk.ready(store))
            light = ready_n >= SETTINGS.light_ready_min
            stats["light"] = {"ready": ready_n, "min": SETTINGS.light_ready_min, "on": light}
        except Exception as e:  # noqa: BLE001 - a full run is the safe default
            log.warning("ready count for the light run failed: %s", str(e)[:150])

    from . import events
    step("events", lambda: stats.__setitem__("events", events.refresh(store)))   # learned order of events, once a day
    step("event ranks", lambda: events.load(store))
    from . import dupescore
    step("dupescore", lambda: stats.__setitem__("dupescore", dupescore.refresh(store)))
    step("dupescore load", lambda: dupescore.load(store))
    if ingest_news:
        with timed("ingest"):
            ingest.sync_feeds(store)
            stats["ingested"] = ingest.ingest(store)
        # outlets' share pictures (collected now, shown later): older articles in stories looked at once
        if light:
            stats["images"] = dict(ingest.IMAGE_STATS, filled=None, skipped="light run")
        else:
            with timed("images"):
                stats["images"] = dict(ingest.IMAGE_STATS, filled=step("images", lambda: ingest.fill_images(store)))
    if search_news and not light:
        # who else covered the stories we know? found articles are grouped like any other
        # the stories being prepared for the writer (ranked in earlier runs) are searched first
        with timed("search"):
            stats["search"] = step("search", lambda: discover.discover(store, tavily, until=t0 + 8 * 60,
                                                                       focus=set(priority.queue(store)), bank=bank))
    stats["retracted_headline_only"] = extract.retract_unreadable(store)
    if tavily is not None and not light:
        # pages we could not read, in stories worth reading (grouped in earlier runs)
        with timed("tavily"):
            stats["tavily_pages_read"] = step("tavily", lambda: extract.read_blocked_pages(
                store, tavily, SETTINGS.tavily_extract_pages_per_run, focus=set(priority.queue(store)), bank=bank))
    with timed("grouping"):
        stats["wire_assigned"] = wire.assign_wire_groups(store)
        stats["grouped"] = step("grouping", lambda: story_mod.group_stories(store, router))   # a failure must not stop reading and writing
    from . import express as _express
    if _express.STATS:
        stats["express"] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _express.STATS.items()}
    stats["embedding"] = dict(story_mod.EMBED_STATS)     # what grouping did with the embedding quota (ledger.py records it)
    # only the stories worth writing are read and analysed (priority.py, owner Oct 6 2026): each story
    # with 3+ sources is rated from its headlines; the best `prep_queue` of them are prepared
    with timed("rating"):
        stats["rated"] = step("priority", lambda: priority.rank_new(store, router))
    queue_ids = priority.queue(store)
    focus = set(queue_ids)
    stats["queue"] = len(focus)
    # express stories (express.py): their own small reading cap, read from one outlet; apart from the queue.
    # A light run does not read them (their reading waits for a full run); its allowance goes to the queue's best stories.
    if light:
        express_ids = set()
        picked = _light_pick(store, queue_ids, SETTINGS.light_read_allowance)
        focus = set(picked)
        stats["light"]["read"] = picked
    else:
        express_ids = step("express_focus", lambda: _express.focus(store)) or set()
        focus |= express_ids
    # time plan: reading stops 20 minutes before the deadline; the story stage gets the rest
    with timed("extract"):
        stats["extracted"] = extract.extract_pending(store, router, deadline - 20 * 60, focus=focus, express=express_ids)

    # published stories are closed (editions.py): never re-analysed, re-read or rewritten
    from . import editions
    from .db import articles as _articles, published as _published
    frozen = editions.frozen_ids(store)
    dirty = [s["id"] for s in store.rows(select(stories.c.id).where(stories.c.dirty.is_(True)))]
    if frozen & set(dirty):
        ids = sorted(frozen & set(dirty))
        for i in range(0, len(ids), 500):
            store.exec(update(stories).where(stories.c.id.in_(ids[i:i + 500])).values(dirty=False))
    # stories outside the preparation queue stay dirty: they are analysed when they enter it
    dirty = [sid for sid in dirty if sid not in frozen and sid in focus]
    # most-covered stories first, so the stories readers most likely want are never the ones cut
    with store.engine.connect() as c:
        size = dict(c.execute(select(_articles.c.story_id, func.count())
                              .where(_articles.c.extracted_at.is_not(None)).group_by(_articles.c.story_id)).all())
    dirty.sort(key=lambda sid: -size.get(sid, 0))
    workers = 1 if str(store.engine.url).startswith("sqlite") else 4

    from . import origins

    from .consolidate import consolidate_story
    with timed("units_concepts"):
        stats["units"] = step("units", lambda: perspectives.refresh_units(store))

    def _concepts():
        from . import concepts
        from .db import claims as _claims
        words = {w for r in store.rows(select(_claims.c.loaded_words).where(_claims.c.loaded_words.is_not(None)))
                 for w in (r["loaded_words"] or [])}
        return concepts.map_new(store, router, words)
    with timed("units_concepts"):
        stats["concepts_mapped"] = step("concepts", _concepts)

    def analyse(sid):
        # one fact per statement (split.py): compound rows split before matching, so a fact two outlets
        # share becomes one statement with both behind it (story 13970: one definition written three times)
        from . import split
        split.split_story(store, router, sid)
        # a fact two outlets share inside sentences that bundle different details becomes one statement with both behind it
        # (bundles.py, owner Oct 26 2026): cut before matching, which then merges the shared parts
        if origins.independent_read_outlets(store, sid) >= 2:
            from . import bundles
            bundles.split_bundles(store, sid)
        match.match_story(store, router, sid)
        # merge duplicate statements, mark contradictions, one spelling per name: only for stories
        # that can be published (it costs a model call)
        n_read = origins.independent_read_outlets(store, sid)
        if n_read >= SETTINGS.qualify_min_outlets or (sid in express_ids and n_read >= 2):
            consolidate_story(store, router, sid)      # two outlets of an express story: conflicts are marked first
        perspectives.analyze_story(store, sid)
        if origins.assess_story(store, router, sid):
            # interim rule while perspectives are unknown: 3+ independent outlets, 2+ origins
            perspectives.mark_qualified(store, sid, "interim")
        elif sid in express_ids and _express.qualify(store, sid):     # one or two outlets, a named origin (express.py)
            pass
    with timed("analyse"):
        analysed = _parallel(dirty, analyse, deadline - 12 * 60, workers)
    from . import positions
    with timed("positions"):
        pos = step("positions", lambda: positions.daily(store, until=deadline))   # E29: the test first, then the clusters read it
    with timed("global_clusters"):
        stats["global_clusters"] = perspectives.recompute_global(store)
    # labels may have changed (or the clusters gone): re-label analysed stories (code only). A
    # published article keeps the perspectives it was written with.
    for sid in sorted(analysed):
        perspectives.analyze_story(store, sid)
        if origins.assess_story(store, None, sid):
            perspectives.mark_qualified(store, sid, "interim")
        elif sid in express_ids and _express.qualify(store, sid):
            pass

    # a story whose read articles were grouped on another embedding model's vectors cannot be
    # trusted to be one event (real data: one such "story" mixed GST, a temple and a phone launch);
    # it is not published until those articles are re-embedded and regrouped
    model = story_mod.embed_model(router)
    if model:
        untrusted = {r["story_id"] for r in store.rows(
            select(_articles.c.story_id).where(_articles.c.story_id.is_not(None), _articles.c.extracted_at.is_not(None),
                                               (_articles.c.embed_model.is_(None)) | (_articles.c.embed_model != model))
            .distinct())} - frozen
        if untrusted:
            ids = sorted(untrusted)
            for i in range(0, len(ids), 500):
                store.exec(update(stories).where(stories.c.id.in_(ids[i:i + 500]), stories.c.qualifies.is_(True))
                           .values(qualifies=False))
        stats["stories_awaiting_regroup"] = len(untrusted)
    # an express mark from an earlier run that no longer holds (a later outlet unread, a third outlet, a dispute) is
    # cleared, so no verdict or writing call is spent on it and the desk never writes it (story 23995, Oct 17 2026)
    stats["express_revoked"] = step("express_revoke", lambda: _express.revoke_stale(store, frozen)) or []
    qualifying = {r["id"] for r in store.rows(select(stories.c.id).where(stories.c.qualifies.is_(True)))} - frozen
    # stories that cannot be published yet spend no verdict or writing calls; they are
    # re-examined when another of their articles is read
    idle = [sid for sid in analysed if sid not in qualifying]
    for i in range(0, len(idle), 500):
        store.exec(update(stories).where(stories.c.id.in_(idle[i:i + 500])).values(dirty=False))
    # the 8-hour cap counts from when a story first met the publishing rule
    editions.note_rule(store, qualifying, sorted(set(analysed) | qualifying))

    budget = dict(verify_budget) if verify_budget else {
        "grounded": router.per_run_budget("grounded"), "judge": router.per_run_budget("judge")}
    stats["verify_budget"] = dict(budget)
    checked = 0
    with timed("verify"):
        for sid in analysed:
            if sid not in qualifying:
                continue
            verify.base_verdicts(store, sid)
            if SETTINGS.model_verdicts and time.time() < deadline - 6 * 60 and (budget.get("judge", 0) > 0):
                checked += verify.verify_story(store, router, sid, budget)
    # writing is the desk's job (desk.py, its own workflow at :35); the pipeline only prepares
    reasons = {sid: editions.settle_reason(store, sid) for sid in qualifying}
    settled = [sid for sid, why in reasons.items() if why]
    # published articles: only their colours mature, by code (the 6-hour clock)
    with timed("published_pages"):
        matured = sum(1 for sid in sorted(frozen) if editions.mature(store, sid))
        # later reports that replace a published line (threads.py): "Updates since published", the old line struck
        for sid in sorted(frozen):
            try:
                editions.attach_updates(store, router, sid)
            except Exception as e:  # noqa: BLE001 - an update list never stops the run
                log.warning("updates of story %s not attached: %s", sid, str(e)[:150])
        # "Latest in this story" (owner, Oct 24 2026): every page lists the follow-ups that develop it, newest last
        try:
            stats["children_attached"] = editions.attach_children(store)
        except Exception as e:  # noqa: BLE001 - a link list never stops the run
            log.warning("children not attached: %s", str(e)[:150])
    stats.update(stories_dirty=len(dirty), analysed=len(analysed), qualifying=len(qualifying),
                 settled=len(settled), settled_read=sum(1 for why in reasons.values() if why == "read"),
                 claims_checked=checked, colours_matured=matured,
                 live_pages=len(store.rows(select(_published.c.story_id))),
                 left_for_next_run=len(dirty) - len(analysed))
    if _express.STATS:      # the funnel again: the story stage added its own counts (express.py)
        stats["express"] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _express.STATS.items()}
    from . import when as _when
    if _when.STATS:         # who placed the reading's dates: code (agrees / differs), the model alone, refused
        stats["when"] = dict(_when.STATS)
    from . import heavy
    stats["heavy_cache"] = dict(heavy.stats, active=heavy.active(store))   # egress: values served locally vs fetched
    if pos is not None:
        stats["positions"] = {k: pos.get(k) for k in ("signal", "r", "separated", "null_r", "null_separated", "units", "items")}
    from . import retention
    stats.update(storage=retention.enforce(store), seconds=round(time.time() - t0))
    # the day's allowance; models switched off for this run (overloaded) still have theirs
    stats["quota_left"] = {t: router.remaining_today(t, include_disabled=True) for t in router.tiers}
    stats["quota_now"] = {t: router.remaining_now(t) for t in router.tiers}   # under the pacing curve
    stats["model_errors"] = dict(router.error_log.most_common(15))
    stats["model_calls"] = {k: dict(v) for k, v in sorted(router.call_log.items())}
    stats["tier_calls"] = {k: dict(v) for k, v in sorted(router.tier_log.items())}
    if tavily is not None:
        stats["tavily"] = {"spent_this_run": tavily.spent_this_run, "left_today": tavily.allowance_today()}
    if carry.enabled():       # what the hours still to come may spend, besides their own share (for the run's record)
        stats["carried"] = {k: bank.left(k, per) for k, per in (
            ("search_stories", SETTINGS.search_stories_per_run), ("tavily_pages", SETTINGS.tavily_extract_pages_per_run),
            ("tavily_searches", SETTINGS.tavily_searches_per_run))}
    if then_write:
        from . import desk
        stats["desk"] = desk.work(store, router)
        stats["published"] = len(stats["desk"]["published"])
    try:
        from . import bundles
        stats["bundles"] = dict(bundles.STATS)            # facts shared across bundled sentences (bundles.py)
        bundles.STATS.clear()
    except Exception:  # noqa: BLE001
        pass
    try:
        from .tools import model_check
        stats["models"] = model_check.snapshot()
    except Exception:  # noqa: BLE001 - a record, never a reason to fail a run
        pass
    try:
        from . import auditcount
        stats["systems"] = auditcount.snapshot()      # where a technical system and the old list it replaced disagreed
    except Exception:  # noqa: BLE001
        pass
    stats["health"] = health(store, stats)
    store.exec(update(_runs).where(_runs.c.id == run_id).values(finished_at=_now(), stats=stats))
    log.info("run complete: %s", stats)
    return stats


def stalled(store: Store, stats: dict) -> dict:
    """Is the pipeline still taking in news? Counts from this run and the last few finished runs:
    articles came in but none were grouped for STALL_RUNS runs in a row. (Zero articles read is
    not a stall signal: healthy runs often read none, as only multi-outlet stories are read.)"""
    from .db import runs as R
    n = SETTINGS.health_stall_runs
    past = [r["stats"] or {} for r in store.rows(select(R.c.stats).where(R.c.finished_at.is_not(None))
                                                  .order_by(R.c.id.desc()).limit(n - 1))]
    window = [stats] + past
    out: dict = {"problems": []}
    if len(window) < n:
        return {}
    came_in = sum((s.get("ingested") or 0) + ((s.get("search") or {}).get("new_articles") or 0) for s in window)
    if came_in and not any(s.get("grouped") for s in window):
        out["problems"].append(f"{came_in} new articles in the last {n} runs but none grouped")
    return {"stall": out["problems"]} if out["problems"] else {}


def writer_silent(store: Store, stats: dict) -> str | None:
    """The writing desk (desk.py) asked the writer in its last two runs and got nothing, or the last
    two clock hours ended without an article while stories were ready (owner: at least one an hour).
    Oct 5 2026: five hours of refused Flash calls went unnoticed."""
    from .db import diagnostics as D, published as P
    reports = [r["report"] or {} for r in store.rows(select(D.c.report).where(D.c.kind == "desk")
                                                      .order_by(D.c.id.desc()).limit(2))]
    problems = []
    w = [(r.get("tier_calls") or {}).get("writer") for r in reports]
    if len(w) == 2 and all(x is not None for x in w) and not any(x.get("ok", 0) for x in w):
        refused: Counter = Counter()
        for x in w:
            refused.update(x)
        problems.append(f"writer wrote nothing in the desk's last 2 runs ({sum(refused.values())} calls: "
                        + ", ".join(f"{n} {k}" for k, n in refused.most_common()) + ")")
    from .db import utcnow as _now
    import datetime as _dt
    now = _now()
    since = now.replace(minute=0, second=0, microsecond=0) - _dt.timedelta(hours=2)
    recent = store.rows(select(P.c.story_id).where(P.c.updated_at >= since, P.c.updated_at < since + _dt.timedelta(hours=2)))
    if reports and not recent and (stats.get("settled") or 0) > 0:
        problems.append(f"no article in the last two clock hours while {stats.get('settled')} stories are ready")
    return "; ".join(problems) or None


def health(store: Store, stats: dict) -> dict:
    """Invariants checked on every real run. A failure is written into the run record (and the
    log) so problems in the live data are seen without waiting for someone to notice the site."""
    from .db import articles as A, canonical as C
    from .stories import story_health
    out: dict = {"problems": []}
    try:
        out.update(story_health(store))
        biggest = out["largest_stories"][0][1] if out["largest_stories"] else 0
        if biggest > SETTINGS.health_max_story_articles:
            out["problems"].append(f"a story holds {biggest} articles: grouping may be merging events")
        import datetime as _dt
        from .db import utcnow as _now

        def _bad(o):
            o = o or {}
            try:
                stood = (_now() - _dt.datetime.fromisoformat(o["met_at"])).total_seconds() / 3600
            except (KeyError, TypeError, ValueError):
                stood = -1
            return (o.get("n_origins", 0) < SETTINGS.established_min_origins
                    or o.get("outlets", 0) < SETTINGS.established_min_outlets
                    or stood < SETTINGS.established_after_hours)
        bad = [c["id"] for c in store.rows(select(C.c.id, C.c.origins).where(C.c.verdict == "corroborated"))
               if _bad(c["origins"])]
        if bad:
            out["problems"].append(f"{len(bad)} established statements lack 2 origins / 3 outlets / 6 hours: {bad[:10]}")
        summ = store.rows(select(A.c.id).where(A.c.text_source == "summary", A.c.extracted_at.is_not(None)).limit(5))
        if summ:
            out["problems"].append(f"headline-only articles were read for facts: {[r['id'] for r in summ]}")
        # a tier is dead for the day when what is left cannot pay for one call (one grouping batch
        # for embeddings). Oct 2026: 20 embeddings and 0 Flash-Lite left read as "no problems"
        # while nothing new was read or grouped for nine hours.
        need = {"embed": SETTINGS.health_embed_batch, "light": 1, "page": 1, "writer": 1}
        left = stats.get("quota_left", {})
        dead = [t for t, n in need.items() if t in left and left[t] < n]
        if dead:
            out["problems"].append(f"daily quota used up for: {', '.join(dead)} (resets 00:00 Pacific)")
        out.update(stalled(store, stats))
        silent = writer_silent(store, stats)
        if silent:
            out["problems"].append(silent)
        for o, rate in ((stats.get("units") or {}).get("outlets_departing_often") or {}).items():
            out["problems"].append(f"{o}: {rate:.0%} of assessed articles fall outside its perspective")
        if stats.get("errors"):
            out["problems"].append(f"{len(stats['errors'])} steps failed")
    except Exception as e:  # noqa: BLE001
        out["problems"].append(f"health check failed: {e}")
    out["problems"] += out.pop("stall", [])
    for p in out["problems"]:
        log.warning("HEALTH: %s", p)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--time-budget", type=float, default=40, help="minutes")
    p.add_argument("--no-ingest", action="store_true")
    p.add_argument("--no-search", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        run(time_budget_min=a.time_budget, ingest_news=not a.no_ingest, search_news=not (a.no_search or a.no_ingest))
    except BaseException as e:  # noqa: BLE001
        # GitHub job logs are not readable from where the pipeline is maintained: keep the traceback
        if not isinstance(e, SystemExit) or e.code not in (0, None):
            _record_crash()
        raise


def _record_crash() -> None:
    import json
    import traceback
    try:
        from .db import diagnostics, insert
        Store(database_url()).exec(insert(diagnostics).values(   # routed: diagnostics live with the readers
            kind="crash", report={"trigger": os.environ.get("RUN_TRIGGER", "manual"),
                                  "traceback": traceback.format_exc()[-6000:]}))
    except Exception:  # noqa: BLE001
        log.exception("could not record the crash")


if __name__ == "__main__":
    main()

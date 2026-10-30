"""The ledger (owner, Oct 12 2026): one record per hourly run, kept in the repository, so the next session (and the
owner's tuning) starts from numbers, not guesses. "Embedding is a lot of confusion": this says, run by run, how many
embedding texts were available, how many were spent, on which outlets, and what those outlets yielded.

    python -m nishpaksh.ledger                    # after the desk step of hourly.yml
    python -m nishpaksh.ledger --dir ledger --rebuild      # render LEDGER.md again from the stored runs

Files in `ledger/` (the folder is committed by .github/scripts/ledger.sh, like the learned titles):
    README.md             what every field means (rewritten when this module's VERSION changes)
    runs-YYYY-MM.jsonl    one JSON line per run: the detail (kept 120 days)
    LEDGER.md             the readable summary, regenerated every run: days, last runs, outlets, express lane

Everything here is a report. Nothing in the pipeline reads it; a failure here stops nothing (the step has
continue-on-error) and costs no model call and no quota. Built from the run's own record (`runs.stats`), the
desk's record (`diagnostics`, kind "desk") and one light query on the articles of the last 72 hours.

`build_entry` and `render` are plain functions of plain data (tested without a database); `main` reads the database.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import pathlib
from collections import Counter, defaultdict

log = logging.getLogger("nishpaksh.ledger")

VERSION = 1
KEEP_DAYS = 120
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
DEFAULT_DIR = pathlib.Path(__file__).resolve().parent.parent / "ledger"

# the run stats copied as they are (small numbers), the rest of `runs.stats` is left out on purpose
PIPELINE_KEYS = ("grouped", "rated", "queue", "extracted", "stories_dirty", "analysed", "qualifying", "settled",
                 "settled_read", "left_for_next_run", "claims_checked", "colours_matured", "live_pages",
                 "stories_awaiting_regroup", "wire_assigned", "retracted_headline_only", "tavily_pages_read")


def _ist(t: dt.datetime) -> str:
    return (t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t).astimezone(IST).strftime("%Y-%m-%d %H:%M")


def pt_day(t: dt.datetime) -> str:
    """The quota day (Pacific, as Google's quotas) a moment belongs to."""
    t = t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # noqa: BLE001   no tz database: Pacific is UTC-7 or -8; -8 is a safe approximation
        return (t - dt.timedelta(hours=8)).date().isoformat()


def stamp(t: dt.datetime) -> str:
    """UTC, second precision, always the same shape (they are compared as text): 2026-10-12T16:05:12Z."""
    t = t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t.astimezone(dt.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


# --- one run's record ----------------------------------------------------------------------------------------------

def build_entry(run: dict, desk: dict | None, outlets: dict | None, intake: dict | None, embed_used: int | None,
                ready_end: int | None = None) -> dict:
    """The record of one run, from plain data.

    run     the `runs` row: id, started_at, finished_at, trigger, stats
    desk    the desk's report (diagnostics, kind "desk") of this hour, or None
    outlets {outlet: [articles in the 72 h window, embedded, in a story with 3+ independent outlets]}
    intake  {"by_outlet": {outlet: new articles this run}} (from the articles table)
    embed_used  embedding texts used so far on this quota day (quota_usage): a number, or {"total": n,
                "by_key": {"k1": n, "k2": n, "k3": n}} (one per Gemini key), or None"""
    st = dict(run.get("stats") or {})
    started = run.get("started_at") or dt.datetime.now(dt.timezone.utc)
    emb = dict(st.get("embedding") or {})
    yields = emb.pop("yields", None) or {}
    left = (st.get("quota_left") or {}).get("embed")
    used = embed_used if isinstance(embed_used, dict) else {"total": embed_used}
    entry: dict = {
        "v": VERSION, "run": run.get("id"), "at": stamp(started), "ist": _ist(started),
        "pt_day": pt_day(started), "trigger": run.get("trigger"), "seconds": st.get("seconds"),
        "intake": {"new": st.get("ingested"), "found_by_search": (st.get("search") or {}).get("new_articles"),
                   "by_outlet": (intake or {}).get("by_outlet") or {}},
        "embed": {"used_today": used.get("total"), "used_by_key": used.get("by_key") or {}, "left_today": left,
                  "this_run": emb, "pace_left_now": (st.get("quota_now") or {}).get("embed")},
        "outlets": outlets or {},
        "pipeline": {k: st[k] for k in PIPELINE_KEYS if k in st},
        "quota_left": st.get("quota_left") or {},
        "tier_calls": st.get("tier_calls") or {},
        "problems": list(((st.get("health") or {}).get("problems")) or []) + list(st.get("errors") or []),
    }
    if yields:
        entry["yield_at_start"] = yields
    if st.get("express"):
        entry["express"] = st["express"]
    # the pool and what was done about it (owner, Oct 29 2026: the system should settle around a level; this is how to see the level
    # and whether the rules move it): ready stories at the job's first desk run, after it (the light/full decision), and at the end
    light = st.get("light") or {}
    if light or desk or ready_end is not None:
        entry["pool"] = {"mode": ("prime" if light.get("prime") else "light" if light.get("on") else "full") if light else None,
                         "at_desk_start": (desk or {}).get("ready"), "after_first_desk": light.get("ready"), "end": ready_end,
                         "write_allowance": (desk or {}).get("write_allowance"),
                         "read": len(light.get("read") or []) if light.get("on") else (st.get("refill") or {}).get("queue"),
                         "desk_runs": (desk or {}).get("runs"), "desk_seconds": (desk or {}).get("seconds")}
    if desk:
        entry["desk"] = {k: desk[k] for k in ("published", "seats", "ready", "ready_beat", "tried", "skipped",
                                              "beat_seat", "beat_seat_empty", "already_this_hour", "short", "write_allowance",
                                              "runs", "seconds", "run_log", "fill", "headlines") if k in desk}
        if desk.get("express"):
            entry["desk"]["express"] = desk["express"]
    return entry


# --- the files -----------------------------------------------------------------------------------------------------

def _month_file(directory: pathlib.Path, at: str) -> pathlib.Path:
    return directory / f"runs-{at[:7]}.jsonl"


def append(directory: pathlib.Path, entry: dict) -> pathlib.Path:
    """Add the entry to its month's file; an entry for the same run is replaced (a workflow run again)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = _month_file(directory, entry["at"])
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keep = []
    for ln in lines:
        try:
            if json.loads(ln).get("run") == entry.get("run") and entry.get("run") is not None:
                continue
        except ValueError:
            continue
        keep.append(ln)
    keep.append(json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return path


def read_entries(directory: pathlib.Path, days: float = 8, now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    since = stamp(now - dt.timedelta(days=days))
    out = []
    for path in sorted(directory.glob("runs-*.jsonl")):
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if e.get("at", "") >= since:
                out.append(e)
    out.sort(key=lambda e: e.get("at", ""))
    return out


def prune(directory: pathlib.Path, now: dt.datetime | None = None) -> list[str]:
    """Delete month files that end more than KEEP_DAYS ago."""
    now = now or dt.datetime.now(dt.timezone.utc)
    removed = []
    for path in sorted(directory.glob("runs-*.jsonl")):
        try:
            y, m = int(path.stem[5:9]), int(path.stem[10:12])
            end = dt.datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if now - end > dt.timedelta(days=KEEP_DAYS):
            path.unlink()
            removed.append(path.name)
    return removed


# --- the readable summary ------------------------------------------------------------------------------------------

def _sum(entries: list[dict], *path) -> int:
    t = 0
    for e in entries:
        x = e
        for p in path:
            x = x.get(p) if isinstance(x, dict) else None
        t += _num(x) or 0
    return int(t)


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return out


def render(entries: list[dict], now: dt.datetime | None = None) -> str:
    """LEDGER.md from the stored runs (the last 8 days are enough)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    L: list[str] = ["# Nishpaksh ledger", ""]
    if not entries:
        return "\n".join(L + ["No runs recorded yet. The first run writes here.", ""])
    L += [f"Generated {_ist(now)} IST from {len(entries)} runs ({entries[0]['ist']} to {entries[-1]['ist']} IST). "
          "Field meanings: README.md. Detail per run: runs-YYYY-MM.jsonl.", ""]

    # 1. embedding by quota day -------------------------------------------------------------------------------------
    by_day: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_day[e["pt_day"]].append(e)
    rows = []
    for day in sorted(by_day, reverse=True):
        es = by_day[day]
        used = [x for x in (_num(e["embed"].get("used_today")) for e in es) if x is not None]
        left = [x for x in (_num(e["embed"].get("left_today")) for e in es) if x is not None]
        ex_emb = _sum(es, "express", "embedded")
        rows.append([day, len(es), _sum(es, "embed", "this_run", "embedded"), int(max(used)) if used else "",
                     int(min(left)) if left else "", ex_emb or "",
                     _sum(es, "embed", "this_run", "held_world") // max(1, len(es)),
                     (es[-1]["embed"]["this_run"] or {}).get("waiting_after", "")])
    L += ["## Embedding quota, by quota day (Pacific)", "",
          *_table(["day", "runs", "texts embedded (sum of runs)", "used by day's end", "least left", "of it express",
                   "world held (avg/run)", "waiting at last run"], rows), "",
          "`used by day's end` is the quota counter (3 keys x 1,000 = 3,000 texts a day). `least left` is the lowest "
          "remaining the runs saw. Waiting articles are embedded in later runs while quota lasts.", ""]

    # 2. last runs --------------------------------------------------------------------------------------------------
    rows = []
    for e in entries[-24:][::-1]:
        tr, pl, dk = e["embed"]["this_run"] or {}, e.get("pipeline") or {}, e.get("desk") or {}
        pub = dk.get("published")
        rows.append([e["ist"], (e.get("intake") or {}).get("new"), tr.get("budget", ""), tr.get("embedded", ""),
                     tr.get("waiting_after", ""), e["embed"].get("left_today", ""), pl.get("grouped", ""),
                     pl.get("queue", ""), pl.get("qualifying", ""), pl.get("settled", ""),
                     len(pub) if isinstance(pub, list) else "", len(e.get("problems") or [])])
    L += ["## Last 24 runs (newest first)", "",
          *_table(["IST", "new articles", "embed budget", "embedded", "waiting", "embed left", "grouped",
                   "reading queue", "qualifying", "settled", "published", "problems"], rows), ""]

    # 2b. the pool and the rhythm --------------------------------------------------------------------------------------
    rows = []
    for e in entries[-24:][::-1]:
        po, pub = e.get("pool") or {}, (e.get("desk") or {}).get("published")
        if po:
            rows.append([e["ist"], po.get("mode", ""), po.get("at_desk_start", ""), po.get("write_allowance", ""),
                         len(pub) if isinstance(pub, list) else "", po.get("after_first_desk", ""), po.get("read", ""),
                         po.get("end", ""), po.get("desk_runs", ""), e.get("seconds", "")])
    rh = next((e["rhythm"] for e in reversed(entries) if e.get("rhythm")), None)
    if rows or rh:
        L += ["## The pool and the rhythm", ""]
        if rh:
            L += [f"Last 24 completed hours: {rh['hours_with_article']} with an article, {rh['empty_hours']} empty, "
                  f"{rh['mean_per_hour']} a hour (spread {rh['sd_per_hour']}); longest gap {rh['longest_gap_min']} min; "
                  f"per hour, oldest first: {' '.join(str(h) for h in rh['hours_24h'])}.", ""]
        if rows:
            L += [*_table(["IST", "mode", "ready at desk start", "desk may write", "published", "ready after first desk",
                           "stories read", "ready at end", "desk runs", "pipeline seconds"], rows), ""]

    # 3. outlets ----------------------------------------------------------------------------------------------------
    intake_week: Counter = Counter()
    embedded_week: Counter = Counter()
    for e in entries:
        intake_week.update({k: v for k, v in ((e.get("intake") or {}).get("by_outlet") or {}).items() if _num(v)})
        embedded_week.update({k: v for k, v in ((e["embed"].get("this_run") or {}).get("by_outlet") or {}).items()
                              if _num(v)})
    latest = next((e["outlets"] for e in reversed(entries) if e.get("outlets")), {})
    rows = []
    for o in sorted(set(latest) | set(intake_week), key=lambda o: (-(latest.get(o) or [0, 0, 0])[2], o)):
        n, emb_n, big = (latest.get(o) or [0, 0, 0])[:3]
        rows.append([o, intake_week.get(o, 0), embedded_week.get(o, 0), n, emb_n, big,
                     f"{big / emb_n:.0%}" if emb_n else ""])
    L += ["## Outlets", "",
          *_table(["outlet", "new articles (8 d)", "embedded (8 d)", "in 72 h window", "of them embedded",
                   "in a 3+ outlet story", "yield"], rows), "",
          "`yield` = share of the outlet's embedded articles that sit in a story with 3+ independent outlets. It is "
          "what decides who is embedded first when the budget is short (`stories._yields`).", ""]

    # 4. express lane -----------------------------------------------------------------------------------------------
    ex = [e for e in entries if e.get("express")]
    if ex:
        keys: Counter = Counter()
        for e in ex:
            for k, v in e["express"].items():
                if _num(v):
                    keys[k] += v
        reasons: Counter = Counter()
        for e in ex:
            reasons.update({k: v for k, v in (e["express"].get("excluded") or {}).items() if _num(v)})
        L += ["## Express lane (sum over these runs)", "",
              *_table(["step", "count"], [[k, int(v)] for k, v in keys.items()]), ""]
        if reasons:
            L += ["Kept out by code, by list:", "",
                  *_table(["list", "count"], [[k, int(v)] for k, v in reasons.most_common()]), ""]
        terms: Counter = Counter()
        for e in ex:
            terms.update({k: v for k, v in (e["express"].get("excluded_terms") or {}).items() if _num(v)})
        if terms:
            L += ["The words doing the excluding (top 25; a word that keeps out good stories is too strict, "
                  "loosen it in config/express.yaml):", "",
                  *_table(["list:word", "count"], [[k, int(v)] for k, v in terms.most_common(25)]), ""]
        for key, title, head in (("story_in", "Express stories that qualified (lane:origin kind):", "lane:origin"),
                                 ("story_out", "Express stories that did not qualify, and why (a reason that "
                                  "dominates is the dial to look at):", "reason"),
                                 ("story_out_lane", "...the same by lane:", "lane:reason")):
            c: Counter = Counter()
            for e in ex:
                c.update({k: v for k, v in (e["express"].get(key) or {}).items() if _num(v)})
            if c:
                L += [title, "", *_table([head, "count"], [[k, int(v)] for k, v in c.most_common()]), ""]
        wrote = sum(len((e.get("desk") or {}).get("express") or []) for e in entries)
        L += [f"Express articles written by the desk in these runs: {wrote}.", ""]
        last = (ex[-1]["express"].get("now") or {})
        if last:
            L += ["At the last run: " + ", ".join(f"{k} {v}" for k, v in last.items()) + ".", ""]
    else:
        L += ["## Express lane", "", "Nothing recorded yet (the lane is built in parts; its funnel appears here "
              "once it runs).", ""]

    # 5. problems ---------------------------------------------------------------------------------------------------
    probs = [(e["ist"], p) for e in entries[-24:] for p in e.get("problems") or []]
    if probs:
        L += ["## Problems seen in the last 24 runs", "", *[f"- {t}: {p}" for t, p in probs[-30:]], ""]
    return "\n".join(L)


README = f"""# Ledger

One record per hourly run, written after the desk step (`python -m nishpaksh.ledger`, schema version {VERSION}).
Purpose: embedding use and outlet yield were hard to see; this keeps them, run after run, in the repository so
the next session starts from numbers.

## Pool and rhythm (Oct 29 2026)

`pool`: `mode` (light, full, prime) of the run; `at_desk_start` ready stories when the job's first desk run began;
`write_allowance` how many that desk run could publish (None: every seat); `after_first_desk` the count that decided light or full;
`read` stories the run read; `end` ready at the end of the job; `desk_runs` and `desk_seconds` of the job's desk runs.
`rhythm`: `hours_24h` articles written in each of the 24 completed hours before this record (oldest first), `empty_hours`,
`mean_per_hour`, `sd_per_hour`, `longest_gap_min` between desk runs that wrote something, `first_in_job_min` from the job's start to its
first article. Times are those of the desk's record (the end of its run), a few minutes before the feed shows the article.
Consistency is the goal: no empty hours and a small spread, then more articles.

## Files
- `LEDGER.md`: the readable summary of the last 8 days, regenerated every run.
- `runs-YYYY-MM.jsonl`: one JSON object per run (kept {KEEP_DAYS} days). Fields below.

## Fields of a run record
- `run`, `at` (UTC), `ist`, `pt_day` (the quota day the run belongs to: Pacific, like Google's quotas), `trigger`, `seconds`.
- `intake`: `new` articles stored this run, `found_by_search`, `by_outlet` (new articles per outlet this run).
- `embed`: `used_today` (the quota counter: embedding texts used so far this quota day, all keys), `used_by_key` (the same per
  Gemini key: k1, k2, k3), `left_today`
  (what the router thought was left, after its reserves), `pace_left_now` (what the pacing curve allows now), and
  `this_run`, from `stories.EMBED_STATS`:
  `budget` (texts this run may use) = everything left today minus a reserve for each later run (`embed_reserve_per_run`),
  never below `embed_min_texts_per_run` and never above the pacing curve; `left_today`, `runs_left`, `pace_now`,
  `waiting_new` / `waiting_old` (articles without a vector: new ones / read ones on another model's vector),
  `chosen_new` / `chosen_old` (what the budget took), `embedded` (texts actually sent), `by_outlet` (embedded per outlet),
  `waiting_before` / `waiting_after`, `held_world` (world-outlet articles kept back by `worldgate.hold`).
- `outlets`: per outlet `[articles in the 72 h window, of them embedded, of them in a story with 3+ independent
  outlets]`; the yield is the third over the second.
- `yield_at_start`: the yield share `stories._yields` used to order this run's embedding (0.5 = too few to judge).
- `pipeline`: counts of the run's stages (grouped, rated, queue, extracted, analysed, qualifying, settled ...).
- `quota_left`, `tier_calls`: Gemini quota left per tier at the end of the run, and the calls made, by outcome.
- `desk`: the writing desk's record of the hour: `published` (story ids), `seats` (general / beat left), `ready`,
  `ready_beat`, `skipped`, `beat_seat`, `beat_seat_empty`, `short`.
- `express`: the express lane's funnel for the run (appears when the lane runs). Counts per step, in order:
  `taken` (new links from express feeds that were downloaded), `intake_excluded` (kept out by code before the page was
  fetched) and `intake_over_cap`, `unreadable` (page not fully readable: option B), `asked` (headlines the model
  answered, each asked twice), `not_lane` (no lane, or the two answers differed), `passed` and `passed_<lane>`,
  `embedded` (texts used from the day's express slice), `calls` (model calls). `excluded` {{list: n}} and
  `excluded_terms` {{"list:word": n}} count the code exclusions at every step. `now` holds readings that are not
  sums: `cap_left` (of `embed_daily_cap` today), `allowance` (what the pacing curve opens now), `passed_waiting`
  (passed, waiting for slice room), `undecided` (headlines still to ask).
- `shadow` (Oct 29 2026): what tidy / fusion / insert WOULD have done to the pages published or matured this run (nothing is
  changed): `stories`, `lines`, `pairs`, `outcomes` (same / covered / overlap / conflict / distinct), `folded`, `stories_with_fold`,
  `to_one_sentence`, `inspector_repeats` (what the current code counts), `weekday_errors`, `also_lines`, `also_would_insert`,
  `also_why_not`, and up to 5 `sample_folds` (kept / dropped / reader), `sample_would_fold` (folds the code proposed that the reader did not confirm),
  `sample_overlaps`, `sample_inserted` (with the story's headline, lead and the line it would sit next to) to READ. Oct 30 2026: a fold
  needs the local reader to say the kept line holds all the dropped line says (`reader` true/false, `unverified`, `reader_refused`,
  `would_fold` = folded + both), a line partly in another script is never judged, an inserted line must also fit the story's time
  and not repeat another inserted line; `seconds` is what the shadow step cost. Any sampled fold or insertion that is
  not right is a false positive: the systems stay off until a day of samples has none.
- `problems`: the run's health problems and failed steps.

## Reading it
- Is embedding really the bottleneck? Compare `used_today` at day's end with 3,000, and `waiting_after` at the
  last runs of the day: articles still waiting then never got a vector.
- Which outlets are worth their texts? `outlets` yield per outlet, over days.
- Is the express slice (`embed_daily_cap`, config/express.yaml) right? `express.embedded` per day against
  `used_today`, and the yield of express articles once recorded.
"""


def write_readme(directory: pathlib.Path) -> None:
    path = directory / "README.md"
    if not path.exists() or path.read_text(encoding="utf-8") != README:
        path.write_text(README, encoding="utf-8")


def write_all(directory: pathlib.Path, entry: dict | None, now: dt.datetime | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if entry is not None:
        append(directory, entry)
    prune(directory, now)
    write_readme(directory)
    (directory / "LEDGER.md").write_text(render(read_entries(directory, 8, now), now), encoding="utf-8")


# --- reading the database (thin; tested through the pure functions above) -----------------------------------------

def _outlet_table(store) -> dict[str, list[int]]:
    """{outlet: [articles in the window, embedded, in a 3+ independent-outlet story]} (one light query: no text, no vector)."""
    from sqlalchemy import select
    from .config import SETTINGS
    from .db import articles, utcnow
    from .wire import independence_groups, independent
    since = utcnow() - dt.timedelta(hours=SETTINGS.story_window_hours)
    rows = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.wire_group,
                             articles.c.story_id, articles.c.embedding.is_not(None).label("emb"))
                      .where(articles.c.published_at >= since, articles.c.text.is_not(None)))
    by_story: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if r["story_id"] is not None:
            by_story[r["story_id"]].append(r)
    big = {sid for sid, m in by_story.items() if len(m) >= 3 and len(independent(independence_groups(m))) >= 3}
    out: dict[str, list[int]] = {}
    for r in rows:
        o = r["outlet"] or "?"
        t = out.setdefault(o, [0, 0, 0])
        t[0] += 1
        t[1] += bool(r["emb"])
        t[2] += bool(r["emb"]) and r["story_id"] in big
    return out


def _intake(store, since: dt.datetime) -> dict:
    from sqlalchemy import func, select
    from .db import articles
    rows = store.rows(select(articles.c.outlet, func.count().label("n")).where(articles.c.fetched_at >= since)
                      .group_by(articles.c.outlet))
    return {"by_outlet": {r["outlet"] or "?": int(r["n"]) for r in rows}}


def _embed_used(store, day: str) -> dict | None:
    """Embedding texts used on the quota day: the total and per Gemini key (usage keys are the model id for key 1,
    `<id>@k2`, `<id>@k3` for the others)."""
    try:
        usage = store.quota_load(day)
    except Exception:  # noqa: BLE001
        return None
    by_key: dict[str, int] = {}
    for model, v in (usage or {}).items():
        if "embedding" in model:
            k = model.split("@", 1)[1] if "@" in model else "k1"
            by_key[k] = by_key.get(k, 0) + int(v[0] or 0)
    return {"total": sum(by_key.values()), "by_key": by_key}


def merge_desk_reports(reports: list[dict]) -> dict | None:
    """One desk record for a job. Since Oct 29 2026 the desk runs twice in a job (before and after the pipeline): the first
    report gives the state at the start (seats, ready, already this hour), and what was written, tried or skipped is the
    sum of both."""
    reports = [r for r in reports if r]
    if not reports:
        return None
    out = dict(reports[0])
    out["runs"] = len(reports)
    # each run apart (owner, Oct 30 2026): its mode (first / fill), the minutes the site had gone without an article when it
    # began, what it published and how long it took; the fill run's own record says which story, how big, how many tries
    out["run_log"] = [{"mode": r.get("mode", "first"), "gap_minutes": r.get("gap_minutes"),
                       "published": len(r.get("published") or []), "seconds": r.get("seconds")} for r in reports]
    for r in reports:
        if r.get("fill"):
            out["fill"] = r["fill"]
    secs = [r.get("seconds") for r in reports if isinstance(r.get("seconds"), (int, float))]
    if secs:
        out["seconds"] = int(sum(secs))
    for r in reports[1:]:
        for key in ("published", "express"):
            if r.get(key):
                out[key] = list(out.get(key) or []) + list(r[key])
        if "tried" in r:
            out["tried"] = int(out.get("tried") or 0) + int(r["tried"] or 0)
        for key in ("skipped", "short"):
            if isinstance(r.get(key), dict):
                merged = dict(out.get(key) or {})
                for k, v in r[key].items():
                    merged[k] = merged[k] + v if isinstance(v, int) and isinstance(merged.get(k), int) else v
                out[key] = merged
        if isinstance(r.get("beat_seat"), list):
            out["beat_seat"] = (out["beat_seat"] if isinstance(out.get("beat_seat"), list) else []) + r["beat_seat"]
    return out


def rhythm_from(events: list[tuple[dt.datetime, int]], job_start: dt.datetime | None, now: dt.datetime) -> dict:
    """How even the publishing is (owner, Oct 29 2026: the goal is consistency, then more of it). `events` are the desk runs that
    wrote something: (when its record was made, articles), UTC. `hours_24h` are the 24 completed clock hours before `now`, oldest
    first; a good system has no empty hour and little spread. Plain data, no database."""
    top = now.replace(minute=0, second=0, microsecond=0)
    hours, this_hour = [0] * 24, 0
    for at, n in events:
        k = int((top - at.replace(minute=0, second=0, microsecond=0)).total_seconds() // 3600)
        if k == 0:
            this_hour += n
        elif 1 <= k <= 24:
            hours[24 - k] += n
    mean = sum(hours) / 24
    times = sorted(at for at, n in events if n > 0 and at > now - dt.timedelta(hours=24))
    since_last = round((now - times[-1]).total_seconds() / 60) if times else None
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])] + ([since_last] if since_last is not None else [])
    first = next((round((at - job_start).total_seconds() / 60) for at, n in sorted(events) if job_start and n > 0 and at >= job_start), None)
    return {"hours_24h": hours, "this_hour": this_hour, "hours_with_article": sum(1 for h in hours if h), "empty_hours": sum(1 for h in hours if not h),
            "mean_per_hour": round(mean, 2), "sd_per_hour": round((sum((h - mean) ** 2 for h in hours) / 24) ** 0.5, 2),
            "longest_gap_min": round(max(gaps)) if gaps else 1440, "since_last_min": since_last, "first_in_job_min": first}


def _desk_events(store, since: dt.datetime) -> list[tuple[dt.datetime, int]]:
    from sqlalchemy import select
    from .db import diagnostics
    rows = store.rows(select(diagnostics.c.created_at, diagnostics.c.report)
                      .where(diagnostics.c.kind == "desk", diagnostics.c.created_at >= since).order_by(diagnostics.c.created_at.asc()))
    out = []
    for r in rows:
        pub = (r.get("report") or {}).get("published")
        if isinstance(pub, list) and pub and r.get("created_at"):
            out.append((r["created_at"], len(pub)))
    return out


def _desk_report(store, since: dt.datetime) -> dict | None:
    from sqlalchemy import select
    from .db import diagnostics
    rows = store.rows(select(diagnostics.c.report).where(diagnostics.c.kind == "desk", diagnostics.c.created_at >= since)
                      .order_by(diagnostics.c.created_at.asc()))
    return merge_desk_reports([r.get("report") for r in rows])


SAMPLES = 5


def _cut(t, n=280):
    t = t or ""
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def shadow_from_pages(pages: dict, ref=None, reader=None) -> dict:
    """What the shadow systems (tidy, fusion, insert; owner Oct 29 2026: nothing of them touches an article yet) would have done
    to these finished pages {story id: {"headline", "paragraphs": [[line]], "also": [...], "lead": [ids]}}. Plain data in, plain
    data out, no model, no quota. Samples are kept so a later session can READ the decisions: any fold or placed line that is not
    right is a false positive, and the adoption bar is none."""
    import time as _time
    from .tools import insert_shadow, tidy_shadow
    t0 = _time.time()
    if reader is None:                                  # the local entailment reader (no quota); without it nothing is verified
        try:
            from . import nli
            reader = (lambda pairs: nli.covers(pairs)) if nli.available() else False
        except Exception:  # noqa: BLE001
            reader = False
    paras = {sid: [[dict(x) for x in para if (x.get("text") or "").strip()] for para in (p.get("paragraphs") or [])] for sid, p in pages.items()}
    protect = {sid: {int(i) for i in (p.get("lead") or []) if isinstance(i, int)} for sid, p in pages.items()}
    t = tidy_shadow.run(paras, protect, nli_fn=reader or None)
    i = insert_shadow.run({sid: {"headline": p.get("headline"), "paragraphs": paras[sid], "also": p.get("also") or []} for sid, p in pages.items()}, ref=ref)
    head = {str(sid): p.get("headline") for sid, p in pages.items()}
    side = lambda r: {"story": r["story"], "headline": _cut(head.get(str(r["story"])), 120),    # noqa: E731
                      "kept": _cut(r["b_text"] if r["drop"] == "a" else r["a_text"]), "dropped": _cut(r["a_text"] if r["drop"] == "a" else r["b_text"]),
                      "reader": r.get("reader"), "why": r.get("why")}
    return {"stories": t["stories"], "lines": t["lines"], "pairs": t["pairs"], "outcomes": t["outcomes"], "folded": t["folded"],
            "stories_with_fold": t["stories_with_fold"], "stories_with_overlap": t["stories_with_overlap"],
            "to_one_sentence": t["to_one_sentence"], "inspector_repeats": t["inspector_repeats"], "weekday_errors": t["weekday_errors"],
            "also_lines": i["lines"], "also_would_insert": i["inserted"], "also_why_not": i["why_not"],
            "reader": bool(reader), "unverified": t["unverified"], "reader_refused": t["reader_refused"],
            "would_fold": t["folded"] + t["unverified"] + t["reader_refused"], "seconds": round(_time.time() - t0, 1),
            "sample_folds": [side(f) for f in t["folds"][:SAMPLES]],
            "sample_would_fold": [side(f) for f in t["would_fold_not_verified"][:SAMPLES]],
            "sample_overlaps": [{"a": f.get("a_text"), "b": f.get("b_text")} for f in t["candidates"][:SAMPLES]],
            "sample_inserted": [{"story": x["story"], "headline": _cut(x.get("headline"), 120), "lead": _cut(x.get("lead"), 240),
                                 "near": _cut(x.get("near")), "shared": x.get("shared"), "text": _cut(x["text"])} for x in i["placed"][:SAMPLES]]}


def _shadow(store, since: dt.datetime) -> dict | None:
    """The shadow systems on the articles published or matured since `since` (at most 12). Never raises; a failure is recorded."""
    try:
        from sqlalchemy import text as sql
        pages = {}
        with store.engine.begin() as c:
            for sid, pay in c.execute(sql("select story_id, payload_en from published where updated_at >= :t order by updated_at desc limit 12"),
                                      {"t": since}):
                if pay:
                    pages[str(sid)] = {"headline": pay.get("headline"), "paragraphs": (pay.get("narrative") or {}).get("paragraphs") or [],
                                       "also": pay.get("also") or [], "lead": pay.get("lead") or []}
        return shadow_from_pages(pages, ref=dt.datetime.now(dt.timezone.utc).date()) if pages else None
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def record(store, directory: pathlib.Path) -> dict | None:
    from sqlalchemy import select
    from .db import runs
    run = store.one(select(runs).where(runs.c.finished_at.is_not(None)).order_by(runs.c.id.desc()).limit(1))
    if not run:
        log.info("ledger: no finished run yet")
        write_all(directory, None)
        return None
    started = run["started_at"]
    try:
        from . import desk
        ready_end = len(desk.ready(store))
    except Exception as e:  # noqa: BLE001 - the ledger never stops the hour
        log.warning("ledger: ready count failed: %s", str(e)[:150])
        ready_end = None
    entry = build_entry(run, _desk_report(store, started - dt.timedelta(minutes=5)), _outlet_table(store),
                        _intake(store, started - dt.timedelta(minutes=1)), _embed_used(store, pt_day(started)), ready_end)
    try:
        from .db import utcnow
        now = utcnow()
        entry["rhythm"] = rhythm_from(_desk_events(store, now - dt.timedelta(hours=26)), started, now)
    except Exception as e:  # noqa: BLE001
        log.warning("ledger: rhythm failed: %s", str(e)[:150])
    shadow = _shadow(store, started - dt.timedelta(minutes=5))
    if shadow:
        entry["shadow"] = shadow
    write_all(directory, entry)
    return entry


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default=str(DEFAULT_DIR))
    p.add_argument("--rebuild", action="store_true", help="render LEDGER.md again from the stored runs; no database")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    directory = pathlib.Path(a.dir)
    if a.rebuild:
        write_all(directory, None)
        return
    from .config import database_url
    from .db import Store
    store = Store(database_url())
    store.init()
    entry = record(store, directory)
    if entry:
        log.info("ledger: run %s recorded (%s)", entry["run"], entry["ist"])


if __name__ == "__main__":
    main()

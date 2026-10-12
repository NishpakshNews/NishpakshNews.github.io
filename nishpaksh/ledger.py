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
                 "settled_broad", "left_for_next_run", "claims_checked", "colours_matured", "live_pages",
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

def build_entry(run: dict, desk: dict | None, outlets: dict | None, intake: dict | None, embed_used: int | None) -> dict:
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
    if desk:
        entry["desk"] = {k: desk[k] for k in ("published", "seats", "ready", "ready_beat", "tried", "skipped",
                                              "beat_seat", "already_this_hour", "short") if k in desk}
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
                                  "dominates is the dial to look at):", "reason")):
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
  `ready_beat`, `skipped`, `beat_seat`, `short`.
- `express`: the express lane's funnel for the run (appears when the lane runs). Counts per step, in order:
  `taken` (new links from express feeds that were downloaded), `intake_excluded` (kept out by code before the page was
  fetched) and `intake_over_cap`, `unreadable` (page not fully readable: option B), `asked` (headlines the model
  answered, each asked twice), `not_lane` (no lane, or the two answers differed), `passed` and `passed_<lane>`,
  `embedded` (texts used from the day's express slice), `calls` (model calls). `excluded` {{list: n}} and
  `excluded_terms` {{"list:word": n}} count the code exclusions at every step. `now` holds readings that are not
  sums: `cap_left` (of `embed_daily_cap` today), `allowance` (what the pacing curve opens now), `passed_waiting`
  (passed, waiting for slice room), `undecided` (headlines still to ask).
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


def _desk_report(store, since: dt.datetime) -> dict | None:
    from sqlalchemy import select
    from .db import diagnostics
    row = store.one(select(diagnostics.c.report).where(diagnostics.c.kind == "desk", diagnostics.c.created_at >= since)
                    .order_by(diagnostics.c.created_at.desc()).limit(1))
    return (row or {}).get("report")


def record(store, directory: pathlib.Path) -> dict | None:
    from sqlalchemy import select
    from .db import runs
    run = store.one(select(runs).where(runs.c.finished_at.is_not(None)).order_by(runs.c.id.desc()).limit(1))
    if not run:
        log.info("ledger: no finished run yet")
        write_all(directory, None)
        return None
    started = run["started_at"]
    entry = build_entry(run, _desk_report(store, started - dt.timedelta(minutes=5)), _outlet_table(store),
                        _intake(store, started - dt.timedelta(minutes=1)), _embed_used(store, pt_day(started)))
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

"""The express lane (owner, Oct 12 2026): a short positive list of topics whose stories may be written from ONE
independent outlet's readable page. Config: `config/express.yaml`. Everything else keeps the strict rule.

Built in parts (see CLAUDE.md, "Express lane"):
  1. this module's door, in code: the lanes, the feeds that carry a lane, and `excluded_many` (a headline
     that a concern definition fits, risk.py, never enters the lane, whatever the lane model says); the ledger (ledger.py);
  2. (built) the express intake (`take_intake`: code exclusions before a page is fetched, its own caps), the headline
     question to a small model (`gate`: lane or not, asked twice, order swapped, unsure = no; the verdict is kept in
     `articles.extraction["express"]`, so a headline is asked about once) and the embedding slice
     (`embed_daily_cap`, booked in quota_usage as "express:embed"), so an express article is embedded only if it passed;
  3. (built) reading and qualifying an express story from one independent outlet with a named origin; the one-hour wait;
     the dispute check when a second outlet turns up;
  4. the seats (the beat seat shared with Domains/Sport) and the record in CLAUDE.md.

Nothing here touches a colour rule: an express story has one independent outlet, so it is purple ("one outlet
only") and can never be green (green needs 3 outlets, 2 origins and 6 hours).

Model and database are used only by `lane_feeds`, `gate`, `embed_allowance` and `book_embedded`; the door itself
(`excluded_many`) uses the local entailment model (nli.py, no quota) and the URL pieces, not word lists.
"""
from __future__ import annotations

import datetime as dt
import functools
import logging
import time

from . import risk

log = logging.getLogger(__name__)

VERDICT_VERSION = 1
# The funnel of the run, plain numbers (run.py saves it as stats["express"], ledger.py prints it). Keys that are
# numbers are summed over runs; `excluded` {list: n} and `excluded_terms` {"list:term": n} count code exclusions;
# `now` holds readings that are not sums (cap left, passed and waiting).
STATS: dict = {}

@functools.lru_cache(maxsize=1)
def cfg() -> dict:
    """The parsed config/express.yaml (cached: read once per process). A missing or broken file switches
    the lane off, never the pipeline."""
    try:
        from .config import load_yaml
        data = load_yaml("express.yaml") or {}
    except Exception:  # noqa: BLE001
        return {"enabled": False, "lanes": {}}
    return data


def reload() -> None:
    cfg.cache_clear()
    _urls.cache_clear()
    _tagged.cache_clear()


def enabled() -> bool:
    c = cfg()
    return bool(c.get("enabled")) and bool(c.get("lanes"))


def lanes() -> dict[str, dict]:
    return dict(cfg().get("lanes") or {})


def setting(name: str, default):
    return cfg().get(name, default)


def lane_feeds(store) -> dict[int, str]:
    """{feed id: lane} for the feeds tagged `lane:` in feeds.yaml (matched by URL, like `beat:`; no schema change)."""
    from .db import feeds, select
    names = lanes()
    tagged = {u: l for u, l in _tagged().items() if l in names}
    if not tagged:
        return {}
    return {r["id"]: tagged[r["url"]] for r in store.rows(select(feeds.c.id, feeds.c.url)) if r["url"] in tagged}


# --- the exclusion check -----------------------------------------------------------------------------------------
# Owner, Oct 27 2026: no word lists. What a headline is about is read by the local entailment model against the
# definition sentences of `concerns:` in express.yaml (risk.py). Only the URL check stays: a path such as /opinion/ is
# the page's structure, not language.

UNREAD = risk.UNREAD       # the headline could not be read by the model: undecided, asked again next run


@functools.lru_cache(maxsize=1)
def _urls() -> list[str]:
    return [str(u).lower() for u in (cfg().get("exclude_url") or [])]


def excluded_many(items: list[tuple[str, str, str, str | None]]) -> list:
    """Why each report must stay out of the express lane: [(title, lead, url, lane)] -> one entry per item, a reason
    "concern:definition" (e.g. "harm:crime", "url:opinion"), None (it may enter), or UNREAD (the model could not read it:
    the caller leaves it undecided and asks again on the next run, it is never passed).

    Applied before any other model sees the headline. With lane None only the concerns that apply to every lane are used
    (the cheap first look); with a lane, that lane's own concerns are added. A match in the headline or in the opening
    words counts. Local model, no quota; the seconds and pairs are counted in STATS."""
    out: list = [None] * len(items)
    todo: list[int] = []
    urls = _urls()
    for i, (_title, _lead, url, _lane) in enumerate(items):
        u = (url or "").lower()
        piece = next((p for p in urls if p in u), None)
        if piece:
            out[i] = f"url:{piece.strip('/')}"
        else:
            todo.append(i)
    if todo:
        c = cfg()
        started = time.monotonic()
        got = risk.reasons([risk.text_of(items[i][0], items[i][1]) for i in todo], [items[i][3] for i in todo],
                           c.get("concerns") or {}, c.get("apply") or {}, float(c.get("concern_min", risk.DEFAULT_MIN)))
        for i, r in zip(todo, got):
            out[i] = r
        bump("risk_texts", len(todo))
        bump("risk_unread", sum(1 for r in got if r is UNREAD))
        if not _QUIET[0]:
            for k, v in risk.STATS.items():
                STATS[f"risk_{k}"] = v
        STATS["risk_seconds"] = round(STATS.get("risk_seconds", 0.0) + time.monotonic() - started, 2) if not _QUIET[0] else STATS.get("risk_seconds", 0.0)
    return out


def excluded(title: str, lead: str = "", url: str = "", lane: str | None = None):
    """`excluded_many` for one report (tests, the replay tool)."""
    return excluded_many([(title, lead, url, lane)])[0]


def reason_group(reason: str | None) -> str | None:
    """The list a reason came from (\"harm:arrested\" -> \"harm\"), for the ledger's counts."""
    return reason.split(":", 1)[0] if reason else None


# --- the funnel counters -----------------------------------------------------------------------------------------

def reset() -> None:
    """A new run (ingest calls it first)."""
    STATS.clear()
    risk.set_budget(float(setting("risk_seconds_per_run", 300)))


CACHE_NAME = "risk_cache"


def load_cache(store) -> None:
    """The scores of earlier runs (risk.py): a headline is read by the model once, not every hour."""
    try:
        from sqlalchemy import select
        from .db import model_state
        row = store.one(select(model_state.c.data).where(model_state.c.name == CACHE_NAME))
        risk.load_cache(row.get("data") if row else None)
    except Exception as e:  # noqa: BLE001 - no cache only costs time
        log.info("risk cache not loaded (%s)", str(e)[:80])


def save_cache(store) -> None:
    try:
        from sqlalchemy import delete, insert
        from .db import model_state
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        with store.route(insert(model_state)).engine.begin() as c:
            c.execute(delete(model_state).where(model_state.c.name == CACHE_NAME))
            c.execute(insert(model_state).values(name=CACHE_NAME, data=risk.dump_cache(), updated_at=now))
    except Exception as e:  # noqa: BLE001
        log.info("risk cache not saved (%s)", str(e)[:80])


_QUIET = [0]     # >0 while `still_holds` re-checks a story: the funnel counts each story once, in the run's own check


def bump(key: str, n: int = 1) -> None:
    if _QUIET[0]:
        return
    STATS[key] = STATS.get(key, 0) + n


def _count_excluded(reason: str) -> None:
    ex = STATS.setdefault("excluded", {})
    g = reason_group(reason) or "?"
    ex[g] = ex.get(g, 0) + 1
    terms = STATS.setdefault("excluded_terms", {})
    terms[reason] = terms.get(reason, 0) + 1


def _now(key: str, value) -> None:
    STATS.setdefault("now", {})[key] = value


# --- intake: which feeds, and what is taken from them -------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _tagged() -> dict[str, str]:
    """{feed url: lane} for every feed carrying a `lane:` tag in feeds.yaml (cached)."""
    from .config import load_yaml
    return {f["url"]: f["lane"] for f in load_yaml("feeds.yaml").get("feeds") or [] if f.get("lane")}


def lane_of_url(url: str) -> str | None:
    """The lane an enabled express feed carries, else None (an untagged feed, or a lane the config does not have)."""
    lane = _tagged().get(url)
    return lane if lane in lanes() else None


def skip_feed(url: str) -> bool:
    """A feed tagged for a lane while the lane is off (or the lane is unknown): not read at all, so no
    section feed ever reaches the strict politics grouping by accident."""
    return url in _tagged() and not (enabled() and lane_of_url(url))


def take_intake(todo: list[tuple[dict, dict]]) -> tuple[list[tuple[dict, dict]], list[tuple[dict, dict]]]:
    """Split ingest's new links (feed row, entry) into (the others, the express links to fetch).

    The express links get their own caps (`intake_per_feed`, `intake_per_run`: the main feeds keep their 400), and
    the code exclusions run on the headline and the feed's blurb BEFORE the page is fetched: a link that would
    be kept out anyway costs no download and is never stored. Newest first, as `todo` already is."""
    if not enabled():
        return todo, []
    rest, mine = [], []
    for f, en in todo:
        (mine if lane_of_url(f["url"]) else rest).append((f, en))
    per_feed: dict[int, int] = {}
    keep: list[tuple[dict, dict]] = []
    cap_feed = int(setting("intake_per_feed", 12))
    cap_run = int(setting("intake_per_run", 80))
    verdicts = excluded_many([(en.get("title") or "", en.get("summary") or "", en.get("url") or "", lane_of_url(f["url"]))
                              for f, en in mine])
    for (f, en), why in zip(mine, verdicts):
        if why is UNREAD:
            bump("intake_unread")          # the model could not read it: the page is fetched, the gate judges it (and holds it if it still cannot)
        elif why:
            _count_excluded(why)
            bump("intake_excluded")
            continue
        if per_feed.get(f["id"], 0) >= cap_feed or len(keep) >= cap_run:
            bump("intake_over_cap")
            continue
        per_feed[f["id"]] = per_feed.get(f["id"], 0) + 1
        keep.append((f, en))
    bump("taken", len(keep))
    return rest, keep


# --- the headline question -------------------------------------------------------------------------------------

LANE_PROMPT = """Below are news headlines. For each one, say which topic it belongs to.

{lanes}
"none" - everything else: politics, government, courts, crime, accidents, deaths, disputes and accusations, share
         prices and the economy, health, opinion, explainers, lists, rumours.

Examples:
{examples}
If you are not sure, answer "none".

{headlines}

Reply with JSON only: {{"results": [{{"n": 1, "lane": "sport"}}, {{"n": 2, "lane": "none"}}, ...]}}"""


def _prompt(titles: list[str]) -> str:
    ls = "\n".join(f'"{k}" - {v.get("describe", "")}' for k, v in lanes().items())
    ex = "\n".join(f"- {e}" for e in setting("filter_examples", []) or [])
    body = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return LANE_PROMPT.format(lanes=ls, examples=ex, headlines=body)


def _ask(router, items: list[dict]) -> dict[int, str]:
    """One model question for a batch: {article id: lane or "none"} for the headlines the model answered. A line
    the model skipped is missing (left undecided); an answer naming no lane is "none" (unsure = not express). A
    model without quota, or a failed call, answers nothing: the batch waits for the next run."""
    from .router import QuotaExhausted
    out: dict[int, str] = {}
    titles = [(a.get("title") or "").strip().replace("\n", " ")[:220] for a in items]
    try:
        res = router.call("page", _prompt(titles), json_out=True, max_output_tokens=800)
    except QuotaExhausted:
        log.info("express: no quota for the headline question")
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("express: headline question failed: %s", str(e)[:200])
        return out
    bump("calls")
    names = set(lanes())
    for item in (res.data or {}).get("results", []) if isinstance(res.data, dict) else []:
        try:
            n = int(item["n"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= n < len(items):
            lane = str(item.get("lane") or "").strip().lower()
            out[items[n]["id"]] = lane if lane in names else "none"
    return out


def lanes_agreed(router, items: list[dict], batch: int) -> dict[int, str]:
    """{article id: lane} for the headlines that got a final answer. Asked twice: the second time only for headlines
    that got a lane, in REVERSE order (and renumbered). Both answers must name the same lane; unsure, two different
    lanes = "none". A headline the model did not answer (a failed call, no quota, a skipped line) is left out, so the
    caller keeps it undecided and asks again next run."""
    first: dict[int, str] = {}
    for i in range(0, len(items), batch):
        first.update(_ask(router, items[i:i + batch]))
    named = [a for a in items if first.get(a["id"], "none") != "none"]
    second: dict[int, str] = {}
    rev = named[::-1]
    for i in range(0, len(rev), batch):
        second.update(_ask(router, rev[i:i + batch]))
    out: dict[int, str] = {}
    for a in items:
        lane = first.get(a["id"])
        if lane is None:
            continue
        if lane == "none":
            out[a["id"]] = "none"
        elif a["id"] in second:
            out[a["id"]] = lane if second[a["id"]] == lane else "none"
    return out


# --- the second question: does it matter beyond its own corner? (owner, Oct 13 2026) -----------------------------------
#
# The lane says WHAT a story is about; this says whether a reader of a national news app needs it. The owner read the first
# batch and found express stories "day to day, unimportant": a foreign player's knee injury, a squad list for a series
# India is not in, a film's cast addition, a comedian's new show, an actor's relationship. What he wanted: India or an
# Indian is the subject ("india"), or the sport, industry or event AS A WHOLE moves, or a global figure's national
# sensation ("world"). Everything else is "none". Asked twice like the lane (second time reversed, only for headlines that
# passed), both answers must be the same class, unsure = none. Examples are the owner's own verdicts (express.yaml).

SIG_PROMPT = """You choose news for Indian readers of a national news app. For each headline below (shown with its topic), decide
whether an Indian reader NEEDS to know it, by answering one of:

"india" - India, an Indian person, team, company or achievement is the main subject, and it is a real achievement,
          event or controversy (a medal, a title, an award, a record, a big deal, a public row).
"world" - the sport, industry or event AS A WHOLE moves (a rule, a tournament, a governing body's ruling, an industry-wide
          move), or something so large that people everywhere know it (a global icon retiring, a nation's sensation).
"none"  - everything else: one foreign player's or team's injury, squad, form or fixtures (unless it is against India),
          a private life, relationship or family matter, a film or show's cast, crew, signing or sequel details, a
          minor or regional celebrity, a small or little-known company or launch, a leak, a rumour, an award shortlist.

{lane_notes}
Examples (the owner's own verdicts):
{examples}
If you are not sure, answer "none".

{headlines}

Reply with JSON only: {{"results": [{{"n": 1, "class": "india"}}, {{"n": 2, "class": "none"}}, ...]}}"""

SIG_CLASSES = ("india", "world", "none")


def _sig_prompt(items: list[tuple[dict, str]]) -> str:
    notes = "\n".join(f"- {k}: {v}" for k, v in (setting("significance_lane_notes", {}) or {}).items())
    ex = "\n".join(f"- {e}" for e in setting("significance_examples", []) or [])
    body = "\n".join(f"{i + 1}. [{lane}] {(a.get('title') or '').strip().replace(chr(10), ' ')[:220]}"
                     for i, (a, lane) in enumerate(items))
    return SIG_PROMPT.format(lane_notes=("What counts, by topic:\n" + notes + "\n") if notes else "", examples=ex, headlines=body)


def _ask_sig(router, items: list[tuple[dict, str]]) -> dict[int, str]:
    """{article id: class} for the headlines the model answered (a missing line is undecided; an unknown class is none)."""
    from .router import QuotaExhausted
    out: dict[int, str] = {}
    try:
        res = router.call("page", _sig_prompt(items), json_out=True, max_output_tokens=800)
    except QuotaExhausted:
        log.info("express: no quota for the significance question")
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("express: significance question failed: %s", str(e)[:200])
        return out
    bump("sig_calls")
    for item in (res.data or {}).get("results", []) if isinstance(res.data, dict) else []:
        try:
            n = int(item["n"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= n < len(items):
            c = str(item.get("class") or "").strip().lower()
            out[items[n][0]["id"]] = c if c in SIG_CLASSES else "none"
    return out


def significance_agreed(router, items: list[tuple[dict, str]], batch: int) -> dict[int, str]:
    """{article id: "india" | "world" | "none"} for the headlines that got a final answer. Same shape as `lanes_agreed`:
    the second question only for those the first passed, in reverse order; both must give the same class."""
    first: dict[int, str] = {}
    for i in range(0, len(items), batch):
        first.update(_ask_sig(router, items[i:i + batch]))
    named = [it for it in items if first.get(it[0]["id"], "none") != "none"]
    second: dict[int, str] = {}
    rev = named[::-1]
    for i in range(0, len(rev), batch):
        second.update(_ask_sig(router, rev[i:i + batch]))
    out: dict[int, str] = {}
    for a, _lane in items:
        i = a["id"]
        if i not in first:
            continue
        if first[i] == "none":
            out[i] = "none"
        elif i in second:
            out[i] = first[i] if second[i] == first[i] else "none"
    return out


# --- the verdict, kept with the article --------------------------------------------------------------------------

def verdict_of(a: dict) -> dict | None:
    """The stored express verdict of an article (articles.extraction["express"]), or None if it has none yet."""
    ex = a.get("extraction")
    v = ex.get("express") if isinstance(ex, dict) else None
    return v if isinstance(v, dict) and v.get("v") == VERDICT_VERSION else None


def _verdict(verdict: str, lane: str | None, why: str | None, now: dt.datetime, sig: str | None = None) -> dict:
    v = {"v": VERDICT_VERSION, "verdict": verdict, "at": now.isoformat(timespec="minutes")}
    if lane:
        v["lane"] = lane
    if sig:
        v["sig"] = sig
    if why:
        v["why"] = why
    return v


def _save(store, verdicts: dict[int, dict]) -> None:
    from sqlalchemy import bindparam, update
    from .db import articles
    if not verdicts:
        return
    with store.engine.begin() as c:
        c.execute(update(articles).where(articles.c.id == bindparam("aid")).values(extraction=bindparam("x")),
                  [{"aid": i, "x": {"express": v}} for i, v in verdicts.items()])


# --- the embedding slice --------------------------------------------------------------------------------------

EMBED_KEY = "express:embed"


def used_today(store) -> int:
    from .db import quota_usage, select
    from .router import quota_day
    r = store.one(select(quota_usage.c.requests).where(quota_usage.c.model == EMBED_KEY,
                                                       quota_usage.c.day == quota_day()))
    return int((r or {}).get("requests") or 0)


def embed_allowance(store, now_pacific: dt.datetime | None = None) -> tuple[int, int]:
    """(texts an express article may be embedded with this run, left of the day's cap). The slice follows the
    same pacing curve as the other quotas (`router.pace_fraction`), so it is spread over the day, not spent at
    midnight."""
    from .router import PACIFIC, pace_fraction
    cap = int(setting("embed_daily_cap", 400))
    used = used_today(store)
    now = now_pacific or dt.datetime.now(PACIFIC)
    left = max(0, cap - used)
    return max(0, min(left, int(cap * pace_fraction(now)) - used)), left


def book_embedded(store, n: int) -> None:
    """Count express texts embedded against today's slice (also in the run's funnel)."""
    if n <= 0:
        return
    from .router import quota_day
    store.quota_add(EMBED_KEY, quota_day(), n, 0)
    bump("embedded", n)


# --- the gate in grouping ----------------------------------------------------------------------------------------

def gate(store, router, arts: list[dict], now: dt.datetime) -> tuple[set[int], set[int]]:
    """For `stories.group_stories`: (held, first) article ids among the articles of express feeds.

    Only an express-feed article that is still unread and has no vector is looked at. It is embedded only when:
      1. its page was readable (a headline-and-blurb article is never used: option B);
      2. no exclusion list matches (code, `excluded`, with its lane's own lists);
      3. the headline question named a lane twice (`lanes_agreed`), and the lane's own exclusions still pass;
      4. the day's slice has room (`embed_allowance`): `first` are the passed ones to embed ahead of the other
         articles this run, newest first; passed ones beyond the slice wait for the next run.
    Everything else is `held`: not embedded, never grouped. Each verdict is saved with the article, so a headline
    is judged once. A model without quota leaves the headlines undecided until the next run."""
    if not enabled():
        return set(), set()
    lane_of = lane_feeds(store)
    mine = sorted((a for a in arts if a.get("feed_id") in lane_of and not a.get("embedding") and not a.get("extracted_at")),
                  key=lambda a: a.get("published_at") or now, reverse=True)
    if not mine:
        return set(), set()
    held: set[int] = set()
    passed: list[dict] = []
    pending: list[tuple[dict, str]] = []
    undecided: list[dict] = []
    save: dict[int, dict] = {}
    unseen = [a for a in mine if verdict_of(a) is None and (a.get("text_source") or "full") != "summary"]
    first_look = dict(zip((a["id"] for a in unseen),
                          excluded_many([(a.get("title") or "", (a.get("text") or "")[:300], a.get("url") or "",
                                          lane_of[a["feed_id"]]) for a in unseen])))
    for a in mine:
        v = verdict_of(a)
        if v is None:
            lane = lane_of[a["feed_id"]]
            if (a.get("text_source") or "full") == "summary":
                save[a["id"]] = _verdict("no", lane, "unreadable", now)
                bump("unreadable")
                v = save[a["id"]]
            else:
                why = first_look.get(a["id"])
                if why is UNREAD:
                    bump("risk_held")        # not read by the model: nothing is saved, not embedded, looked at again next run
                    held.add(a["id"])
                    continue
                if why:
                    _count_excluded(why)
                    save[a["id"]] = _verdict("excluded", lane, why, now)
                    v = save[a["id"]]
        if v is None:
            undecided.append(a)
        elif v.get("verdict") == "yes" and (v.get("sig") or not setting("significance_enabled", True)):
            passed.append(a)
        elif v.get("verdict") in ("pending", "yes") and v.get("lane"):       # a "yes" without `sig`: asked the new question
            pending.append((a, v["lane"]))        # the lane said yes, the significance question is still to answer
        else:
            held.add(a["id"])
    # the headline question
    allowance, cap_left = embed_allowance(store)
    _now("cap_left", cap_left)
    if undecided and router is not None and cap_left > 0:
        batch = int(setting("filter_batch", 20))
        limit = batch * int(setting("filter_calls_per_run", 6))
        todo = undecided[:limit]
        got = lanes_agreed(router, todo, batch)
        named = [a for a in todo if got.get(a["id"]) not in (None, "none")]
        second_look = dict(zip((a["id"] for a in named),
                               excluded_many([(a.get("title") or "", (a.get("text") or "")[:300], a.get("url") or "", got[a["id"]])
                                              for a in named])))
        for a in todo:
            if a["id"] not in got:
                continue
            lane = got[a["id"]]
            bump("asked")
            if lane == "none":
                save[a["id"]] = _verdict("no", None, "not_lane", now)
                bump("not_lane")
                held.add(a["id"])
                continue
            why = second_look.get(a["id"])
            if why is UNREAD:
                bump("risk_held")            # the lane is named but the lane's own concerns could not be read: asked again next run
                held.add(a["id"])
                continue
            if why:
                _count_excluded(why)
                save[a["id"]] = _verdict("excluded", lane, why, now)
                held.add(a["id"])
                continue
            save[a["id"]] = _verdict("pending", lane, None, now)
            bump("lane_ok")
            pending.append((a, lane))
        done = {a["id"] for a in todo if a["id"] in got}
        undecided = [a for a in undecided if a["id"] not in done]
    if pending and router is not None and cap_left > 0:
        if not setting("significance_enabled", True):
            got_sig = {a["id"]: "world" for a, _ in pending}
        else:
            batch = int(setting("filter_batch", 20))
            todo_sig = pending[:batch * int(setting("significance_calls_per_run", 6))]
            got_sig = significance_agreed(router, todo_sig, batch)
        for a, lane in pending:
            cls = got_sig.get(a["id"])
            if cls is None:
                continue                               # no answer: asked again next run
            if cls == "none":
                save[a["id"]] = _verdict("no", lane, "not_significant", now)
                bump("not_significant")
                bump(f"not_significant_{lane}")
                held.add(a["id"])
            else:
                save[a["id"]] = _verdict("yes", lane, None, now, sig=cls)
                bump("passed")
                bump(f"passed_{lane}")
                bump(f"sig_{cls}")
                passed.append(a)
        decided = {a["id"] for a, _ in pending if a["id"] in got_sig}
        pending = [(a, l) for a, l in pending if a["id"] not in decided]
    held |= {a["id"] for a, _ in pending}              # lane agreed, significance unanswered: not embedded yet
    _now("sig_waiting", len(pending))
    held |= {a["id"] for a in undecided}               # not yet judged: not embedded
    passed.sort(key=lambda a: a.get("published_at") or now, reverse=True)
    first = {a["id"] for a in passed[:allowance]}
    held |= {a["id"] for a in passed[allowance:]}      # passed, the slice is full for now
    _now("passed_waiting", len(passed) - len(first))
    _now("undecided", len(undecided))
    _now("allowance", allowance)
    _save(store, save)
    return held, first


# --- Part 3: an express story, read from one independent outlet ----------------------------------------------------
#
# A story is express when: one lane's headline question said yes for a member (above), no member is excluded or
# off-lane, and fewer than 3 independent outlets cover it (3 or more is the normal route). It is read with its own
# small cap (`reads_per_run` NEW stories a run; stories already begun are always finished). It qualifies when:
#   - every independent outlet whose page is readable has been read (a second outlet is never ignored),
#   - the statements of what happened (kind "event") name their origin: the company, the league, an official; one
#     "sources said" event, or one event credited to another media house, and it does not qualify (unsure = no),
#   - with two outlets, nothing is disputed between them (a conflict or a denial).
# Sport results may stand on the outlet's own voice (`own_voice_lanes`): a match result is the reporter's own
# observation. The reason a story did not qualify is counted in STATS["story_out"], for the ledger.

ANON, OWN, NAMED, MEDIA, AGENCY = "anon", "own", "named", "media", "agency"


def _count(group: str, key: str) -> None:
    if _QUIET[0]:
        return
    g = STATS.setdefault(group, {})
    g[key] = g.get(key, 0) + 1


def names_a_media_house(raw: str) -> bool:
    """The attribution is another media house (not an origin: "Bloomberg", "a Bloomberg report", "according to Mint").
    The registry decides, the one the pipeline already keeps (ownership.yaml + feeds.yaml: `ownership.is_known_outlet`), not a
    list of words kept here: the whole attribution is an outlet, or an organisation the entity reader finds in it is one."""
    from .ownership import is_known_outlet
    if is_known_outlet(raw):
        return True
    try:
        from . import nlp
        return any(is_known_outlet(e.text) for e in nlp.ents(raw))
    except Exception:  # noqa: BLE001 - no reader: only a whole-string outlet name counts (as above)
        return False


def attribution_kind(raw: str | None) -> str:
    """How a statement's source reads: own voice, anonymous, an agency, another media house (not an origin), or named."""
    from .origins import ANON_WORDS, OWN_WORDS, _norm
    try:
        from .origins import AGENCIES
    except ImportError:  # noqa: BLE001
        AGENCIES = set()
    n = _norm(raw or "")
    if n in OWN_WORDS:
        return OWN
    if n in ANON_WORDS or n.startswith(("unnamed", "anonymous", "sources ")):
        return ANON
    if n in AGENCIES:
        return AGENCY
    if names_a_media_house(raw or ""):
        return MEDIA
    return NAMED


def origin_verdict(claims: list[dict], lane: str) -> tuple[bool, str]:
    """(named enough, why). `claims` are the story's statement rows ({kind, stance, attributed_to}). Only statements
    of what happened count (kind "event", stance asserts or attributes). Plain code, no model."""
    events = [c for c in claims if c.get("kind") == "event" and c.get("stance") in ("asserts", "attributes")]
    if not events:
        return False, "no_event"
    kinds = [attribution_kind(c.get("attributed_to")) for c in events]
    if ANON in kinds:
        return False, "anonymous_source"
    if MEDIA in kinds:
        return False, "other_media_source"
    if AGENCY in kinds:
        return False, "agency_source"
    if NAMED in kinds:
        return True, "named"
    if lane in (setting("own_voice_lanes", ["sport"]) or []):
        return True, "own_voice"
    return False, "not_named"


def story_lane(members: list[dict], lane_of: dict[int, str] | None = None) -> tuple[str | None, str | None]:
    """(lane, None) when the members make an express story, else (None, why). A member judged excluded or off-lane,
    or a member any exclusion list matches, keeps the whole story out; two lanes in one story is unsure = out."""
    lanes_yes: set[str] = set()
    for a in members:
        v = verdict_of(a)
        if not v:
            continue
        if v.get("verdict") == "yes" and v.get("lane"):
            # a "yes" from before the significance question (no `sig`) does not count: it never met the bar
            if v.get("sig") or not setting("significance_enabled", True):
                lanes_yes.add(v["lane"])
        elif v.get("verdict") == "excluded" or v.get("why") in ("not_lane", "not_significant"):
            return None, "member_" + ("excluded" if v.get("verdict") == "excluded" else v["why"])
    if not lanes_yes:
        return None, "no_lane"
    if len(lanes_yes) > 1:
        return None, "two_lanes"
    lane = next(iter(lanes_yes))
    seen = excluded_many([(a.get("title") or "", "", a.get("url") or "", lane) for a in members])
    if any(w and w is not UNREAD for w in seen):
        return None, "member_excluded"
    if any(w is UNREAD for w in seen):
        return None, "risk_unread"        # a headline the model could not read: the story waits (never passed on a guess)
    return lane, None


def story_sig(members: list[dict]) -> str:
    """"india" when any passed member was judged an India story, else "world" (a story from before the question counts as "world")."""
    sigs = {(verdict_of(a) or {}).get("sig") for a in members if (verdict_of(a) or {}).get("verdict") == "yes"}
    return "india" if "india" in sigs else "world"


def order() -> list[str]:
    """The strict order the desk and the reader of stories follow, best first (express.yaml `order`): express lanes
    and the normal "domains" beat in one list. A name not listed ranks last."""
    return [str(x) for x in (setting("order", ["companies", "tech", "domains", "sport", "entertainment"]) or [])]


def tier(express_lane: str | None, desk: str | None) -> int:
    """0 = first. An express story ranks by its lane; any other beat story by its desk (domains, sport). The normal
    Sport desk and express sport share one place (owner, Oct 13 2026: merged)."""
    o = order()
    key = express_lane or desk
    return o.index(key) if key in o else len(o)


def _readable(a: dict) -> bool:
    return (a.get("text_source") or "full") != "summary" and a.get("has_text", True)


def outlet_key(a: dict) -> str:
    """One OUTLET (owner, Oct 16 2026: an express story needs two outlets it could read, independent or not); the same
    wire copy carried by two outlets is one text, so it counts once."""
    return f"wire:{a['wire_group']}" if a.get("wire_group") else "outlet:" + (a.get("outlet") or "").strip().lower()


LANE_MEMBER_DAYS = 7      # how far back a lane-feed member makes a story an express one (its freshness is the newest report's)


def min_outlets() -> int:
    """Outlets with a readable page an express story needs before it is read and written (config `min_outlets`)."""
    return int(setting("min_outlets", 2))


def candidates(store, now: dt.datetime | None = None) -> dict[int, dict]:
    """{story id: {"lane", "groups", "read"}} for stories that are express now: unpublished, fresh, a lane, one or
    two independent readable outlets. `read` is True once an article of the story has been read."""
    from sqlalchemy import func, select
    from .config import SETTINGS
    from .db import articles
    from .editions import frozen_ids
    from .wire import independence_groups, independent
    now = now or _now_utc()
    lane_of = lane_feeds(store)
    if not enabled() or not lane_of:
        return {}
    since = now - dt.timedelta(hours=SETTINGS.stale_after_hours)
    # a story with a lane-feed member (last LANE_MEMBER_DAYS) that has ANY fresh report: a second outlet from a main
    # feed (story 23995: The Hindu's lane article of Oct 13, Aaj Tak's home-feed report of Oct 16) makes the story
    # current again, so it is read and assessed again, never carried on an old qualification (owner, Oct 17 2026)
    lane_since = now - dt.timedelta(days=LANE_MEMBER_DAYS)
    mine = {r["story_id"] for r in store.rows(
        select(articles.c.story_id).where(articles.c.story_id.is_not(None), articles.c.feed_id.in_(sorted(lane_of)),
                                          articles.c.published_at >= lane_since))}
    if mine:
        ids_ = sorted(mine)
        fresh: set[int] = set()
        for i in range(0, len(ids_), 500):
            fresh |= {r["story_id"] for r in store.rows(
                select(articles.c.story_id).where(articles.c.story_id.in_(ids_[i:i + 500]),
                                                  articles.c.published_at >= since))}
        mine = fresh
    mine -= frozen_ids(store)
    if not mine:
        return {}
    cols = [articles.c.id, articles.c.story_id, articles.c.outlet, articles.c.url, articles.c.agency,
            articles.c.wire_group, articles.c.title, articles.c.text_source, articles.c.extracted_at,
            articles.c.extraction, articles.c.feed_id, articles.c.published_at,
            (func.length(articles.c.text) > 0).label("has_text")]
    by: dict[int, list[dict]] = {}
    ids = sorted(mine)
    for i in range(0, len(ids), 500):
        for r in store.rows(select(*cols).where(articles.c.story_id.in_(ids[i:i + 500]))):
            by.setdefault(r["story_id"], []).append(r)
    out = {}
    for sid, arts in by.items():
        lane, why = story_lane(arts, lane_of)
        if not lane:
            continue
        groups = independence_groups(arts)
        n = len(independent({groups[a["id"]] for a in arts if _readable(a)}))
        if n < 1 or n >= int(setting("normal_route_outlets", 3)):
            continue
        if len({outlet_key(a) for a in arts if _readable(a)}) < min_outlets():
            continue                      # one outlet's page only: waits for a second (owner, Oct 16 2026)
        out[sid] = {"lane": lane, "sig": story_sig(arts), "groups": n, "read": any(a["extracted_at"] for a in arts),
                    "newest": max((a["published_at"] for a in arts if a["published_at"]), default=now)}
    return out


def _now_utc() -> dt.datetime:
    from .db import utcnow
    return utcnow()


def focus(store, now: dt.datetime | None = None) -> set[int]:
    """The express stories to read and analyse this run: those already begun, plus the newest `reads_per_run`
    that have not been read at all. The cap is the express lane's own; it never takes a place from the
    preparation queue (priority.py)."""
    cands = candidates(store, now)
    begun = {sid for sid, c in cands.items() if c["read"]}
    new = _reading_order({sid: c for sid, c in cands.items() if not c["read"]}, int(setting("reads_per_run", 3)))
    take = new[:int(setting("reads_per_run", 3))]
    bump("story_candidates", len(cands))
    bump("story_begun", len(begun))
    bump("story_started", len(take))
    _now("stories_waiting_to_read", sum(1 for c in cands.values() if not c["read"]) - len(take))
    for sid in take:
        bump(f"started_{cands[sid]['lane']}")
    return begun | set(take)


def _reading_order(unread: dict[int, dict], limit: int) -> list[int]:
    """The unread express stories in the order to read them: one story from each lane in turn, lanes in the strict
    order (companies, tech, sport, entertainment), a lane's India stories before its "world" ones, newest first. So a
    quiet lane (tech, companies) is never crowded out by a busy one, and the lowest tier is read only when the others
    have nothing waiting."""
    by_lane: dict[str, list[int]] = {}
    for sid in sorted(unread, key=lambda s: (unread[s].get("sig") != "india", -(unread[s]["newest"].timestamp()))):
        by_lane.setdefault(unread[sid]["lane"], []).append(sid)
    lanes_in_order = sorted(by_lane, key=lambda l: tier(l, None))
    out: list[int] = []
    while len(out) < limit and any(by_lane.values()):
        for l in lanes_in_order:
            if by_lane[l] and len(out) < limit:
                out.append(by_lane[l].pop(0))
    return out


def disputed(store, sid: int) -> bool:
    """Two outlets, and a conflict was marked between statements or a statement is denied by one of them."""
    from sqlalchemy import select
    from .db import canonical, claims
    if any(r["stance"] == "denies" for r in store.rows(select(claims.c.stance).where(claims.c.story_id == sid))):
        return True
    return any(r["conflicts"] for r in store.rows(select(canonical.c.conflicts).where(canonical.c.story_id == sid)))


UNREAD_STORIES: set[int] = set()     # stories `assess` could not judge because the model could not read a headline (not revoked for it)
LANE_OF_STORY: dict[int, tuple[str, str]] = {}      # the lane of a story `assess` just passed (qualify saves it with the story)


def assess(store, sid: int) -> bool:
    """Does the story qualify under the express rule? (See the block comment above.) Code only; counts why not."""
    from sqlalchemy import func, select
    from .config import SETTINGS
    from .db import articles, claims
    from .wire import independence_groups, independent
    if not enabled():
        return False
    lane_of = lane_feeds(store)
    arts = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.wire_group,
                             articles.c.title, articles.c.text_source, articles.c.extracted_at, articles.c.extraction,
                             articles.c.feed_id, (func.length(articles.c.text) > 0).label("has_text"))
                      .where(articles.c.story_id == sid))
    lane, why = story_lane(arts, lane_of)
    if why == "risk_unread":
        UNREAD_STORIES.add(sid)
    else:
        UNREAD_STORIES.discard(sid)
    if not lane:
        if why != "no_lane":          # a normal story is not an express miss
            _count("story_out", why)
            _count("story_out_lane", f"?:{why}")
        return False
    groups = independence_groups(arts)
    readable = {groups[a["id"]] for a in arts if _readable(a)}
    read = {groups[a["id"]] for a in arts if a["extracted_at"] and _readable(a)}
    if len(independent(readable)) >= int(setting("normal_route_outlets", SETTINGS.qualify_min_outlets)):
        return False                  # three outlets or more: the normal rule decides
    if not independent(read):
        _count("story_out", "not_read_yet")
        _count("story_out_lane", f"{lane}:not_read_yet")
        return False
    if independent(readable) - independent(read):
        _count("story_out_lane", f"{lane}:second_outlet_unread")
        _count("story_out", "second_outlet_unread")     # its page is readable but not yet read: wait, never skip it
        return False
    # two OUTLETS read at least, independent or not (owner, Oct 16 2026), and every readable outlet read
    out_readable = {outlet_key(a) for a in arts if _readable(a)}
    out_read = {outlet_key(a) for a in arts if a["extracted_at"] and _readable(a)}
    if len(out_readable) < min_outlets():
        _count("story_out", "one_outlet")
        _count("story_out_lane", f"{lane}:one_outlet")
        return False
    if out_readable - out_read:
        _count("story_out", "second_outlet_unread")
        _count("story_out_lane", f"{lane}:second_outlet_unread")
        return False
    if len(independent(read)) >= 2 and disputed(store, sid):
        _count("story_out_lane", f"{lane}:disputed")
        _count("story_out", "disputed")
        return False
    rows = store.rows(select(claims.c.kind, claims.c.stance, claims.c.attributed_to).where(claims.c.story_id == sid))
    ok, why = origin_verdict(rows, lane)
    if not ok:
        _count("story_out", why)
        _count("story_out_lane", f"{lane}:{why}")
        return False
    _count("story_in", f"{lane}:{why}")
    bump("story_qualified")
    LANE_OF_STORY[sid] = (lane, story_sig(arts))
    return True


def still_holds(store, sid: int) -> bool:
    """The express rule checked again NOW, by code (no model, funnel not counted). An express qualification is kept
    from the run that made it, and a report that joins later (a second outlet, unread) does not by itself bring the
    story back for a check: story 23995 qualified on Oct 13 on one outlet, Aaj Tak joined on Oct 16 unread, and the
    desk wrote it on the old mark. So the desk asks this before writing, and every run clears a mark that fails it."""
    _QUIET[0] += 1
    try:
        ok = assess(store, sid)
    finally:
        _QUIET[0] -= 1
        LANE_OF_STORY.pop(sid, None)
    return ok


def revoke_stale(store, skip: set[int] | frozenset = frozenset()) -> list[int]:
    """Every unpublished story marked qualified by the express rule (except `skip`: closed, or just checked this run)
    that no longer passes `still_holds` loses the mark and is set dirty, so it is read and checked again. Returns the ids."""
    from sqlalchemy import select, update
    from .db import stories
    out = []
    for r in store.rows(select(stories.c.id, stories.c.analysis).where(stories.c.qualifies.is_(True))):
        if r["id"] in skip or (r["analysis"] or {}).get("qualified_by") != "express":
            continue
        if not still_holds(store, r["id"]):
            if r["id"] in UNREAD_STORIES:
                continue          # the model could not read a headline just now: the mark stays, the desk will not write it until it can
            store.exec(update(stories).where(stories.c.id == r["id"]).values(qualifies=False, dirty=True))
            out.append(r["id"])
    if out:
        bump("story_revoked", len(out))
    return out


def settle_decision(now: dt.datetime, last: dt.datetime | None, met: dt.datetime | None,
                    stale_after_hours: float, wait_hours: float | None = None) -> str | None:
    """Ready to write: the express rule has been met for `wait_for_second_hours` (a second outlet that reports it
    in that hour is read and checked first), and the newest report is not stale. Else None."""
    wait = float(setting("wait_for_second_hours", 1) if wait_hours is None else wait_hours)
    if last is None or (now - last).total_seconds() >= stale_after_hours * 3600:
        return None
    if met and (now - met).total_seconds() >= wait * 3600:
        return "express"
    return None


def qualify(store, sid: int) -> bool:
    """`assess`, and when it passes: the story qualifies by the express rule and keeps its lane in
    `analysis["express_lane"]`, where the writer's wording rules read it (`writer_note`)."""
    from sqlalchemy import select, update
    from .db import stories
    from . import perspectives
    if not assess(store, sid):
        return False
    perspectives.mark_qualified(store, sid, "express")
    lane, sig = LANE_OF_STORY.pop(sid, (None, None))
    row = store.one(select(stories.c.analysis).where(stories.c.id == sid)) or {}
    an = dict(row.get("analysis") or {})
    if lane and (an.get("express_lane"), an.get("express_sig")) != (lane, sig):
        an["express_lane"], an["express_sig"] = lane, sig
        store.exec(update(stories).where(stories.c.id == sid).values(analysis=an))
    return True


WRITER_NOTE = (
    "This story comes from one or two outlets and is about what a company, studio or organisation says about itself. "
    "Write every statement that says who makes it as that party's own word, with the verb the statement uses "
    "(\"X said\", \"X announced\", \"X plans\"). Never state a party's claim, plan, forecast, price, "
    "figure or ranking as established fact, and add no praise or adjective the statements do not carry.\n\n")


def writer_note(payload: dict) -> str:
    """Extra writer instruction for an express story outside sport (a match result is the reporter's own
    observation; a company's claim about itself is not). Empty for every other story."""
    if payload.get("qualified_by") != "express":
        return ""
    return "" if payload.get("express_lane") in (setting("own_voice_lanes", ["sport"]) or []) else WRITER_NOTE

"""The express lane (owner, Oct 12 2026): a short positive list of topics whose stories may be written from ONE
independent outlet's readable page. Config: `config/express.yaml`. Everything else keeps the strict rule.

Built in parts (see CLAUDE.md, "Express lane"):
  1. this module's door, in code: the lanes, the feeds that carry a lane, and `excluded` (a headline that
     matches an exclusion never enters the lane, whatever a model says); the ledger (ledger.py);
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
(`excluded`) is plain code.
"""
from __future__ import annotations

import datetime as dt
import functools
import logging
import re

log = logging.getLogger(__name__)

VERDICT_VERSION = 1
# The funnel of the run, plain numbers (run.py saves it as stats["express"], ledger.py prints it). Keys that are
# numbers are summed over runs; `excluded` {list: n} and `excluded_terms` {"list:term": n} count code exclusions;
# `now` holds readings that are not sums (cap left, passed and waiting).
STATS: dict = {}

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MONTH_BEFORE = {"in", "since", "until", "till", "by", "from", "of", "on", "this", "last", "next", "early", "late",
                "mid", "during", "before", "after", "every", "each", "through", "to", "for"}


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
    _compiled.cache_clear()
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

def _term_regex(term: str) -> tuple[re.Pattern, bool]:
    """(pattern, hindi). Latin terms: whole words, phrases with any spacing; an all-capitals term is matched as
    written (ED the agency, never Ed Sheeran). Hindi terms: plain fragments."""
    term = str(term).strip()
    if DEVANAGARI.search(term):
        return re.compile(re.escape(term)), True
    body = r"\s+".join(re.escape(w) for w in term.split())
    flags = 0 if (term == term.upper() and any(ch.isalpha() for ch in term)) else re.IGNORECASE
    return re.compile(rf"(?<![\w]){body}(?![\w])", flags), False


@functools.lru_cache(maxsize=1)
def _compiled() -> dict:
    c = cfg()
    ex = c.get("exclude") or {}
    apply_ = c.get("apply") or {}
    reasons = {}
    for reason, terms in ex.items():
        where = apply_.get(reason, "all")
        reasons[reason] = (None if where == "all" else set(where),
                           [(t, *_term_regex(t)) for t in (terms or [])])
    pats = {}
    for reason, plist in ((c.get("patterns") or {}).items()):
        pats[reason] = [re.compile(p, re.IGNORECASE) for p in plist or []]
    allow = [re.compile(re.escape(a), re.IGNORECASE) for a in (c.get("allow_phrases") or [])]
    urls = [u.lower() for u in (c.get("exclude_url") or [])]
    return {"reasons": reasons, "patterns": pats, "allow": allow, "urls": urls}


def _may_is_a_month(text: str, m: re.Match) -> bool:
    """\"May\" is a month, not a doubt, when it is written with a capital and follows a time word (\"in May\"),
    or a number follows it (\"May 12\"). \"may\" in lower case is always the verb."""
    word = m.group(0)
    if word != "May":
        return False
    after = text[m.end():].lstrip()[:1]
    if after.isdigit():
        return True
    before = re.findall(r"[A-Za-z']+", text[:m.start()])
    return bool(before) and before[-1].lower() in MONTH_BEFORE


def excluded(title: str, lead: str = "", url: str = "", lane: str | None = None) -> str | None:
    """Why this report must stay out of the express lane, or None. `reason:term` (e.g. \"harm:arrested\").

    Code only, applied before any model sees the headline. With `lane` None only the lists that apply to every
    lane are used (the cheap first look); with a lane, that lane's own lists are added too. A match in the
    headline or in the opening words counts."""
    c = _compiled()
    u = (url or "").lower()
    for piece in c["urls"]:
        if piece in u:
            return f"url:{piece.strip('/')}"
    text = f"{title or ''}. {(lead or '')[:300]}"
    for rx in c["allow"]:
        text = rx.sub(" ", text)
    for reason, (where, terms) in c["reasons"].items():
        if where is not None and (lane is None or lane not in where):
            continue
        for term, rx, _hindi in terms:
            for m in rx.finditer(text):
                if term.lower() == "may" and _may_is_a_month(text, m):
                    continue
                return f"{reason}:{term}"
    for reason, plist in c["patterns"].items():
        for rx in plist:
            if rx.search(title or ""):
                return f"{reason}:pattern"
    return None


def reason_group(reason: str | None) -> str | None:
    """The list a reason came from (\"harm:arrested\" -> \"harm\"), for the ledger's counts."""
    return reason.split(":", 1)[0] if reason else None


# --- the funnel counters -----------------------------------------------------------------------------------------

def reset() -> None:
    """A new run (ingest calls it first)."""
    STATS.clear()


def bump(key: str, n: int = 1) -> None:
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
    for f, en in mine:
        why = excluded(en.get("title") or "", en.get("summary") or "", en.get("url") or "", lane_of_url(f["url"]))
        if why:
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


# --- the verdict, kept with the article --------------------------------------------------------------------------

def verdict_of(a: dict) -> dict | None:
    """The stored express verdict of an article (articles.extraction["express"]), or None if it has none yet."""
    ex = a.get("extraction")
    v = ex.get("express") if isinstance(ex, dict) else None
    return v if isinstance(v, dict) and v.get("v") == VERDICT_VERSION else None


def _verdict(verdict: str, lane: str | None, why: str | None, now: dt.datetime) -> dict:
    v = {"v": VERDICT_VERSION, "verdict": verdict, "at": now.isoformat(timespec="minutes")}
    if lane:
        v["lane"] = lane
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
    undecided: list[dict] = []
    save: dict[int, dict] = {}
    for a in mine:
        v = verdict_of(a)
        if v is None:
            lane = lane_of[a["feed_id"]]
            if (a.get("text_source") or "full") == "summary":
                save[a["id"]] = _verdict("no", lane, "unreadable", now)
                bump("unreadable")
                v = save[a["id"]]
            else:
                why = excluded(a.get("title") or "", (a.get("text") or "")[:300], a.get("url") or "", lane)
                if why:
                    _count_excluded(why)
                    save[a["id"]] = _verdict("excluded", lane, why, now)
                    v = save[a["id"]]
        if v is None:
            undecided.append(a)
        elif v.get("verdict") == "yes":
            passed.append(a)
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
            why = excluded(a.get("title") or "", (a.get("text") or "")[:300], a.get("url") or "", lane)
            if why:
                _count_excluded(why)
                save[a["id"]] = _verdict("excluded", lane, why, now)
                held.add(a["id"])
                continue
            save[a["id"]] = _verdict("yes", lane, None, now)
            bump("passed")
            bump(f"passed_{lane}")
            passed.append(a)
        done = {a["id"] for a in todo if a["id"] in got}
        undecided = [a for a in undecided if a["id"] not in done]
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
    g = STATS.setdefault(group, {})
    g[key] = g.get(key, 0) + 1


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
    words = [str(w).lower() for w in setting("media_words", [])]
    if any(re.search(rf"\b{re.escape(w)}\b", n) for w in words):
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
            lanes_yes.add(v["lane"])
        elif v.get("verdict") == "excluded" or v.get("why") == "not_lane":
            return None, "member_" + ("excluded" if v.get("verdict") == "excluded" else "not_lane")
    if not lanes_yes:
        return None, "no_lane"
    if len(lanes_yes) > 1:
        return None, "two_lanes"
    lane = next(iter(lanes_yes))
    for a in members:
        why = excluded(a.get("title") or "", "", a.get("url") or "", lane)
        if why:
            return None, "member_excluded"
    return lane, None


def _readable(a: dict) -> bool:
    return (a.get("text_source") or "full") != "summary" and a.get("has_text", True)


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
    mine = {r["story_id"] for r in store.rows(
        select(articles.c.story_id).where(articles.c.story_id.is_not(None), articles.c.feed_id.in_(sorted(lane_of)),
                                          articles.c.published_at >= since))}
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
        out[sid] = {"lane": lane, "groups": n, "read": any(a["extracted_at"] for a in arts),
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
    new = sorted((sid for sid, c in cands.items() if not c["read"]), key=lambda sid: cands[sid]["newest"], reverse=True)
    take = new[:int(setting("reads_per_run", 3))]
    bump("story_candidates", len(cands))
    bump("story_begun", len(begun))
    bump("story_started", len(take))
    _now("stories_waiting_to_read", len(new) - len(take))
    return begun | set(take)


def disputed(store, sid: int) -> bool:
    """Two outlets, and a conflict was marked between statements or a statement is denied by one of them."""
    from sqlalchemy import select
    from .db import canonical, claims
    if any(r["stance"] == "denies" for r in store.rows(select(claims.c.stance).where(claims.c.story_id == sid))):
        return True
    return any(r["conflicts"] for r in store.rows(select(canonical.c.conflicts).where(canonical.c.story_id == sid)))


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
    if not lane:
        if why != "no_lane":          # a normal story is not an express miss
            _count("story_out", why)
        return False
    groups = independence_groups(arts)
    readable = {groups[a["id"]] for a in arts if _readable(a)}
    read = {groups[a["id"]] for a in arts if a["extracted_at"] and _readable(a)}
    if len(independent(readable)) >= int(setting("normal_route_outlets", SETTINGS.qualify_min_outlets)):
        return False                  # three outlets or more: the normal rule decides
    if not independent(read):
        _count("story_out", "not_read_yet")
        return False
    if independent(readable) - independent(read):
        _count("story_out", "second_outlet_unread")     # its page is readable but not yet read: wait, never skip it
        return False
    if len(independent(read)) >= 2 and disputed(store, sid):
        _count("story_out", "disputed")
        return False
    rows = store.rows(select(claims.c.kind, claims.c.stance, claims.c.attributed_to).where(claims.c.story_id == sid))
    ok, why = origin_verdict(rows, lane)
    if not ok:
        _count("story_out", why)
        return False
    _count("story_in", f"{lane}:{why}")
    bump("story_qualified")
    return True


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

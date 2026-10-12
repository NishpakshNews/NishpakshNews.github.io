"""YouTube videos for an article.

Fetched once, when the article is new (the desk, after publishing), so the site's videos button opens at once and
costs nothing per click.

Design (rebuilt Oct 12 2026 on the owner's idea; the first design found almost nothing, see `videoquery.py`):
  1. SEARCH VAGUE, TWICE. One phrase for the kind of event, in English, and one in Hindi (`videoquery.phrases`: a small
     model call checked by code, or code alone): "opposition march", not the names. Two searches of 50 results
     (100 units each), the last 30 days before the story's first report onwards; only if fewer than MIN_SHOW videos
     survive, the same two searches again with no date limit (older videos beat none).
  2. LANGUAGE ONLY WHEN SURE (`videoquery.video_language`), using the title's script and YouTube's language tags
     (one `videos.list` call for all ids, 1 unit). A video in any other language, or unclear, is not shown.
  3. RANK BY SIMILARITY to the story's own words: English videos against the English headline and article, Hindi
     videos against the Hindi ones (`videoquery.scores`). The best PER_LANG of each language, at most 2 per channel,
     credible channels get a 10% boost. If fewer than MIN_SHOW are kept, the best remaining language-sure videos fill
     the gap: the card is never empty while the search found any video in a language we are sure of.
  Each video is stored with its language ('hi' or 'en'); the site trusts it.

  4. THE ONGOING STORY, NOT ONLY THE NEWEST STEP (owner, Oct 13 2026). Headlines now avoid repeating the story's earlier
     ones, so a follow-up's headline names only what is new, while videos are titled for the whole story. The story's
     earlier headlines (its parents, nearest first, and the thread's root) go into the same single phrase call and into
     the ranking words (`videoquery.document(thread=)`), and so do the words that two or more other recent stories on
     the topic share (`neighbours=`, a weak hint). No extra YouTube or model call: the headlines are read from the DB.
  5. NO SHORTS (owner, Oct 13 2026). A video shorter than `videoquery.MIN_SECONDS`, or tagged #shorts, is dropped before
     anything else, including the fill-up to MIN_SHOW. The length comes from the same `videos.list` call as the
     language tags (`contentDetails` costs nothing extra). A live broadcast (no length yet) is not dropped.

Needs YOUTUBE_API_KEY (YouTube Data API v3, free: 10,000 units a day; a search costs 100, a details call 1). A story
costs 200 units, 400 when the older search is needed; DAY_UNITS and the per-run `limit` keep it under the day's quota.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import os

from sqlalchemy import func, update

from . import videoquery
from .db import Store, articles, insert, published, quota_usage, select, story_links, utcnow, videos

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/youtube/v3/search"
DETAILS_API = "https://www.googleapis.com/youtube/v3/videos"
PER_SEARCH = 50
PER_LANG = 5                            # videos kept per language (the site interleaves Hindi and English)
PER_CHANNEL = 2
MIN_SHOW = 3                            # fewer than this after the dated searches: the older search is made too
DAY_UNITS = 9000
NEW_HOURS = 36
WINDOW_DAYS = 30                        # the dated searches look this far before the story's first report
RETRY_AFTER = dt.timedelta(hours=3)     # a story that found nothing is tried once more after this
FIRST_WINDOW = dt.timedelta(hours=2)    # ...but only if the first try was made this soon after publishing
CREDIBLE_BOOST = 1.1
THREAD_MAX = 4                          # earlier headlines of the story's thread given to the phrase and the ranking
NEIGHBOUR_DAYS = 7                      # recent headlines of OTHER stories searched for topic neighbours
NEIGHBOUR_POOL = 400

# Exhaustive curated credible & analytical channels for Hindi
CREDIBLE_HI = {
    # UPSC / Public affairs / Deep-dive analysis
    "drishti ias",
    "drishti ias : english",
    "studyiq ias",
    "dhyeya ias",
    "next ias hindi",
    "unacademy upsc hindi",
    "khan global studies",
    "sanskriti ias",
    "pw onlyias",
    "parcham classes",
    "world affairs by unacademy",
    # Public broadcasters & legislative desks
    "sansad tv",
    "sansad tv hindi",
    "dd news",
    "dd national",
    "pib india",
    # Editorial & mainstream newsrooms
    "the lallantop",
    "aaj tak",
    "ndtv india",
    "bbc news hindi",
    "abp news",
    "news 24",
    "dainik bhaskar",
    "amar ujala",
    "tv9 bharatvarsh",
    "zee news",
}

# Exhaustive curated credible & analytical channels for English
CREDIBLE_EN = {
    # Public policy / Analytical / UPSC
    "theprint",
    "the wire",
    "scroll.in",
    "newslaundry",
    "vajiram & ravi",
    "vajiram and ravi",
    "vision ias",
    "insights ias",
    "forumias",
    "unacademy upsc",
    "sleepy classes",
    # Public & international coverage from India
    "sansad tv english",
    "wion",
    "rstv",
    # Mainstream editorial desks
    "the hindu",
    "the indian express",
    "hindustan times",
    "ndtv",
    "india today",
    "times now",
    "cnn-news18",
    "business standard",
    "livemint",
    "moneycontrol",
    "cnbc-tv18",
    "et now",
    "reuters",
    "associated press",
}


def match_channel(channel_title: str, channel_set: set[str]) -> bool:
    """Case-insensitive substring match against curated channel sets."""
    c = (channel_title or "").strip().lower()
    return any(target in c for target in channel_set)


def channel_language(channel_title: str) -> str | None:
    """Resolve language strictly by channel membership; returns None if unlisted."""
    if match_channel(channel_title, CREDIBLE_HI):
        return "hi"
    if match_channel(channel_title, CREDIBLE_EN):
        return "en"
    return None


def is_credible(channel_title: str) -> bool:
    """Check if the channel belongs to either curated list."""
    return match_channel(channel_title, CREDIBLE_HI) or match_channel(channel_title, CREDIBLE_EN)


def _units_today(store: Store) -> int:
    from .router import quota_day
    r = store.one(select(quota_usage.c.requests).where(quota_usage.c.model == "youtube-search",
                                                       quota_usage.c.day == quota_day()))
    return (r or {}).get("requests") or 0


def _naive_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Return a UTC-naive datetime for consistent comparisons across the two databases.

    The newsroom timestamps use ``utcnow()`` and are naive UTC, while Supabase ``timestamptz``
    values may arrive as timezone-aware datetimes. Naive values are already UTC by convention.
    """
    if value is None:
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def _due(updated_at: dt.datetime | None, have: dict | None, now: dt.datetime) -> bool:
    """A story has no videos row yet, or its empty first try is ready for one retry.

    Normalize timestamps at this boundary: newsroom values are naive UTC, but Supabase
    ``timestamptz`` values are commonly timezone-aware.
    """
    if have is None:
        return True
    if have.get("items"):
        return False

    now = _naive_utc(now)
    updated_at = _naive_utc(updated_at)
    fetched = _naive_utc(have.get("fetched_at"))
    if now is None or fetched is None or updated_at is None:
        return False

    return now - fetched >= RETRY_AFTER and fetched - updated_at <= FIRST_WINDOW

def _search(key: str, q: str, after: dt.datetime | None, lang: str, get=None) -> list[dict]:
    """One search. `after` None: no date limit."""
    import requests
    get = get or requests.get
    params = {
        "part": "snippet",
        "type": "video",
        "q": q[:200],
        "maxResults": PER_SEARCH,
        "key": key,
        "regionCode": "IN",
        "relevanceLanguage": lang,
        "safeSearch": "moderate",
    }
    if after is not None:
        params["publishedAfter"] = after.replace(microsecond=0).isoformat() + "Z"
    r = get(API, params=params, timeout=20)
    r.raise_for_status()
    out = []
    for it in r.json().get("items") or []:
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        if not vid:
            continue
        thumbs = sn.get("thumbnails") or {}
        thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
        ch_title = html.unescape(sn.get("channelTitle") or "")
        out.append({
            "id": vid,
            "title": html.unescape(sn.get("title") or ""),
            "desc": html.unescape(sn.get("description") or ""),
            "channel": ch_title,
            "channelId": sn.get("channelId"),
            "at": sn.get("publishedAt"),
            "thumb": thumb,
            "credible": is_credible(ch_title),
        })
    return out


def _details(key: str, ids: list[str], get=None) -> dict[str, dict]:
    """{video id: {"tag": YouTube's audio or default language tag, "seconds": length or None}} (one call, 1 unit, up
    to 50 ids; `contentDetails` adds no cost). {} when it fails: the title alone then has to make a video's language
    certain, and only the #shorts tag can tell a Short."""
    import requests
    get = get or requests.get
    out: dict[str, dict] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start:start + 50]
        r = get(DETAILS_API, params={"part": "snippet,contentDetails", "id": ",".join(chunk), "key": key}, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items") or []:
            sn = it.get("snippet") or {}
            out[it.get("id")] = {
                "tag": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or None,
                "seconds": videoquery.parse_duration((it.get("contentDetails") or {}).get("duration")),
            }
    return out


def choose(cands: list[dict], docs: dict[str, dict[str, float]], tags: dict[str, str | None] | None = None,
           per_lang: int = PER_LANG, per_channel: int = PER_CHANNEL, min_show: int = MIN_SHOW,
           seconds: dict[str, int | None] | None = None) -> list[dict]:
    """The videos to show. `docs` is {"en": weights, "hi": weights} from `videoquery.document`. Only videos whose
    language is certain and that are not Shorts (`seconds`: {video id: length}; also the #shorts tag); best
    similarity first within each language; at most `per_channel` per channel; if fewer than `min_show` are kept, the
    best remaining certain ones are added (never a Short). Returned items carry `lang`, no description."""
    tags = tags or {}
    seconds = seconds or {}
    seen: set[str] = set()
    certain: dict[str, list[dict]] = {"en": [], "hi": []}
    for v in cands:
        if not v.get("id") or v["id"] in seen:
            continue
        seen.add(v["id"])
        if videoquery.is_short(v.get("title"), v.get("desc"), seconds.get(v["id"])):
            continue
        cl = channel_language(v.get("channel") or "")
        lang = videoquery.video_language(v.get("title") or "", tags.get(v["id"]), cl)
        if lang in certain:
            certain[lang].append(dict(v, lang=lang))
    ranked: dict[str, list[dict]] = {}
    for lang, vids in certain.items():
        sc = videoquery.scores(vids, docs.get(lang) or {})
        for v, s in zip(vids, sc):
            v["score"] = s * (CREDIBLE_BOOST if v.get("credible") else 1.0)
        ranked[lang] = sorted(vids, key=lambda v: (-v["score"], _neg(v.get("at"))))
    out: list[dict] = []
    per: dict[str, int] = {}

    def take(v: dict) -> bool:
        ch = v.get("channelId") or v.get("channel")
        if per.get(ch, 0) >= per_channel:
            return False
        per[ch] = per.get(ch, 0) + 1
        out.append(v)
        return True
    for lang in ("en", "hi"):
        n = 0
        for v in ranked[lang]:
            if n >= per_lang:
                break
            if v["score"] > 0 and take(v):
                n += 1
    if len(out) < min_show:                        # never an empty card while a certain-language video exists
        rest = sorted((v for l in ranked.values() for v in l if v not in out), key=lambda v: -v["score"])
        for v in rest:
            if len(out) >= min_show:
                break
            take(v)
    return [{k: x for k, x in v.items() if k not in ("desc", "score")} for v in out]


def _neg(at: str | None) -> str:
    """Sort key: newer first among equal scores (ISO times sort as text)."""
    return "".join(chr(255 - ord(c)) if ord(c) < 256 else c for c in (at or ""))


def _gather(store: Store, key: str, qs: list[tuple[str, str]], after: dt.datetime | None, get=None) -> list[dict] | None:
    """Run each (phrase, language) search; the videos found, or None when a search failed (try again next run)."""
    from .router import quota_day
    found: list[dict] = []
    for q, lang in qs:
        try:
            found += _search(key, q, after, lang, get)
        except Exception as e:  # noqa: BLE001
            log.info("youtube search failed for %r: %s", q, e)
            return None
        store.quota_add("youtube-search", quota_day(), 100, 0)
    return found


def _thread(store: Store, story_id: int, limit: int = THREAD_MAX) -> tuple[list[str], list[str]]:
    """(English, Hindi) headlines of the story's earlier stories: its parents and their parents, nearest first, and
    the thread's root when the line is longer than `limit`. DB reads only. ([], []) for a story with no parents."""
    order: list[int] = []
    level, seen = [story_id], {story_id}
    for _ in range(20):
        ps = sorted({r["parent_id"] for cur in level
                     for r in store.rows(select(story_links.c.parent_id).where(story_links.c.child_id == cur))} - seen)
        if not ps:
            break
        order += ps
        seen.update(ps)
        level = ps
    if not order:
        return [], []
    if len(order) > limit:
        order = order[:limit - 1] + [order[-1]]
    rows = {r["story_id"]: r for r in store.rows(select(published.c.story_id, published.c.headline_en,
                                                        published.c.headline_hi).where(published.c.story_id.in_(order)))}
    en = [rows[i]["headline_en"] for i in order if i in rows and rows[i].get("headline_en")]
    hi = [rows[i]["headline_hi"] for i in order if i in rows and rows[i].get("headline_hi")]
    return en, hi


def _paragraphs(payload: dict | None) -> list[str]:
    return [x.get("text") or "" for para in ((payload or {}).get("narrative") or {}).get("paragraphs") or []
            for x in para]


def fetch_new(store: Store, limit: int = 6, key: str | None = None, get=None, router=None) -> list[int]:
    from .router import quota_day
    key = key if key is not None else os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        return []

    now = utcnow()
    since = now - dt.timedelta(hours=NEW_HOURS)
    have = {r["story_id"]: r for r in store.rows(select(videos.c.story_id, videos.c.fetched_at, videos.c["items"]))}
    rows = [r for r in store.rows(select(published.c.story_id, published.c.headline_en, published.c.headline_hi,
                                         published.c.payload_en, published.c.payload_hi, published.c.updated_at)
                                  .where(published.c.updated_at >= since).order_by(published.c.updated_at.desc()))
            if _due(r.get("updated_at"), have.get(r["story_id"]), now)]

    pool = None                          # recent headlines of every story, read once and only if a story is due
    done: list[int] = []
    for r in rows[:limit]:
        if _units_today(store) + 200 > DAY_UNITS:
            break
        head_en, head_hi = r.get("headline_en") or "", r.get("headline_hi") or ""
        thread_en, thread_hi = _thread(store, r["story_id"])
        if pool is None:
            pool = store.rows(select(published.c.story_id, published.c.headline_en, published.c.headline_hi)
                              .where(published.c.updated_at >= now - dt.timedelta(days=NEIGHBOUR_DAYS))
                              .order_by(published.c.updated_at.desc()).limit(NEIGHBOUR_POOL))
        others = [p for p in pool if p["story_id"] != r["story_id"]]
        near_en = videoquery.neighbours(head_en, [p["headline_en"] or "" for p in others if p["headline_en"] not in thread_en])
        near_hi = videoquery.neighbours(head_hi, [p["headline_hi"] or "" for p in others if p["headline_hi"] not in thread_hi])
        docs = {"en": videoquery.document(head_en, _paragraphs(r.get("payload_en")), thread_en, near_en),
                "hi": videoquery.document(head_hi, _paragraphs(r.get("payload_hi")), thread_hi, near_hi)}
        ph = videoquery.phrases(head_en, head_hi, router, thread_en, thread_hi)
        qs = [(ph[l], l) for l in ("en", "hi") if ph.get(l)]
        first = store.one(select(func.min(articles.c.published_at).label("t"))
                          .where(articles.c.story_id == r["story_id"]))
        start = (first or {}).get("t") or since
        after = start - dt.timedelta(days=WINDOW_DAYS)

        cands = _gather(store, key, qs, after, get) if qs else []
        if cands is None:
            continue
        tags: dict[str, str | None] = {}
        lengths: dict[str, int | None] = {}
        asked: set[str] = set()

        def details(c: list[dict]) -> None:
            ids = [v["id"] for v in c if v["id"] not in asked]
            if not ids:
                return
            try:
                got = _details(key, ids, get)
                store.quota_add("youtube-search", quota_day(), 1, 0)
            except Exception as e:  # noqa: BLE001  (the title alone must then make a language certain)
                log.info("youtube details failed: %s", e)
                return
            asked.update(ids)
            for vid, d in got.items():
                tags[vid], lengths[vid] = d["tag"], d["seconds"]
        details(cands)
        items = choose(cands, docs, tags, seconds=lengths)
        # too few: the same searches with no date limit; an older video on the topic beats an empty card
        if len(items) < MIN_SHOW and qs and _units_today(store) + 100 * len(qs) + 1 <= DAY_UNITS:
            older = _gather(store, key, qs, None, get)
            if older:
                cands = cands + older
                details(cands)
                items = choose(cands, docs, tags, seconds=lengths)
        log.info("videos for story %s: %s -> %d kept", r["story_id"], qs, len(items))

        if r["story_id"] in have:        # the one second try replaces the empty row
            store.exec(update(videos).where(videos.c.story_id == r["story_id"]).values(fetched_at=utcnow(), items=items))
        else:
            store.exec(insert(videos).values(story_id=r["story_id"], fetched_at=utcnow(), items=items))
        done.append(r["story_id"])

    return done

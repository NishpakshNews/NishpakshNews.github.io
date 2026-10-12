"""YouTube videos for an article.

Fetched once, when the article is new (the desk, after publishing), so the site's videos button opens at once and
costs nothing per click.

Design:
  * What is searched and what counts as relevant lives in `videoquery.py` (owner, Oct 12 2026): figures are taken
    out of every query, the English search is made from the story's NAMES and main act, the Hindi search from the
    Hindi headline's own words, and a video must share two root words with the story's keywords (names and both
    headlines), not with the headline alone. A second, shorter search runs only when the first left fewer than
    MIN_USABLE videos. A story that found nothing is tried once more, about 3 h later.
  * Each search fetches 50 results (100 units each) to maximize pool depth without burning extra quota.
  * Curated credible lists for Hindi and English (analytical outlets, UPSC/IAS desks, established national newsrooms).
  * Exact language tagging: channels in the Hindi list are tagged 'hi', channels in the English list are tagged 'en'.
    Channels absent from both lists leave 'lang' as None so the frontend displays no language badge.
  * Showing something beats showing nothing (owner, Oct 12 2026): the rules above gave empty video cards. Videos are
    ranked in three tiers, best first: (0) closely related (two shared root words) and uploaded after the story's
    first report; (1) closely related but OLDER (a search with no date limit, made only when tier 0 gave fewer than
    MIN_USABLE); (2) recent but loosely related (the title shares one of the story's NAMES). The reader can scroll
    YouTube for the rest. Titles that share no name or two words with the story (audiobooks, drama, ads) are still
    left out. Within a tier, credible channels come first.
  * At most 2 videos from one channel, keeping diversity across sources.

Needs YOUTUBE_API_KEY (YouTube Data API v3, free: 10,000 units a day; a search costs 100).
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import os
import re

from sqlalchemy import func, update

from . import videoquery
from .db import Store, articles, claims, insert, published, quota_usage, select, utcnow, videos

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/youtube/v3/search"
PER_SEARCH = 50
KEEP = 10
PER_CHANNEL = 2
DAY_UNITS = 9000
NEW_HOURS = 36
MIN_USABLE = 2                          # fewer videos than this after the first searches: a shorter search is made
RETRY_AFTER = dt.timedelta(hours=3)     # a story that found nothing is tried once more after this
FIRST_WINDOW = dt.timedelta(hours=2)    # ...but only if the first try was made this soon after publishing

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


def relevant(title: str, headlines: list[str], names: list[str] | None = None) -> bool:
    """A video's title shares at least two root words with the story's headlines (and names, when given)."""
    kw = set()
    for h in headlines:
        kw |= videoquery.roots(h)
    for n in names or []:
        kw |= videoquery.roots(n)
    return videoquery.relevant(title, kw)


def pick(lists: list[list[dict]], keep: int = KEEP, per_channel: int = PER_CHANNEL) -> list[dict]:
    """Take results, ranking credible channels first, enforcing the per-channel cap."""
    combined: list[dict] = []
    for lst in lists:
        combined.extend(lst)

    # best tier first, then credible channels ahead of unlisted ones, preserving relative discovery order
    combined.sort(key=lambda v: (v.get("tier", 0), 0 if v.get("credible") else 1))

    out: list[dict] = []
    seen: set[str] = set()
    per: dict[str, int] = {}

    for v in combined:
        if len(out) >= keep:
            break
        vid = v.get("id")
        ch = v.get("channelId") or v.get("channel")
        if not vid or vid in seen or per.get(ch, 0) >= per_channel:
            continue
        seen.add(vid)
        per[ch] = per.get(ch, 0) + 1
        out.append(v)

    return out


def _search(key: str, q: str, after: dt.datetime | None, lang: str, get=None) -> list[dict]:
    """`after` None: no date limit (the search for older, closely related videos)."""
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
            "channel": ch_title,
            "channelId": sn.get("channelId"),
            "at": sn.get("publishedAt"),
            "thumb": thumb,
            "lang": channel_language(ch_title),
            "credible": is_credible(ch_title),
        })
    return out


def _units_today(store: Store) -> int:
    from .router import quota_day
    r = store.one(select(quota_usage.c.requests).where(quota_usage.c.model == "youtube-search",
                                                       quota_usage.c.day == quota_day()))
    return (r or {}).get("requests") or 0


def _due(updated_at: dt.datetime | None, have: dict | None, now: dt.datetime) -> bool:
    """A story has no videos row yet, or its only row is empty from a first try made soon after publishing and
    is now old enough for the one second try (owner, Oct 12 2026: \"they fail to fetch\", and an empty row was final)."""
    if have is None:
        return True
    if have.get("items"):
        return False
    fetched = have.get("fetched_at")
    if not fetched or not updated_at:
        return False
    return now - fetched >= RETRY_AFTER and fetched - updated_at <= FIRST_WINDOW


def _run(store: Store, key: str, qs: list[tuple[str, str]], after: dt.datetime | None, kw: set[str], get=None,
         names: set[str] | None = None) -> list | None:
    """Search each (query, language) and tier the videos (see the module note). None when a search failed (try
    again next run). With `after` (recent search): two shared words = tier 0; when `names` are given, one shared
    name = tier 2. Without `after` (older search): two shared words = tier 1; nothing weaker."""
    from .router import quota_day
    lists: list[list[dict]] = []
    for q, lang in qs:
        try:
            results = _search(key, q, after, lang, get)
        except Exception as e:  # noqa: BLE001
            log.info("youtube search failed for %r: %s", q, e)
            return None
        store.quota_add("youtube-search", quota_day(), 100, 0)
        kept = []
        for v in results:
            if videoquery.relevant(v["title"], kw):
                kept.append(dict(v, tier=0 if after is not None else 1))
            elif after is not None and names and videoquery.loosely_relevant(v["title"], names):
                kept.append(dict(v, tier=2))
        lists.append(kept)
    return lists


def _strong(lists: list[list[dict]]) -> int:
    """How many distinct tier-0 videos (closely related and recent) the searches found."""
    return len(pick([[v for v in lst if v.get("tier", 0) == 0] for lst in lists], keep=KEEP))


def fetch_new(store: Store, limit: int = 6, key: str | None = None, get=None) -> list[int]:
    key = key if key is not None else os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        return []

    now = utcnow()
    since = now - dt.timedelta(hours=NEW_HOURS)
    have = {r["story_id"]: r for r in store.rows(select(videos.c.story_id, videos.c.fetched_at, videos.c.items))}
    rows = [r for r in store.rows(select(published.c.story_id, published.c.headline_en, published.c.headline_hi,
                                         published.c.updated_at)
                                  .where(published.c.updated_at >= since).order_by(published.c.updated_at.desc()))
            if _due(r.get("updated_at"), have.get(r["story_id"]), now)]

    done: list[int] = []
    for r in rows[:limit]:
        if _units_today(store) + 200 > DAY_UNITS:
            break

        frames = [(cr.get("rel") or {}).get("frame") or {} for cr in store.rows(
            select(claims.c.rel).where(claims.c.story_id == r["story_id"], claims.c.kind == "event"))]
        kw = videoquery.keywords(frames, r["headline_en"], r["headline_hi"])
        first = store.one(select(func.min(articles.c.published_at).label("t"))
                          .where(articles.c.story_id == r["story_id"]))
        after = ((first or {}).get("t") or since) - dt.timedelta(hours=1)

        names = videoquery.name_keywords(frames)
        qs = videoquery.queries(frames, r["headline_en"], r["headline_hi"])
        lists = _run(store, key, qs, after, kw, get, names) if qs else []
        if lists is None:
            continue
        # too few closely related recent videos: a shorter search (the names alone, the first words of the Hindi headline)
        if _strong(lists) < MIN_USABLE and _units_today(store) + 100 * 2 <= DAY_UNITS:
            again = [q for q in videoquery.queries(frames, r["headline_en"], r["headline_hi"], short=True)
                     if q not in qs]
            more = _run(store, key, again, after, kw, get, names) if again else []
            lists += more or []          # a failed second try keeps what the first found
        # still too few: older videos that ARE about the story (no date limit); better than an empty card
        if _strong(lists) < MIN_USABLE and qs and _units_today(store) + 100 * len(qs) <= DAY_UNITS:
            older = _run(store, key, qs, None, kw, get)
            lists += older or []
        items = [{k: v for k, v in x.items() if k != "tier"} for x in pick(lists)]
        log.info("videos for story %s: %s -> %d kept", r["story_id"], [q for q, _ in qs], len(items))

        if r["story_id"] in have:        # the one second try replaces the empty row
            store.exec(update(videos).where(videos.c.story_id == r["story_id"]).values(fetched_at=utcnow(), items=items))
        else:
            store.exec(insert(videos).values(story_id=r["story_id"], fetched_at=utcnow(), items=items))
        done.append(r["story_id"])

    return done

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
from .db import Store, articles, insert, published, quota_usage, select, utcnow, videos

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


def _tags(key: str, ids: list[str], get=None) -> dict[str, str | None]:
    """{video id: YouTube's audio or default language tag} (one call, 1 unit, up to 50 ids). {} when it fails: the
    title alone then has to make a video's language certain."""
    import requests
    get = get or requests.get
    out: dict[str, str | None] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start:start + 50]
        r = get(DETAILS_API, params={"part": "snippet", "id": ",".join(chunk), "key": key}, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items") or []:
            sn = it.get("snippet") or {}
            out[it.get("id")] = sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or None
    return out


def choose(cands: list[dict], docs: dict[str, dict[str, float]], tags: dict[str, str | None] | None = None,
           per_lang: int = PER_LANG, per_channel: int = PER_CHANNEL, min_show: int = MIN_SHOW) -> list[dict]:
    """The videos to show. `docs` is {"en": weights, "hi": weights} from `videoquery.document`. Only videos whose
    language is certain; best similarity first within each language; at most `per_channel` per channel; if fewer than
    `min_show` are kept, the best remaining certain ones are added. Returned items carry `lang`, no description."""
    tags = tags or {}
    seen: set[str] = set()
    certain: dict[str, list[dict]] = {"en": [], "hi": []}
    for v in cands:
        if not v.get("id") or v["id"] in seen:
            continue
        seen.add(v["id"])
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
    have = {r["story_id"]: r for r in store.rows(select(videos.c.story_id, videos.c.fetched_at, videos.c.items))}
    rows = [r for r in store.rows(select(published.c.story_id, published.c.headline_en, published.c.headline_hi,
                                         published.c.payload_en, published.c.payload_hi, published.c.updated_at)
                                  .where(published.c.updated_at >= since).order_by(published.c.updated_at.desc()))
            if _due(r.get("updated_at"), have.get(r["story_id"]), now)]

    done: list[int] = []
    for r in rows[:limit]:
        if _units_today(store) + 200 > DAY_UNITS:
            break
        head_en, head_hi = r.get("headline_en") or "", r.get("headline_hi") or ""
        docs = {"en": videoquery.document(head_en, _paragraphs(r.get("payload_en"))),
                "hi": videoquery.document(head_hi, _paragraphs(r.get("payload_hi")))}
        ph = videoquery.phrases(head_en, head_hi, router)
        qs = [(ph[l], l) for l in ("en", "hi") if ph.get(l)]
        first = store.one(select(func.min(articles.c.published_at).label("t"))
                          .where(articles.c.story_id == r["story_id"]))
        start = (first or {}).get("t") or since
        after = start - dt.timedelta(days=WINDOW_DAYS)

        cands = _gather(store, key, qs, after, get) if qs else []
        if cands is None:
            continue
        tags: dict[str, str | None] = {}

        def details(c: list[dict]) -> None:
            ids = [v["id"] for v in c if v["id"] not in tags]
            if not ids:
                return
            try:
                tags.update(_tags(key, ids, get))
                store.quota_add("youtube-search", quota_day(), 1, 0)
            except Exception as e:  # noqa: BLE001  (the title alone must then make a language certain)
                log.info("youtube details failed: %s", e)
        details(cands)
        items = choose(cands, docs, tags)
        # too few: the same searches with no date limit; an older video on the topic beats an empty card
        if len(items) < MIN_SHOW and qs and _units_today(store) + 100 * len(qs) + 1 <= DAY_UNITS:
            older = _gather(store, key, qs, None, get)
            if older:
                cands = cands + older
                details(cands)
                items = choose(cands, docs, tags)
        log.info("videos for story %s: %s -> %d kept", r["story_id"], qs, len(items))

        if r["story_id"] in have:        # the one second try replaces the empty row
            store.exec(update(videos).where(videos.c.story_id == r["story_id"]).values(fetched_at=utcnow(), items=items))
        else:
            store.exec(insert(videos).values(story_id=r["story_id"], fetched_at=utcnow(), items=items))
        done.append(r["story_id"])

    return done

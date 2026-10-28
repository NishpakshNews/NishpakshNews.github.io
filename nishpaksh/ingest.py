"""Stage 1: read RSS feeds and article pages. Plain HTTP, no AI, no quota."""
from __future__ import annotations

import calendar
import datetime as dt
import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import requests
import trafilatura

from . import reliable
from .config import SETTINGS, load_yaml
from .db import Store, articles, feeds, insert, select, update, utcnow
from .wire import minhash

from . import hygiene

log = logging.getLogger(__name__)
IMAGE_STATS = {"with": 0, "without": 0}   # new articles this run with / without a picture (run stats "images")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8"}
# Some sites block browser-looking requests from cloud servers but allow declared bots,
# others the reverse. Try one, then the other.
BOT_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NishpakshBot/0.2; +https://nishpakshnews.github.io)",
               "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"}


def page_text(r: requests.Response) -> str:
    """The page as text (B10). requests decodes a page with no charset in its header as ISO-8859-1, which turned UTF-8
    Hindi into mojibake; trafilatura's decoder reads the page's own declaration or detects the charset."""
    if "charset" in (r.headers.get("content-type") or "").lower():
        return r.text
    try:
        from trafilatura.utils import decode_file
        return decode_file(r.content) or r.text
    except Exception:  # noqa: BLE001
        return r.text


def _fetch(url: str, headers: dict, timeout: int) -> requests.Response:
    """One GET with the reliable layer: a timeout or a 5xx / 429 is retried with backoff, per host circuit breaker."""
    def once():
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code in reliable.RETRY_STATUS and r.status_code != 429:
            raise reliable.HttpFailure(r.status_code)
        return r
    out = reliable.call("fetch:" + (urlsplit(url).hostname or ""), once, attempts=2, base=0.4)
    if out.ok:
        return out.value
    raise requests.RequestException(out.error or out.kind)


def _get(url: str, timeout: int) -> requests.Response:
    r = _fetch(url, HEADERS, timeout)
    if r.status_code in (401, 403, 429) or (r.ok and r.text.lstrip()[:15].lower().startswith(("<!doctype html", "<html"))
                                            and url.endswith((".xml", "/feed/", "/feed", "/rss", ".rss", ".cms"))):
        r2 = _fetch(url, BOT_HEADERS, timeout)
        if r2.ok:
            return r2
    return r
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|cmp$|ito$)")

AGENCY_PATTERNS = [
    ("PTI", r"\(\s*PTI\s*\)|\bPTI\b\s*$|^PTI\b"),
    ("ANI", r"\(\s*ANI\s*\)|^ANI\b"),
    ("IANS", r"\(\s*IANS\s*\)|^IANS\b"),
    ("UNI", r"\(\s*UNI\s*\)"),
    ("Reuters", r"\(\s*Reuters\s*\)"),
    ("AFP", r"\(\s*AFP\s*\)"),
    ("AP", r"\(\s*AP\s*\)"),
    ("Xinhua", r"\(\s*Xinhua\s*\)"),
    ("APP", r"\(\s*APP\s*\)"),
    ("Bhasha", r"\(\s*भाषा\s*\)|^भाषा\b"),
    ("ANI", r"\(\s*एएनआई\s*\)"),
    ("IANS", r"\(\s*आईएएनएस\s*\)"),
    ("Agency", r"\(\s*एजेंसी\s*\)"),
]


def is_web_url(u: str | None) -> bool:
    """Only http(s) links are ever stored: anything else (javascript:, data:) would be a link on the page."""
    p = urlsplit((u or "").strip())
    return p.scheme.lower() in ("http", "https") and bool(p.netloc)


def canonical_url(u: str) -> str:
    p = urlsplit(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k.lower())]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urlencode(q), ""))


def detect_agency(author: str | None, text: str | None) -> str | None:
    probes = [(author or "").strip()]
    if text:
        probes += [text[:300], text[-200:]]
    for name, pat in AGENCY_PATTERNS:
        for p in probes:
            if p and re.search(pat, p, flags=re.MULTILINE):
                return name
    if author and re.fullmatch(r"(?i)\s*(pti|ani|ians|uni|reuters|afp|ap|xinhua|agencies|agency)\s*", author):
        return author.strip().upper()
    return None


# The picture each outlet publishes for its own share previews (owner, Oct 9 2026): collected now, chosen and
# shown later. Only the link is stored (never the image), "" = looked and found none, NULL = not looked yet.
IMAGE_META = ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src")
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")


def clean_image(u: str | None, base: str = "") -> str | None:
    """A usable picture link: absolute, http(s), not a data: URI, not absurdly long."""
    u = html.unescape((u or "").strip())
    if not u or u.startswith("data:"):
        return None
    if u.startswith("//"):
        u = "https:" + u
    u = urljoin(base, u) if base else u
    if not is_web_url(u) or len(u) > 1500:
        return None
    return u


def page_image(page_html: str, base: str = "") -> str | None:
    """og:image (else twitter:image) from a page's head."""
    head = page_html[:200_000]
    found: dict[str, str] = {}
    for tag in _META.findall(head):
        attrs = {k.lower(): v.strip("\"'") for k, v in _ATTR.findall(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        if key in IMAGE_META and attrs.get("content") and key not in found:
            found[key] = attrs["content"]
    for key in IMAGE_META:
        img = clean_image(found.get(key), base)
        if img:
            return img
    return None


def entry_image(e) -> str | None:
    """The picture a feed entry carries (media:content, media:thumbnail, an image enclosure)."""
    for key in ("media_content", "media_thumbnail"):
        for m in e.get(key) or []:
            if (m.get("medium") in (None, "image")) and not str(m.get("type", "image")).startswith(("video", "audio")):
                img = clean_image(m.get("url"))
                if img:
                    return img
    for ln in e.get("links") or []:
        if str(ln.get("type", "")).startswith("image"):
            img = clean_image(ln.get("href"))
            if img:
                return img
    return None


def strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def entry_time(e) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return dt.datetime.fromtimestamp(calendar.timegm(t), dt.timezone.utc).replace(tzinfo=None)
    return None


def sync_feeds(store: Store) -> None:
    """Make the feeds table match config/feeds.yaml: add new feeds, re-enable edited ones,
    and disable feeds that were removed from the file."""
    cfg = load_yaml("feeds.yaml")["feeds"]
    wanted = {f["url"]: f for f in cfg}
    existing = {r["url"]: r for r in store.rows(select(feeds))}
    for url, f in wanted.items():
        if url not in existing:
            store.exec(insert(feeds).values(name=f["name"], url=url, lang=f.get("lang", "en"),
                                            role=f.get("role", "news"), fail_count=0, disabled=False))
    for url, r in existing.items():
        if url not in wanted and not r["disabled"]:
            store.exec(update(feeds).where(feeds.c.id == r["id"]).values(disabled=True))


def fetch_feed(feed: dict) -> list[dict]:
    r = _get(feed["url"], timeout=20)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.bozo_exception}")
    out = []
    for e in parsed.entries:
        link = e.get("link")
        if not link or not is_web_url(link):
            continue
        out.append({
            "url": canonical_url(link),
            "title": strip_html(e.get("title", "")),
            "summary": strip_html(e.get("summary", "")),
            "author": e.get("author"),
            "published_at": entry_time(e),
            "image": entry_image(e),
        })
    return out


def fetch_article(url: str) -> dict | None:
    try:
        r = _get(url, timeout=25)
        html = page_text(r)
        if r.status_code != 200 or not html:
            return None
        doc = trafilatura.bare_extraction(html, url=url, with_metadata=True, include_comments=False, favor_precision=True)
    except Exception as e:  # noqa: BLE001
        log.debug("fetch failed %s: %s", url, e)
        return None
    if doc is None:
        return None
    d = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
    image = page_image(html, url) or clean_image(d.get("image"), url)
    from . import blocks
    text, _dropped = blocks.clean(html, d.get("text") or "")      # related-link strips are not the story (B33)
    return {"text": text, "author": d.get("author"), "title": d.get("title"), "image": image}


def fetch_image(url: str) -> str:
    """Only the picture of a page already read ("" when it has none or cannot be read)."""
    try:
        r = _get(url, timeout=15)
        return (page_image(page_text(r), url) or "") if r.status_code == 200 and r.content else ""
    except Exception:  # noqa: BLE001
        return ""


def fill_images(store: Store, limit: int = 120) -> int:
    """Articles stored before pictures were collected (or by a path that does not read the page): look once.
    First those behind the articles live on the site (any age: a live page needs its picture), then those of the
    last 36 h in a story, newest first. A page that has none, or blocks us, is marked "" and left."""
    from .db import published
    live = select(published.c.story_id)
    # a few per story, round the stories, so one story of 289 reports does not take the whole run
    per: dict[int, list] = {}
    for r in store.rows(select(articles.c.id, articles.c.url, articles.c.story_id).where(
            articles.c.image.is_(None), articles.c.story_id.in_(live)).order_by(articles.c.published_at.desc())):
        per.setdefault(r["story_id"], []).append(r)
    rows = []
    for k in range(3):
        rows += [v[k] for v in per.values() if len(v) > k]
    rows = rows[:limit]
    if len(rows) < limit:
        since = utcnow() - dt.timedelta(hours=36)
        have = {r["id"] for r in rows}
        rows += [r for r in store.rows(select(articles.c.id, articles.c.url).where(
            articles.c.image.is_(None), articles.c.story_id.isnot(None), articles.c.published_at >= since)
            .order_by(articles.c.published_at.desc()).limit(limit - len(rows))) if r["id"] not in have]
    if not rows:
        return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda r: fetch_image(r["url"]), rows))
    for r, img in zip(rows, got):
        store.exec(update(articles).where(articles.c.id == r["id"]).values(image=img))
    found = sum(1 for g in got if g)
    log.info("images: %d of %d older articles have one", found, len(rows))
    return found


def _dk(feed: dict) -> str:
    """The key of a feed in the intake diagnostics: an express feed has its lane in it (one outlet, many section feeds)."""
    from . import express
    lane = express.lane_of_url(feed["url"])
    return f"{feed['name']} [{lane}]" if lane else feed["name"]


def ingest(store: Store) -> int:
    from . import express
    express.reset()          # the express funnel of this run starts here (stats["express"])
    express.load_cache(store)        # the scores of earlier runs (risk.py)
    now = utcnow()
    oldest = now - dt.timedelta(hours=SETTINGS.max_article_age_hours)
    candidates: list[tuple[dict, dict]] = []
    seen: set[str] = set()
    diag: dict[str, dict] = {}

    for feed in store.rows(select(feeds).where(feeds.c.disabled.is_(False))):
        if express.skip_feed(feed["url"]):
            continue         # an express feed while its lane is off: never mixed into the politics intake
        try:
            entries = fetch_feed(feed)
            store.exec(update(feeds).where(feeds.c.id == feed["id"]).values(fail_count=0, last_ok=now))
        except Exception as e:  # noqa: BLE001
            fails = (feed["fail_count"] or 0) + 1
            disabled = fails >= SETTINGS.feed_disable_after_failures
            store.exec(update(feeds).where(feeds.c.id == feed["id"]).values(fail_count=fails, disabled=disabled))
            log.warning("feed %s failed (%d)%s: %s", feed["name"], fails, " -> DISABLED" if disabled else "", e)
            continue
        diag[_dk(feed)] = {"entries": len(entries), "fresh": 0, "new": 0, "added": 0, "too_short": 0}
        for en in entries:
            pub = en["published_at"] or now
            if pub < oldest or en["url"] in seen:
                continue
            seen.add(en["url"])
            candidates.append((feed, en))
            diag[_dk(feed)]["fresh"] += 1

    if not candidates:
        log.info("ingest: no fresh links; per feed %s", diag)
        return 0
    known = set()
    urls = [en["url"] for _, en in candidates]
    for i in range(0, len(urls), 500):
        known |= {r["url"] for r in store.rows(select(articles.c.url).where(articles.c.url.in_(urls[i:i + 500])))}
    todo = [(f, en) for f, en in candidates if en["url"] not in known]
    for f, _ in todo:
        diag[_dk(f)]["new"] += 1
    todo.sort(key=lambda fe: fe[1]["published_at"] or now, reverse=True)
    # express feeds have their own door and caps (express.py): the code exclusions run before any page is fetched
    todo, express_todo = express.take_intake(todo)
    per_feed: dict[int, int] = {}
    fair = []
    for f, en in todo:
        if per_feed.get(f["id"], 0) < SETTINGS.max_new_per_feed:
            per_feed[f["id"]] = per_feed.get(f["id"], 0) + 1
            fair.append((f, en))
    todo = fair[: SETTINGS.max_new_articles_per_run] + express_todo
    log.info("ingest: %d new links across %d feeds (%d from express feeds)", len(todo),
             len({f['id'] for f, _ in todo}), len(express_todo))

    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(lambda fe: fetch_article(fe[1]["url"]), todo))

    added = 0
    for (feed, en), page in zip(todo, pages):
        text, source = hygiene.repair((page or {}).get("text") or ""), "full"
        if len(text) < SETTINGS.min_full_text_chars:
            # page blocked or unreadable: fall back to what the feed itself says
            text, source = ". ".join(x for x in (en["title"], en["summary"]) if x), "summary"
        if len(text) < 60:
            diag[_dk(feed)]["too_short"] += 1
            continue
        author = (page or {}).get("author") or en["author"]
        values = dict(
            url=en["url"], feed_id=feed["id"], outlet=feed["name"], lang=feed["lang"], role=feed["role"],
            title=en["title"] or (page or {}).get("title") or "", author=(author or None) and author[:300],
            published_at=en["published_at"] or now, fetched_at=now, text=text, text_source=source,
            agency=detect_agency(author, text), minhash=minhash(text), extract_failures=0,
            image=(page or {}).get("image") or en.get("image") or "",
        )
        try:
            store.exec(insert(articles).values(**values))
            added += 1
            IMAGE_STATS["with" if values["image"] else "without"] += 1
            diag[_dk(feed)]["added"] += 1
        except Exception as e:  # unique race etc.
            log.debug("insert skipped %s: %s", en["url"], e)
    # a feed with new links that still added nothing has a real problem (blocked pages, empty text)
    stuck = {k: v for k, v in diag.items() if v["new"] and not v["added"]}
    if stuck:
        log.info("feeds with new links that added nothing: %s", stuck)
    return added

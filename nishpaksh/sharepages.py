"""Share pages: the thumbnail and headline that WhatsApp and other apps show when an article's link is sent.

The reading site is one page that opens an article from the part of the address after the `#`. Link-preview
robots never run the page and never see that part, so every shared link showed the same plain preview with no
picture. Each live article therefore also gets a tiny page of its own at a short, clean address,

    https://nishpakshnews.github.io/s/<id>/        English
    https://nishpakshnews.github.io/hi/s/<id>/     Hindi

whose head carries the preview (headline, opening sentence, the article's picture) and which sends a reader
straight on to the article. They are written into the `feed` branch (feed.py, `s/` and `hi/s/`) and
.github/scripts/build_site.sh copies them into the Pages build next to the site. The picture is the one on the
article's card: the outlet's own share picture, linked and credited, never copied; an article without one shows
the site's icon.
"""
from __future__ import annotations

import html
import json
import os
import pathlib
import shutil

SITE = os.environ.get("NISHPAKSH_SITE", "https://nishpakshnews.github.io").rstrip("/")
FALLBACK_IMAGE = f"{SITE}/icon-512.png"
DESCRIPTION_MAX = 200          # chats cut a longer preview anyway
NAME = {"en": "Nishpaksh", "hi": "निष्पक्ष"}


def share_path(sid, lang: str) -> str:
    """The article's address on the site, without the host: /s/<id>/ (Hindi: /hi/s/<id>/)."""
    return f"/hi/s/{sid}/" if lang == "hi" else f"/s/{sid}/"


def description(paras: list, limit: int = DESCRIPTION_MAX) -> str:
    """The article's opening, whole sentences, up to `limit` characters (the card's sentences are in page order)."""
    out = ""
    for para in paras or []:
        for s in para or []:
            t = " ".join((s.get("t") or "").split())
            if not t:
                continue
            if out and len(out) + 1 + len(t) > limit:
                return out
            out = f"{out} {t}".strip()
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    if len(out) > limit:
        out = out[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return out


def image_for(pic: dict | None) -> str:
    src = (pic or {}).get("src") or ""
    return src if src.startswith(("https://", "http://")) else FALLBACK_IMAGE


def render(sid, lang: str, headline: str, desc: str, image: str) -> str:
    e = lambda s: html.escape(s or "", quote=True)
    url = SITE + share_path(sid, lang)
    target = f"/?lang={lang}#/story/{sid}"
    name = NAME[lang]
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(headline)} · {name}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{name}">
<meta property="og:locale" content="{'hi_IN' if lang == 'hi' else 'en_IN'}">
<meta property="og:title" content="{e(headline)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(image)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(headline)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(image)}">
<meta name="theme-color" content="#1f2550">
<meta http-equiv="refresh" content="0; url={e(target)}">
<script>location.replace({json.dumps(target)});</script>
</head>
<body style="font-family:system-ui,sans-serif;margin:2rem">
<p><a href="{e(target)}">{e(headline)}</a></p>
</body>
</html>
"""


def write(root: str | pathlib.Path, manifest: dict, pics: dict, order: list[str]) -> int:
    """Write a page per live article and language under `root`/s and `root`/hi/s; pages of articles that are no
    longer live are removed. Returns the number of pages written."""
    root = pathlib.Path(root)
    for base in (root / "s", root / "hi" / "s"):
        shutil.rmtree(base, ignore_errors=True)
    n = 0
    for sid in order:
        for lang in ("en", "hi"):
            c = (manifest.get(sid) or {}).get(lang)
            if not c or not c.get("h"):
                continue
            d = root / share_path(sid, lang).strip("/")
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(
                render(sid, lang, c["h"], description(c.get("paras")), image_for(pics.get(sid))), encoding="utf-8")
            n += 1
    return n

"""Replay the express exclusions on stored headlines (express lane, part 4).

Why: the ledger says which words keep headlines out (`harm:detained` 176, `gossip:box office` 160 ...), but not whether
they kept out GOOD stories. This lists the stored headlines a word excluded, so the owner can judge, and shows which
of them would pass if the word were dropped from config/express.yaml (they could still fail another list).

    python -m nishpaksh.express_replay                      # every excluded headline, grouped by the word
    python -m nishpaksh.express_replay detained RBI         # only these words, and what dropping them would let in

`replay` is plain code (rows in, report out); only `main` touches the database. Nothing is written."""
from __future__ import annotations

import copy
import sys
from collections import defaultdict

from . import express


def _without(cfg: dict, drop: set[str]) -> dict:
    out = copy.deepcopy(cfg)
    for reason, terms in (out.get("exclude") or {}).items():
        out["exclude"][reason] = [t for t in terms or [] if str(t).lower() not in drop]
    return out


def replay(rows: list[dict], drop: set[str] | None = None) -> dict[str, list[dict]]:
    """rows: {title, url, lane, why} for headlines stored as excluded. Returns {"reason:term": [row + "now"]}: `now`
    is what the exclusions say about it WITHOUT the dropped words (None = it would pass the code lists)."""
    drop = {d.lower() for d in (drop or set())}
    base = express.cfg()
    saved = express.cfg
    try:
        if drop:
            express.cfg = lambda: _without(base, drop)
            express._compiled.cache_clear()
        out: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            out[r.get("why") or "?"].append(dict(r, now=express.excluded(r.get("title") or "", "", r.get("url") or "", r.get("lane"))))
        return dict(out)
    finally:
        express.cfg = saved
        express._compiled.cache_clear()


def stored_exclusions(store) -> list[dict]:
    from sqlalchemy import select
    from .db import articles
    rows = []
    for r in store.rows(select(articles.c.title, articles.c.url, articles.c.extraction)
                        .where(articles.c.extraction.is_not(None))):
        v = express.verdict_of(r)
        if v and v.get("verdict") == "excluded":
            rows.append({"title": r["title"], "url": r["url"], "lane": v.get("lane"), "why": v.get("why")})
    return rows


def main(argv: list[str]) -> None:
    from .config import database_url
    from .db import Store
    store = Store(database_url())
    words = {a.lower() for a in argv}
    rep = replay(stored_exclusions(store), words)
    for why, rows in sorted(rep.items(), key=lambda kv: -len(kv[1])):
        if words and why.split(":", 1)[-1].lower() not in words:
            continue
        free = [r for r in rows if r["now"] is None]
        print(f"\n{why}: {len(rows)} headlines" + (f", {len(free)} would pass without it" if words else ""))
        for r in (free if words else rows)[:15]:
            print("   -", (r["title"] or "")[:110], "" if words else f"[{r['lane']}]")


if __name__ == "__main__":
    main(sys.argv[1:])

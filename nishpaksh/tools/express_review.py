"""Why express articles are short (owner, Oct 16 2026): for the live express stories, how long the one report was,
how many statements the reading took from it, and how many words the page has. Read-only, no model.

Writes one `diagnostics` row (kind 'express_review', Supabase, private) holding the numbers and, for a sample, the
report's text and the statements read, so the gap can be read side by side. Prints numbers only (the workflow log is
public; article text never goes there).

    python -m nishpaksh.tools.express_review [--sample 15]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import statistics as st

from sqlalchemy import text as sql

from .. import heavy
from ..config import SETTINGS, database_url
from ..db import Store, articles, claims, published, select

log = logging.getLogger("express_review")


def _words(t: str) -> int:
    return len(re.findall(r"\w+", t or ""))


def collect(store: Store, sample: int) -> dict:
    pubs = [r for r in store.rows(select(published.c.story_id, published.c.payload_en))
            if (r["payload_en"] or {}).get("qualified_by") in ("express", "interim")]
    ids = [r["story_id"] for r in pubs]
    arts = store.rows(select(articles.c.id, articles.c.story_id, articles.c.outlet, articles.c.url, articles.c.title,
                             articles.c.text_source, articles.c.extraction, *heavy.columns(store, "text"))
                      .where(articles.c.story_id.in_(ids or [-1]), articles.c.extracted_at.is_not(None)))
    arts = heavy.fill(store, arts, "text")
    by_story: dict[int, list[dict]] = {}
    for a in arts:
        by_story.setdefault(a["story_id"], []).append(a)
    cl = store.rows(select(claims.c.article_id, claims.c.kind, claims.c.text, claims.c.rel)
                    .where(claims.c.article_id.in_([a["id"] for a in arts] or [-1]), claims.c.kind != "relation"))
    read: dict[int, list[dict]] = {}
    for c in cl:
        read.setdefault(c["article_id"], []).append(c)
    rows = []
    for r in pubs:
        p = r["payload_en"] or {}
        paras = (p.get("narrative") or {}).get("paragraphs") or []
        page_words = sum(_words(s.get("text")) for para in paras for s in para)
        shown = len(p.get("established") or []) + len(p.get("contested") or []) + len(p.get("context") or [])
        mine = by_story.get(r["story_id"], [])
        n_read = sum(len(read.get(a["id"], [])) for a in mine)
        ctx = sum(1 for a in mine for c in read.get(a["id"], []) if (c.get("rel") or {}).get("context"))
        text_words = sum(_words(a.get("text")) for a in mine)
        cut = sum(1 for a in mine if len(a.get("text") or "") > SETTINGS.max_article_chars)
        rows.append({"id": r["story_id"], "lane": p.get("qualified_by"), "headline": p.get("headline"),
                     "articles": len(mine), "text_words": text_words, "text_cut": cut,
                     "summary_only": sum(1 for a in mine if a.get("text_source") == "summary"),
                     "models": sorted({str((a.get("extraction") or {}).get("model")) for a in mine}),
                     "read": n_read, "read_context": ctx, "shown": shown, "page_words": page_words,
                     "words_per_statement_read": round(text_words / n_read, 1) if n_read else None})
    out: dict = {"stories": rows}
    for lane in ("express", "interim"):
        xs = [x for x in rows if x["lane"] == lane]
        if not xs:
            continue
        med = lambda k: st.median([x[k] for x in xs if x[k] is not None] or [0])  # noqa: E731
        out[lane] = {"n": len(xs), "text_words": med("text_words"), "read": med("read"), "shown": med("shown"),
                     "page_words": med("page_words"), "words_per_statement_read": med("words_per_statement_read"),
                     "text_cut": sum(x["text_cut"] for x in xs), "summary_only": sum(x["summary_only"] for x in xs)}
    # a sample to read side by side: the report and what was read from it (private table only)
    ex = sorted([x for x in rows if x["lane"] == "express"], key=lambda x: -x["text_words"])
    pick = ex[:sample // 2] + ex[len(ex) // 2: len(ex) // 2 + sample - sample // 2]
    out["sample"] = []
    for x in pick:
        for a in by_story.get(x["id"], [])[:1]:
            out["sample"].append({"id": x["id"], "url": a["url"], "title": a["title"], "text": (a.get("text") or "")[:9000],
                                  "read": [f'{c["kind"]}{"/" + c["rel"]["context"] if (c.get("rel") or {}).get("context") else ""}: {c["text"]}'
                                           for c in read.get(a["id"], [])]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=16)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = Store(database_url())
    report = collect(store, args.sample)
    print(json.dumps({k: v for k, v in report.items() if k in ("express", "interim")}, indent=1))
    with store.readers.engine.begin() as c:
        c.execute(sql("insert into diagnostics (kind, report) values ('express_review', :r)"),
                  {"r": json.dumps(report, ensure_ascii=False, default=str)})


if __name__ == "__main__":
    main()

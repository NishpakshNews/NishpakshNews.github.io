"""Read-only audits of the published articles (nishpaksh/audit.py has the checks; this is the thin reader).

Runs on GitHub's runner against the newsroom (workflow `audit`, read-only copy), no model call, nothing changed. Writes
one `diagnostics` row (kind 'audit') with the summary and prints it.

    python -m nishpaksh.tools.audit                # every live article (the newsroom's `published`)
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text as sql

from .. import audit
from ..config import database_url
from ..db import Store, articles, canonical, claims, published, select, stories

log = logging.getLogger("audit")


def collect(store: Store) -> list[dict]:
    pubs = store.rows(select(published.c.story_id, published.c.payload_en, published.c.payload_hi))
    ids = [r["story_id"] for r in pubs]
    if not ids:
        return []
    langs: dict[int, set] = {}
    for r in store.rows(select(articles.c.story_id, articles.c.lang)
                        .where(articles.c.story_id.in_(ids), articles.c.extracted_at.is_not(None))):
        langs.setdefault(r["story_id"], set()).add(r["lang"] or "en")
    texts: dict[int, dict[int, str]] = {}
    for r in store.rows(select(canonical.c.story_id, canonical.c.id, canonical.c.text, canonical.c.kind)
                        .where(canonical.c.story_id.in_(ids))):
        if r["kind"] != "relation" and r["text"]:
            texts.setdefault(r["story_id"], {})[r["id"]] = r["text"]
    asked = {r["id"]: ((r["analysis"] or {}).get("same_checks") or {})
             for r in store.rows(select(stories.c.id, stories.c.analysis).where(stories.c.id.in_(ids)))}
    from ..relate import relate
    out = []
    for r in pubs:
        sid = r["story_id"]
        pe, ph = r["payload_en"] or {}, r["payload_hi"] or {}
        out.append({
            "id": sid, "mix": audit.language_mix(langs.get(sid, set())),
            "merge": audit.merge_report(texts.get(sid, {}), asked.get(sid, {}), relate_fn=lambda a, b: relate(a, b)),
            "hindi": audit.hindi_report(ph) if ph else None,
            "openings": audit.openings_report((pe.get("narrative") or {}).get("paragraphs") or []),
            "forms": audit.forms_report(audit.article_text(pe)),
        })
    return out


def when_report(store: Store, limit: int = 20000) -> dict:
    """Code's reading of the stored time words (when.py) against the date the reading model typed, over the newest
    statements with a time: how often code reads them, agrees, differs (with examples), and refuses the model."""
    from .. import when
    rows = store.rows(select(claims.c.text, claims.c.time, articles.c.published_at, articles.c.lang)
                      .select_from(claims.join(articles, claims.c.article_id == articles.c.id))
                      .where(claims.c.time.is_not(None)).order_by(claims.c.id.desc()).limit(limit))
    when.STATS.clear()
    out = {"statements": 0, "with_words": 0, "examples_differ": [], "examples_model_only": [], "forms": {}}
    for r in rows:
        t = r["time"] or {}
        if not isinstance(t, dict):
            continue
        out["statements"] += 1
        if not (t.get("when_text") or "").strip():
            continue
        out["with_words"] += 1
        before = dict(when.STATS)
        new = when.read_time(dict(t), r["text"], r["published_at"])
        changed = {k for k in when.STATS if when.STATS[k] != before.get(k, 0)}
        ex = {"words": t["when_text"], "model": t.get("start"), "code": new.get("start"),
              "published": str(r["published_at"])[:16], "lang": r["lang"]}
        if "code_differs" in changed and len(out["examples_differ"]) < 25:
            out["examples_differ"].append(ex)
        if "model_only" in changed and len(out["examples_model_only"]) < 25:
            out["examples_model_only"].append(ex)
    out["counts"] = dict(when.STATS)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = Store(database_url())
    rows = collect(store)
    report = audit.summarise(rows)
    report["per_story"] = [{"id": s["id"], "mix": s["mix"], "near_pairs": s["merge"]["near_pairs"],
                            "statements": s["merge"]["statements"],
                            "latin": (s["hindi"] or {}).get("with_latin"), "alike": s["openings"]["alike"]}
                           for s in rows]
    report["when"] = when_report(store)
    print(json.dumps({k: v for k, v in report.items() if k != "per_story"}, ensure_ascii=False, indent=1))
    with store.readers.engine.begin() as c:      # diagnostics live in Supabase (db.READER_TABLES), not the newsroom copy
        c.execute(sql("insert into diagnostics (kind, report) values ('audit', :r)"),
                  {"r": json.dumps(report, ensure_ascii=False)})
    log.info("audit: %d live articles", len(rows))


if __name__ == "__main__":
    main()

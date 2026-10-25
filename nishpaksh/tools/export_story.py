"""Export ONE story's working data (no article bodies) from the loaded newsroom copy to a JSON file.

    python -m nishpaksh.tools.export_story --title Hyundai --since 2026-10-12 --out story.json

Article text is left out on purpose (publishers' copyright); claims, canonical statements and the
published article are what is needed to trace how a sentence was made.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from sqlalchemy import text as sql

from ..config import database_url
from ..db import Store


def _j(o):
    return o.isoformat() if isinstance(o, (dt.datetime, dt.date)) else str(o)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--since", default="2026-10-01")
    ap.add_argument("--out", default="story.json")
    a = ap.parse_args()
    store = Store(database_url(), readers_url="")
    out: dict = {}
    with store.engine.connect() as c:
        def rows(q, **p):
            return [dict(r) for r in c.execute(sql(q), p).mappings()]
        ids = [r["story_id"] for r in rows(
            "select distinct story_id from articles where story_id is not null and title ilike :t "
            "and published_at >= :s", t=f"%{a.title}%", s=a.since)]
        out["story_ids"] = ids
        for sid in ids:
            d = {}
            d["articles"] = rows("select id, outlet, url, title, published_at, story_id, lang, text_source, "
                                 "extract_failures, extracted_at, extraction from articles "
                                 "where story_id = :s order by id", s=sid)
            d["claims"] = rows("select id, article_id, local_id, kind, text, stance, attributed_to, evidence, time, "
                               "canonical_id, rel from claims "
                               "where story_id = :s order by article_id, local_id", s=sid)
            d["canonical"] = rows("select id, kind, text, verdict, checkable, conflicts, rel, origins from canonical "
                                  "where story_id = :s order by id", s=sid)
            try:                      # E9: the story's own record: analysis counters (failed asks, doubtful disputes ...) and the dossier
                d["story"] = rows("select id, analysis from stories where id = :s", s=sid)
                d["dossier"] = rows("select data from dossiers where story_id = :s", s=sid)
            except Exception as e:
                c.rollback()
                d["story"] = f"not exported: {e}"
            try:
                d["published"] = rows("select to_jsonb(p) as row from published p where p.story_id = :s", s=sid)
            except Exception as e:  # a column name differs: say so instead of failing the whole export
                c.rollback()
                d["published"] = f"not exported: {e}"
            out[str(sid)] = d
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=_j)
    print(f"stories {out['story_ids']} written to {a.out}")


if __name__ == "__main__":
    main()

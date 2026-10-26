"""One story's working numbers, to trace a page (read-only, no model): its articles (language, read or not), claims and
which merged statement each joined, the merged statements with their members, the story's analysis keys and the
published page's counts. Writes a `diagnostics` row (kind 'story_check', private); prints counts only.

    python -m nishpaksh.tools.story_check 23690 26428
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter

from sqlalchemy import text as sql

from ..config import database_url
from ..db import Store


def _j(o):
    return o.isoformat() if isinstance(o, (dt.datetime, dt.date)) else str(o)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", type=int)
    a = ap.parse_args()
    store = Store(database_url())
    if not a.ids:        # no ids typed: the five newest published stories
        with store.engine.connect() as c:
            a.ids = [r[0] for r in c.execute(sql("select story_id from published order by updated_at desc limit 5"))]
    out: dict = {}
    with store.engine.connect() as c:
        def rows(q, **p):
            return [dict(r) for r in c.execute(sql(q), p).mappings()]
        for sid in a.ids:
            arts = rows("select id, outlet, lang, text_source, extracted_at, extract_failures, wire_group, agency, "
                        "published_at, story_id from articles where story_id = :s order by id", s=sid)
            cl = rows("select id, article_id, kind, text, canonical_id, stance, attributed_to from claims "
                      "where story_id = :s order by article_id, id", s=sid)
            can = rows("select id, kind, text, verdict, conflicts, origins from canonical where story_id = :s order by id", s=sid)
            st = rows("select id, signature, qualifies, dirty, updated_at, analysis from stories where id = :s", s=sid)
            pub = rows("select version, updated_at, payload_en->'counts' as counts, "
                       "payload_en->'qualified_by' as q from published where story_id = :s", s=sid)
            members = Counter(x["canonical_id"] for x in cl if x["canonical_id"] is not None)
            arts_of = {}
            for x in cl:
                if x["canonical_id"] is not None:
                    arts_of.setdefault(x["canonical_id"], set()).add(x["article_id"])
            an = (st[0]["analysis"] if st else None) or {}
            summary = {
                "articles": len(arts), "read": sum(1 for x in arts if x["extracted_at"]),
                "langs": dict(Counter(x["lang"] for x in arts)),
                "claims": len(cl), "claims_unmatched": sum(1 for x in cl if x["canonical_id"] is None),
                "canonical": len(can),
                "canonical_by_articles": dict(Counter(min(len(v), 6) for v in arts_of.values())),
                "verdicts": dict(Counter(x["verdict"] for x in can)),
                "analysis_keys": sorted(an)[:60], "story": {k: st[0][k] for k in ("qualifies", "dirty", "updated_at")} if st else None,
                "published": pub,
            }
            print(sid, json.dumps({k: v for k, v in summary.items() if k != "published"}, default=_j))
            out[str(sid)] = {"summary": summary, "articles": arts, "claims": cl, "canonical": can,
                             "analysis": an}
    with store.readers.engine.begin() as c:
        c.execute(sql("insert into diagnostics (kind, report) values ('story_check', :r)"),
                  {"r": json.dumps(out, ensure_ascii=False, default=_j)})


if __name__ == "__main__":
    main()

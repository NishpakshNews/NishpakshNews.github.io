"""Shadow measure for `insert`: how many "Also in these reports" lines would be placed in the article, and where.
Reads the latest published pages (or --file {story_id: {"headline", "paragraphs", "also"}}); changes nothing."""
from __future__ import annotations

import argparse
import json

from .. import insert
from ..narrative import shade


def run(pages: dict, ref=None) -> dict:
    tot = {"stories": 0, "lines": 0, "inserted": 0, "why_not": {}, "placed": []}
    for sid, s in pages.items():
        also = s.get("also") or []
        if not also or not s.get("paragraphs"):
            continue
        _, rep = insert.insert([list(p) for p in s["paragraphs"]], also, s.get("headline") or "", shade=shade, ref=ref)
        tot["stories"] += 1
        tot["lines"] += rep["lines"]
        tot["inserted"] += rep["inserted"]
        for k, v in rep["why_not"].items():
            tot["why_not"][k] = tot["why_not"].get(k, 0) + v
        lead = " ".join((x.get("text") or "") for para in s["paragraphs"] for x in para)[:240]
        tot["placed"] += [{"story": sid, "headline": s.get("headline"), "lead": lead, "near": it.get("near"), "tie": it["place"],
                           "shared": it.get("shared"), "text": it["text"]} for it in rep["items"] if it["ok"]]
    tot["share_inserted"] = round(tot["inserted"] / tot["lines"], 3) if tot["lines"] else 0
    return tot


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    if args.file:
        pages = json.load(open(args.file))
    else:
        from sqlalchemy import text as sql
        from ..config import database_url
        from ..db import Store
        store = Store(database_url())
        pages = {}
        with store.engine.begin() as c:
            for sid, p in c.execute(sql("select story_id, payload_en from published order by updated_at desc limit :n"), {"n": args.limit}):
                if p:
                    pages[str(sid)] = {"headline": p.get("headline"), "paragraphs": (p.get("narrative") or {}).get("paragraphs") or [],
                                       "also": p.get("also") or []}
    print(json.dumps(run(pages), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

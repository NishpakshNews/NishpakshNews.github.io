"""Paragraph tidy in SHADOW (build charter, adoption rule): `tidy.py` is run beside the current code on the stored live articles
and nothing is changed. Read-only, no model quota. One `diagnostics` row, kind 'tidy_shadow'.

    python -m nishpaksh.tools.tidy_shadow                    # the latest 60 live articles (database)
    python -m nishpaksh.tools.tidy_shadow --limit 200
    python -m nishpaksh.tools.tidy_shadow --file pages.json  # {"<story id>": paragraphs} or [payload, ...]; no database

For each article: how many lines `tidy` would fold (`same` / `covered`), how many pairs are merge candidates (`overlap`), how many are
conflicts (two answers to one question: both stay), the paragraphs that would fall to one sentence, and what the current code (the
inspector's `repeats`) counted. With the local reader (NLI) available it runs twice, code alone and code + reader, and lists the
pairs the reader changed. Read the folded pairs first: ANY of them that is not a repeat is a false fold, and the adoption bar is
99% precision on folds. Weekday-date mismatches ("Tuesday, 28 October 2026") are counted too.
"""
from __future__ import annotations

import argparse
import json

from .. import inspector, tidy

EXAMPLES = 30


def lines_of(payload: dict) -> list[list[dict]]:
    return [[dict(x) for x in para if (x.get("text") or "").strip()] for para in ((payload.get("narrative") or {}).get("paragraphs") or [])]


def run(pages: dict[str, list[list[dict]]], protect: dict[str, set] | None = None, nli_fn=None) -> dict:
    out = {"stories": 0, "lines": 0, "pairs": 0, "outcomes": {}, "folded": 0, "to_one_sentence": 0, "inspector_repeats": 0,
           "weekday_errors": 0, "unverified": 0, "reader_refused": 0, "stories_with_fold": 0, "stories_with_overlap": 0, "folds": [], "would_fold_not_verified": [], "candidates": [], "conflicts": [],
           "by_story": {}}
    for sid, paras in pages.items():
        paras = [p for p in paras if p]
        if not paras:
            continue
        new, rep = tidy.tidy(paras, protect=(protect or {}).get(sid, frozenset()), nli_fn=nli_fn)
        out["stories"] += 1
        out["lines"] += sum(len(p) for p in paras)
        out["pairs"] += rep["pairs"]
        for k, n in rep["outcomes"].items():
            out["outcomes"][k] = out["outcomes"].get(k, 0) + n
        out["folded"] += rep["folded"]
        out["unverified"] += rep.get("unverified", 0)
        out["reader_refused"] += rep.get("reader_refused", 0)
        out["to_one_sentence"] += rep["to_one_sentence"]
        out["inspector_repeats"] += inspector.inspect(paras).get("repeats", 0)
        out["weekday_errors"] += sum(len(tidy.weekday_errors(x.get("text"))) for p in paras for x in p)
        out["stories_with_fold"] += bool(rep["folded"])
        out["stories_with_overlap"] += bool(rep["outcomes"].get("overlap"))
        out["by_story"][str(sid)] = {"lines": sum(len(p) for p in paras), "folded": rep["folded"], "overlap": rep["outcomes"].get("overlap", 0),
                                     "conflict": rep["outcomes"].get("conflict", 0)}
        for it in rep["items"]:
            row = {"story": sid, **{k: it[k] for k in ("outcome", "cos", "why", "a_text", "b_text")}, "drop": None if it["drop"] is None else ("a" if it["drop"] == it["a"] else "b"),
                   "reader": it.get("reader"), "applied": it["applied"]}
            if it["applied"] == "folded":
                out["folds"].append(row)
            elif str(it["applied"]).startswith(("unverified", "refused: the reader")):
                out["would_fold_not_verified"].append(row)
            elif it["applied"] == "candidate":
                out["candidates"].append(row)
        # conflicts are not in `items` (nothing is applied to them): list them from the judged pairs
        for n, v in tidy.pairs_of(paras):
            if v.outcome == "conflict":
                out["conflicts"].append({"story": sid, "why": v.why, "cos": round(v.cos, 2),
                                         "a_text": paras[n][v.a]["text"], "b_text": paras[n][v.b]["text"]})
    for k in ("folds", "would_fold_not_verified", "candidates", "conflicts"):
        out[k + "_total"] = len(out[k])
        out[k] = out[k][:EXAMPLES]
    out["fold_rate_pct"] = round(100 * out["folded"] / max(1, out["lines"]), 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()
    pages: dict[str, list[list[dict]]] = {}
    protect: dict[str, set] = {}
    if args.file:
        data = json.load(open(args.file))
        if isinstance(data, list):
            data = {str(p.get("story_id", k)): lines_of(p) for k, p in enumerate(data)}
        pages = {str(k): v for k, v in data.items()}
    else:
        from sqlalchemy import text as sql
        from ..config import database_url
        from ..db import Store
        store = Store(database_url())
        with store.engine.begin() as c:
            for sid, payload in c.execute(sql("select story_id, payload_en from published order by updated_at desc limit :n"), {"n": args.limit}):
                if payload:
                    pages[str(sid)] = lines_of(payload)
                    protect[str(sid)] = {int(i) for i in (payload.get("lead") or []) if isinstance(i, int)}
    report = {"code": run(pages, protect)}
    try:
        from .. import nli
        if nli.available():
            report["code_and_reader"] = run(pages, protect, nli_fn=lambda pairs: nli.covers(pairs))
            a = {(r["story"], r["a_text"], r["b_text"]) for r in report["code"]["folds"]}
            report["reader_added_folds"] = [r for r in report["code_and_reader"]["folds"] if (r["story"], r["a_text"], r["b_text"]) not in a]
        else:
            report["code_and_reader"] = {"available": False}
    except Exception as e:  # noqa: BLE001
        report["code_and_reader"] = {"error": str(e)[:120]}
    report["thresholds"] = {k: getattr(tidy, k) for k in ("COVER", "OVERLAP", "HELD", "QUESTION", "NEAR", "NEW_ROOTS")}
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    if not args.file:
        try:
            from sqlalchemy import text as sql
            with store.readers.engine.begin() as c:
                c.execute(sql("insert into diagnostics (kind, report) values ('tidy_shadow', :r)"),
                          {"r": json.dumps(report, ensure_ascii=False, default=str)})
        except Exception as e:  # noqa: BLE001
            print("diagnostics not written:", e)


if __name__ == "__main__":
    main()

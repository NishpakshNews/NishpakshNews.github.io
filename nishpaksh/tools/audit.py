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


def fidelity_report(store: Store, articles_limit: int = 600) -> dict:
    """The fidelity checks (fidelity.py) over stored data, no model: (1) every live page's Hindi strings against
    their English ones; (2) the statements read from the newest articles that still have their text, against the
    sentence of the report each came from. Counts by problem, with a few examples."""
    import collections
    from .. import fidelity as F, heavy, names as N
    out: dict = {"translation": {"strings": 0, "with_problem": 0, "problems": {}, "examples": []},
                 "reading": {}}
    tp: collections.Counter = collections.Counter()
    for r in store.rows(select(published.c.payload_en, published.c.payload_hi)):
        en, hi = audit.hindi_strings(r["payload_en"] or {}), audit.hindi_strings(r["payload_hi"] or {})
        if len(en) != len(hi) or [f for f, _ in en] != [f for f, _ in hi]:
            continue
        for (field, e), (_, h) in zip(en, hi):
            out["translation"]["strings"] += 1
            probs = [p for p in F.check_translation(e, h, strict_only=False)]
            if probs:
                out["translation"]["with_problem"] += 1
                tp.update(p.kind if p.kind == "latin" else str(p) for p in probs)
                if len(out["translation"]["examples"]) < 30 and any(p.kind in ("lost", "added") for p in probs):
                    out["translation"]["examples"].append({"field": field, "en": e[:300], "hi": h[:300],
                                                           "problems": [str(p) for p in probs]})
    out["translation"]["problems"] = dict(tp.most_common())
    reg = N.load(store)
    arts = store.rows(select(articles.c.id, articles.c.lang).where(articles.c.extracted_at.is_not(None),
                                                                    articles.c.text.is_not(None))
                      .order_by(articles.c.id.desc()).limit(articles_limit))
    texts = {r["id"]: r["text"] for r in heavy.fill(store, store.rows(
        select(articles.c.id, *heavy.columns(store, "text")).where(articles.c.id.in_([a["id"] for a in arts] or [-1]))),
        "text")}
    lang = {a["id"]: (a["lang"] or "en") for a in arts}
    rows = store.rows(select(claims.c.article_id, claims.c.text).where(claims.c.article_id.in_(list(texts) or [-1]),
                                                                       claims.c.kind != "relation"))
    for lg in ("hi", "en"):
        c: collections.Counter = collections.Counter()
        ex = []
        n = found = flagged = 0
        for r in rows:
            if lang.get(r["article_id"]) != lg or not r["text"]:
                continue
            n += 1
            win, probs = F.check_reading(r["text"], texts.get(r["article_id"]) or "", lg, reg, strict_only=False)
            if win is None:
                continue
            found += 1
            if probs:
                flagged += 1
                c.update(str(p) for p in probs)
                if len(ex) < 30 and any(p.strict for p in probs):
                    ex.append({"statement": r["text"][:300], "source": win[:300], "problems": [str(p) for p in probs]})
        out["reading"][lg] = {"statements": n, "source_found": found, "with_problem": flagged,
                              "problems": dict(c.most_common()), "examples": ex}
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
    try:
        report["fidelity"] = fidelity_report(store)
    except Exception as e:  # noqa: BLE001 - one part failing must not lose the rest of the audit
        log.exception("fidelity report failed")
        report["fidelity"] = {"error": f"{type(e).__name__}: {str(e)[:500]}"}
    print(json.dumps({k: v for k, v in report.items() if k != "per_story"}, ensure_ascii=False, indent=1))
    with store.readers.engine.begin() as c:      # diagnostics live in Supabase (db.READER_TABLES), not the newsroom copy
        c.execute(sql("insert into diagnostics (kind, report) values ('audit', :r)"),
                  {"r": json.dumps(report, ensure_ascii=False)})
    log.info("audit: %d live articles", len(rows))


if __name__ == "__main__":
    main()

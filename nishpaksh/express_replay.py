"""Audit the express concerns on stored headlines (read-only; nothing is written).

The concerns (config/express.yaml, risk.py) are definition sentences read by the local entailment model, with one untuned bar
(`concern_min`). The headlines the express gate already judged are the evidence to tune them against, and the first (word-list)
design left its verdicts on them: `excluded` with the word that fired, `yes` for the ones it let through. This compares:

  - for the headlines the old lists excluded: how many the definitions also exclude, and the ones they would let through (a
    word list that over-excluded, or a definition that is too narrow: read the headlines to know which);
  - for the headlines that passed: the ones the definitions would exclude (what the word lists missed);
  - how many headlines each definition fires on, and the strongest score of each group in tenths (to set the bar).

    python -m nishpaksh.express_replay            # the report on every stored judged headline

Needs the real model (the runner: the `audit` workflow); `audit()` is plain code (rows in, report out)."""
from __future__ import annotations

import sys
from collections import Counter, defaultdict

from . import express, risk


def audit(rows: list[dict], definitions: dict, apply_: dict, bar: float) -> dict:
    """rows: {title, lead?, lane, verdict, why}. Report: {"old_excluded": {group: {n, also, missed: [titles]}},
    "passed": {n, would_exclude: [(title, reason)]}, "by_definition": {name: n}, "spread": {"excluded": {tenth: n}, "passed": {tenth: n}},
    "unread": n}."""
    texts = [risk.text_of(r.get("title"), r.get("lead")) for r in rows]
    one = risk.scores(texts, [r.get("lane") for r in rows], definitions, apply_)
    old: dict[str, dict] = defaultdict(lambda: {"n": 0, "also": 0, "missed": []})
    passed = {"n": 0, "would_exclude": []}
    by_def: Counter = Counter()
    spread = {"excluded": Counter(), "passed": Counter()}
    unread = 0
    for r, s in zip(rows, one):
        now = risk.decide(s, bar)
        if now is risk.UNREAD:
            unread += 1
        elif now:
            by_def[now] += 1
        top = max((p for p in s.values() if p is not None), default=None)
        kind = r.get("verdict")
        if kind == "excluded":
            g = express.reason_group(r.get("why")) or "?"
            old[g]["n"] += 1
            if now and now is not risk.UNREAD:
                old[g]["also"] += 1
            elif now is None:
                old[g]["missed"].append(r.get("title"))
            if top is not None:
                spread["excluded"][int(top * 10)] += 1
        elif kind == "yes":
            passed["n"] += 1
            if now and now is not risk.UNREAD:
                passed["would_exclude"].append((r.get("title"), now))
            if top is not None:
                spread["passed"][int(top * 10)] += 1
    return {"old_excluded": dict(old), "passed": passed, "by_definition": dict(by_def),
            "spread": {k: dict(sorted(v.items())) for k, v in spread.items()}, "unread": unread}


def stored_rows(store) -> list[dict]:
    from sqlalchemy import select
    from .db import articles
    rows = []
    for r in store.rows(select(articles.c.title, articles.c.url, articles.c.extraction)
                        .where(articles.c.extraction.is_not(None))):
        v = express.verdict_of(r)
        if v and v.get("verdict") in ("excluded", "yes"):
            rows.append({"title": r["title"], "url": r["url"], "lane": v.get("lane"), "verdict": v["verdict"], "why": v.get("why")})
    return rows


def main(argv: list[str]) -> None:
    from .config import database_url
    from .db import Store
    c = express.cfg()
    rep = audit(stored_rows(Store(database_url())), c.get("concerns") or {}, c.get("apply") or {},
                float(c.get("concern_min", risk.DEFAULT_MIN)))
    print(f"unread by the model: {rep['unread']}")
    for g, d in sorted(rep["old_excluded"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"\nold {g}: {d['n']} excluded, {d['also']} also excluded now, {len(d['missed'])} would pass now")
        for t in d["missed"][:12]:
            print("   would pass:", (t or "")[:110])
    p = rep["passed"]
    print(f"\npassed before: {p['n']}, {len(p['would_exclude'])} would be excluded now")
    for t, why in p["would_exclude"][:15]:
        print(f"   {why}: {(t or '')[:110]}")
    print("\nfires on (stored headlines):", rep["by_definition"])
    print("strongest score in tenths:", rep["spread"])


if __name__ == "__main__":
    main(sys.argv[1:])

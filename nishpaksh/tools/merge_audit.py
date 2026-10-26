"""Why do same-meaning lines stay apart? (read-only, no model quota; runs the REAL embedding and NLI models on the runner.)

For each story: its merged statements ("canonical") with the articles behind each; every pair of statements from different
articles whose embeddings are close is read by `relate.relate` (code), NLI in both directions, and judged: same /
one-way covers / contradiction / neutral. The report counts what the rebuilt matcher WOULD merge or fold now, against what
the stored run did (the statements are still separate), with example pairs and scores. Writes one `diagnostics` row kind
'merge_audit'.

    python -m nishpaksh.tools.merge_audit 44582 45418      # no ids: the three newest published stories
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter

from sqlalchemy import text as sql

from ..config import database_url
from ..db import Store

PAIRS_MAX = 120          # pairs read by NLI per story (closest first); CPU: ~2 passes a pair
BUDGET_SECONDS = 600     # the whole run stops starting new stories after this
STORIES = 3              # when no ids are typed
EXAMPLES = 12


def classify(code: str, f, b, nli) -> str:
    """Pure: relate's verdict + NLI (forward, backward) -> same / a_covers_b / b_covers_a / conflict / different / unread."""
    if f is None or b is None:
        return "unread"
    if max(f[2], b[2]) >= nli.CONTRA:
        return "conflict"
    if code == "different":
        return "different"
    fe, be = f[0] >= nli.ENTAIL, b[0] >= nli.ENTAIL
    if fe and be:
        return "same"
    if fe:
        return "a_says_b"          # a entails b: a is the detailed line, b the short one
    if be:
        return "b_says_a"
    return "neutral"


def clusters(n: int, edges: list[tuple[int, int]]) -> int:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in edges:
        parent[find(a)] = find(b)
    return len({find(i) for i in range(n)})


def audit_story(items: list[dict]) -> dict:
    """items: [{id, text, arts: set(article ids)}]. Returns counts and examples."""
    from .. import embed, nli, relate
    texts = [i["text"] for i in items]
    out: dict = {"statements": len(items), "stored_single_article": sum(1 for i in items if len(i["arts"]) == 1)}
    if len(items) < 2:
        return out
    v, how = embed.vectors(texts)
    sim = v @ v.T
    thr = embed.PROPOSE[how]
    cand = [(float(sim[a, b]), a, b) for a in range(len(items)) for b in range(a + 1, len(items))
            if sim[a, b] >= thr and not (items[a]["arts"] & items[b]["arts"])]
    cand.sort(reverse=True)
    out.update(method=how, threshold=thr, proposed=len(cand))
    cand = cand[:PAIRS_MAX]
    pairs = [(texts[a], texts[b]) for _s, a, b in cand]
    print("  embedded", len(items), "statements;", len(pairs), "pairs to NLI", flush=True)
    both = nli.both(pairs)
    kinds: Counter = Counter()
    ex: dict[str, list] = {}
    same_edges, cover_edges = [], []
    for (s, a, b), r in zip(cand, both):
        code = relate.relate(texts[a], texts[b])
        k = classify(code, r[0] if r else None, r[1] if r else None, nli)
        kinds[f"{k}|code:{code}"] += 1
        if k == "same":
            same_edges.append((a, b))
        elif k in ("a_says_b", "b_says_a"):
            cover_edges.append((a, b))
        if len(ex.setdefault(k, [])) < EXAMPLES:
            ex[k].append({"sim": round(s, 3), "code": code, "a": texts[a][:220], "b": texts[b][:220],
                          "ent": [round(r[0][0], 2), round(r[1][0], 2)] if r else None,
                          "con": [round(r[0][2], 2), round(r[1][2], 2)] if r else None})
    out["pairs_read"] = len(cand)
    out["kinds"] = dict(kinds)
    out["statements_after_merging_same"] = clusters(len(items), same_edges)
    out["statements_after_folding_covers"] = clusters(len(items), same_edges + cover_edges)
    out["examples"] = ex
    return out


def _write(store, report: dict) -> None:
    try:
        with store.readers.engine.begin() as c:
            c.execute(sql("insert into diagnostics (kind, report) values ('merge_audit', :r)"),
                      {"r": json.dumps(report, ensure_ascii=False, default=str)})
    except Exception as e:  # noqa: BLE001
        print("diagnostics not written:", e)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", type=int)
    a = ap.parse_args()
    store = Store(database_url())
    with store.engine.connect() as c:
        if not a.ids:
            a.ids = [r[0] for r in c.execute(sql("select story_id from published order by updated_at desc limit 3"))]
        report: dict = {}
        t0 = time.time()
        for sid in a.ids:
            if time.time() - t0 > BUDGET_SECONDS:
                print("budget used; stories left out:", sid, flush=True)
                break
            can = [dict(r) for r in c.execute(sql("select id, text from canonical where story_id = :s order by id"), {"s": sid}).mappings()]
            arts: dict[int, set] = {}
            for r in c.execute(sql("select canonical_id, article_id from claims where story_id = :s and canonical_id is not null"), {"s": sid}):
                arts.setdefault(r[0], set()).add(r[1])
            items = [{"id": x["id"], "text": x["text"], "arts": arts.get(x["id"], set())} for x in can if x["text"]]
            try:
                report[str(sid)] = audit_story(items)
            except Exception as e:  # noqa: BLE001
                report[str(sid)] = {"error": str(e)[:300]}
            r = report[str(sid)]
            _write(store, {str(sid): r})                   # each story is kept as soon as it is done
            print(round(time.time() - t0), "s", sid, {k: r.get(k) for k in ("statements", "proposed", "pairs_read", "statements_after_merging_same",
                                              "statements_after_folding_covers")}, flush=True)


if __name__ == "__main__":
    main()

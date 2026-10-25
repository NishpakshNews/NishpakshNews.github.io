"""The single audit (B19/B21): every new system measured once, on the runner, against what the newsroom already decided.

    python -m nishpaksh.tools.evaluate

Sections (each isolated: one failing never hides the others), written as ONE row in `diagnostics` (kind 'evaluate'):
  claim_matching  the newsroom's own answered pairs (table pair_labels) scored by (a) relate's code verdict, (b) the
                  Fellegi-Sunter weight, (c) the fitted logistic model when there is one: recall at PRECISION_TARGET and the size
                  of the middle band (how many questions a model would still be asked)
  nli             the NLI cross-encoder on the same pairs: score distribution per label, and the thresholds that would give the
                  target precision (read nli.ENTAIL / CONTRA / UNSURE against this)
  writing         the inspector's counts over the live pages (opens with a pronoun, no antecedent, repeats, unintroduced,
                  no focus, time going back), per article
  thresholds      the untuned guesses named in CLAUDE.md, with the values in force, so the report is read in one place
Nothing is tuned here: the report is read once, then settings are changed once.
"""
from __future__ import annotations

import json
import statistics

PRECISION_TARGET = 0.99


def recall_at_precision(scores: list[float], labels: list[bool], target: float = PRECISION_TARGET) -> dict:
    """Highest recall of "same" over thresholds whose precision is at least `target` (scores: higher = more likely same)."""
    pos = sum(labels)
    if not pos:
        return {"recall": None, "threshold": None, "n": len(labels), "positives": 0}
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    tp = fp = 0
    best = {"recall": 0.0, "threshold": None}
    for k, i in enumerate(order):
        tp += labels[i]
        fp += not labels[i]
        nxt = scores[order[k + 1]] if k + 1 < len(order) else None
        if nxt == scores[i]:
            continue                                   # a tie is taken whole
        if tp / (tp + fp) >= target and tp / pos > best["recall"]:
            best = {"recall": round(tp / pos, 4), "threshold": scores[i]}
    return {**best, "n": len(labels), "positives": pos}


def score_pairs(rows: list[dict]) -> dict:
    from .. import dupescore, fellegisunter as fs
    from ..idf import Weights
    from ..relate import Profile, relate
    profs = [(Profile(r["a"]), Profile(r["b"])) for r in rows]
    labels = [bool(r["label"]) for r in rows]
    rank = {"different": 0.0, "ask": 1.0, "ask_a_covers_b": 1.0, "ask_b_covers_a": 1.0, "a_covers_b": 2.0, "b_covers_a": 2.0, "same": 3.0}
    code = [rank.get(relate(r["a"], r["b"], None, None, pa, pb), 1.0) for r, (pa, pb) in zip(rows, profs)]
    gam = [fs.gamma(pa, pb) for pa, pb in profs]
    model = fs.fit(gam)
    out = {"pairs": len(rows), "positives": sum(labels), "code_verdict": recall_at_precision(code, labels)}
    if model is not None:
        w = [model.weight(g) for g in gam]
        out["fellegi_sunter"] = recall_at_precision(w, labels)
        out["fellegi_sunter"]["middle_band"] = sum(fs.LOWER < x < fs.UPPER for x in w)
    if dupescore._model:                                # noqa: SLF001
        weights = Weights([t for r in rows for t in (r["a"], r["b"])])
        p = [dupescore.prob(dupescore.features(pa, pb, weights)) or 0.0 for pa, pb in profs]
        out["logistic"] = recall_at_precision(p, labels)
    return out


def nli_scores(rows: list[dict], limit: int = 300) -> dict:
    from .. import nli
    rows = rows[:limit]
    res = nli.both([(r["a"], r["b"]) for r in rows])
    got = [(min(x[0][0], x[1][0]), r["label"]) for x, r in zip(res, rows) if x is not None]
    if not got:
        return {"available": False}
    pos = [s for s, y in got if y]
    neg = [s for s, y in got if not y]
    summ = lambda v: {"n": len(v), "median": round(statistics.median(v), 3) if v else None}   # noqa: E731
    return {"available": True, "same": summ(pos), "different": summ(neg),
            "both_ways_entailment": recall_at_precision([s for s, _ in got], [bool(y) for _, y in got]),
            "thresholds": {"ENTAIL": nli.ENTAIL, "CONTRA": nli.CONTRA, "UNSURE": nli.UNSURE}}


def writing(pages: list[dict]) -> dict:
    keys = ["opens_with_pronoun", "pronoun_without_antecedent", "repeats", "unintroduced", "pronoun_without_focus", "time_back"]
    tot = {k: 0 for k in keys}
    seen = 0
    for p in pages:
        ins = ((p.get("narrative") or {}).get("flow") or {}).get("inspector")
        if not ins:
            continue
        seen += 1
        for k in keys:
            tot[k] += int(ins.get(k, 0))
    return {"articles": seen, **tot, "per_article": {k: round(v / seen, 3) for k, v in tot.items()} if seen else {}}


def thresholds() -> dict:
    out = {}
    for mod, names in [("nli", ["ENTAIL", "CONTRA", "UNSURE"]), ("fidelity", ["SUPPORT", "CONTRA"]), ("threads", ["LINK"]),
                       ("belong", ["KEEP_SIMILARITY"]), ("truth", ["BELIEF_MIN"]), ("checkworthy", ["SURE"]),
                       ("events", ["MARGIN", "MIN_N", "SURE"]), ("fellegisunter", ["UPPER", "LOWER"])]:
        try:
            m = __import__(f"nishpaksh.{mod}", fromlist=["x"])
            for n in names:
                out[f"{mod}.{n}"] = getattr(m, n, None)
        except Exception as e:  # noqa: BLE001
            out[mod] = f"unavailable: {str(e)[:60]}"
    return out


def main() -> None:
    from sqlalchemy import text as sql
    from ..config import database_url
    from ..db import Store
    store = Store(database_url())
    report: dict = {}

    def section(name, fn):
        try:
            report[name] = fn()
        except Exception as e:  # noqa: BLE001
            report[name] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}

    rows: list[dict] = []
    try:
        with store.engine.begin() as c:
            rows = [dict(r._mapping) for r in c.execute(sql("select a, b, label from pair_labels order by id desc limit 3000"))]
    except Exception as e:  # noqa: BLE001
        report["pair_labels"] = {"error": str(e)[:100]}
    section("claim_matching", lambda: score_pairs(rows) if rows else {"pairs": 0})
    section("nli", lambda: nli_scores(rows) if rows else {"available": False})
    pages: list[dict] = []
    try:
        with store.engine.begin() as c:
            pages = [r[0] for r in c.execute(sql("select payload from published order by updated_at desc limit 200")) if r[0]]
    except Exception as e:  # noqa: BLE001
        report["published"] = {"error": str(e)[:100]}
    section("writing", lambda: writing(pages))
    section("thresholds", thresholds)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    try:
        with store.readers.engine.begin() as c:
            c.execute(sql("insert into diagnostics (kind, report) values ('evaluate', :r)"),
                      {"r": json.dumps(report, ensure_ascii=False, default=str)})
    except Exception as e:  # noqa: BLE001
        print("diagnostics not written:", e)


if __name__ == "__main__":
    main()

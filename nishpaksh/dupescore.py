"""A small calibrated model that ranks "same fact?" pairs (B16 step 3), trained on the newsroom's own decisions.

Every pair the twice-asked question (match.same_facts) answers is kept with its final answer (`pair_labels`): a distant
supervision whose labels are as good as that question. Once there are enough of both kinds, a logistic regression on a few
features (IDF-weighted word overlap, shared names, number agreement, negation agreement, time compatibility) is fitted
once a day and kept in `model_state`. WHAT IT DOES: it orders the pairs to ask, so the per-consolidation cap
(consolidate.SAME_ASK_MAX) is spent on the likeliest pairs instead of the closest ones. WHAT IT NEVER DOES: merge anything
or skip a question; the twice-asked question and the code checks still decide. With no fitted model the order is unchanged.
"""
from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger("nishpaksh.dupescore")

MIN_LABELS = 200
MIN_PER_CLASS = 30
KEEP_DAYS = 45
REFRESH_HOURS = 20
NAME = "dupescore"

_model: dict | None = None


def features(pa, pb, weights) -> list[float]:
    """Profile pair (relate.Profile) -> numbers in 0..1."""
    wa, wb = set(pa.roots), set(pb.roots)
    union = wa | wb
    overlap = (sum(weights.w(w) for w in wa & wb) / sum(weights.w(w) for w in union)) if union else 0.0
    names = (len(pa.names & pb.names) / len(pa.names | pb.names)) if (pa.names | pb.names) else 1.0
    nums = 1.0 if pa.nums == pb.nums else (len(pa.nums & pb.nums) / len(pa.nums | pb.nums) if (pa.nums | pb.nums) else 1.0)
    return [overlap, names, nums, 1.0 if pa.neg == pb.neg else 0.0, 1.0 if pa.date == pb.date else 0.0]


def set_model(m: dict | None) -> None:
    global _model
    _model = m


def prob(feats: list[float]) -> float | None:
    if not _model:
        return None
    import math
    z = _model["b"] + sum(w * f for w, f in zip(_model["w"], feats))
    return 1 / (1 + math.exp(-z))


def order(pairs: list[tuple[int, int]], prof: dict, texts: dict, times: dict | None = None) -> list[tuple[int, int]]:
    """The same pairs, likeliest first (stable). Unchanged when no model is fitted."""
    if not _model:
        try:                                  # no labelled model yet: the unsupervised Fellegi-Sunter weight orders the questions
            from . import fellegisunter
            return fellegisunter.order(pairs, prof, times)
        except Exception:                     # noqa: BLE001
            return list(pairs)
    if len(pairs) < 2:
        return list(pairs)
    from .idf import Weights
    weights = Weights(list(texts.values()))
    scored = [(prob(features(prof[a], prof[b], weights)) or 0.0, k, p) for k, p in enumerate(pairs) for a, b in [p]]
    return [p for _s, _k, p in sorted(scored, key=lambda t: (-t[0], t[1]))]


# ------------------------------------------------------------------ keeping labels and fitting
def record(store, labelled: list[tuple[str, str, bool]]) -> None:
    """Remember answered pairs (never an unanswered one). Best effort: a failure never stops consolidation."""
    if not labelled:
        return
    try:
        from sqlalchemy import insert
        from .db import pair_labels
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        with store.route(insert(pair_labels)).engine.begin() as c:
            c.execute(insert(pair_labels), [dict(a=a[:400], b=b[:400], label=bool(y), created_at=now) for a, b, y in labelled])
    except Exception as e:  # noqa: BLE001
        log.info("dupescore: labels not kept (%s)", str(e)[:80])


def fit(rows: list[dict]) -> dict | None:
    """Logistic regression on labelled pairs [{a, b, label}], or None when there is too little of either kind."""
    from .idf import Weights
    from .relate import Profile
    pos = sum(1 for r in rows if r["label"])
    if len(rows) < MIN_LABELS or pos < MIN_PER_CLASS or len(rows) - pos < MIN_PER_CLASS:
        return None
    from sklearn.linear_model import LogisticRegression
    weights = Weights([t for r in rows for t in (r["a"], r["b"])])
    X = [features(Profile(r["a"]), Profile(r["b"]), weights) for r in rows]
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=500).fit(X, [1 if r["label"] else 0 for r in rows])
    return {"w": [float(x) for x in clf.coef_[0]], "b": float(clf.intercept_[0]), "n": len(rows), "pos": pos}


def load(store) -> bool:
    try:
        from sqlalchemy import select
        from .db import model_state
        row = store.one(select(model_state.c.data).where(model_state.c.name == NAME))
    except Exception:  # noqa: BLE001
        row = None
    set_model(row["data"] if row and row.get("data") else None)
    try:
        from . import contrast
        c = store.one(select(model_state.c.data).where(model_state.c.name == contrast.NAME))
        contrast.set_learned((c or {}).get("data") or [])
    except Exception:  # noqa: BLE001
        pass
    return _model is not None


def refresh(store) -> dict | None:
    """Once a day: fit on the kept labels, store the model, drop old labels. None when it ran recently."""
    from sqlalchemy import delete, insert, select
    from .db import model_state, pair_labels
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    last = store.one(select(model_state.c.updated_at).where(model_state.c.name == NAME))
    if last and last["updated_at"] and now - last["updated_at"] < dt.timedelta(hours=REFRESH_HOURS):
        return None
    store.exec(delete(pair_labels).where(pair_labels.c.created_at < now - dt.timedelta(days=KEEP_DAYS)))
    kept = store.rows(select(pair_labels.c.a, pair_labels.c.b, pair_labels.c.label))
    m = fit(kept)
    try:
        from . import contrast
        words = contrast.learn(kept)
        with store.route(insert(model_state)).engine.begin() as c:
            c.execute(delete(model_state).where(model_state.c.name == contrast.NAME))
            c.execute(insert(model_state).values(name=contrast.NAME, data=words, updated_at=now))
        contrast.set_learned(words)
    except Exception as e:  # noqa: BLE001
        log.info("contrast: not learned (%s)", str(e)[:80])
    with store.route(insert(model_state)).engine.begin() as c:
        c.execute(delete(model_state).where(model_state.c.name == NAME))
        c.execute(insert(model_state).values(name=NAME, data=m, updated_at=now))
    set_model(m)
    return {"fitted": bool(m), **({"n": m["n"]} if m else {})}

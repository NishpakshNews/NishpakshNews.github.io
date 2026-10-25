"""dupescore.py: ranks pairs, never decides; needs enough labels of both kinds."""
import random

import pytest

from nishpaksh import dupescore
from nishpaksh.relate import Profile


@pytest.fixture(autouse=True)
def _reset():
    dupescore.set_model(None)
    yield
    dupescore.set_model(None)


def _rows(n=240):
    rng = random.Random(3)
    base = ["Police arrested the site engineer in Kesarganj", "Two people died in the flyover collapse",
            "The minister announced a probe into the contractor", "Heavy rain fell on Monday night in Patna"]
    rows = []
    for i in range(n):
        a = rng.choice(base)
        if i % 2 == 0:
            rows.append(dict(a=a, b=a.replace("Police", "The police"), label=True))
        else:
            rows.append(dict(a=a, b=rng.choice([b for b in base if b != a]), label=False))
    return rows


def test_too_few_labels_fit_nothing():
    assert dupescore.fit(_rows(50)) is None
    only_yes = [dict(r, label=True) for r in _rows(240)]
    assert dupescore.fit(only_yes) is None


def test_fitted_model_ranks_the_likelier_pair_first_and_order_is_stable_without_one():
    texts = {1: "Police arrested the site engineer in Kesarganj", 2: "The police arrested the site engineer in Kesarganj",
             3: "Heavy rain fell on Monday night in Patna"}
    prof = {i: Profile(t) for i, t in texts.items()}
    pairs = [(1, 3), (1, 2)]
    assert dupescore.order(pairs, prof, texts) == pairs                    # no model: unchanged
    m = dupescore.fit(_rows())
    assert m and m["n"] == 240
    dupescore.set_model(m)
    assert dupescore.order(pairs, prof, texts) == [(1, 2), (1, 3)]


def test_labels_round_trip_and_refresh_fits_once_a_day(tmp_path):
    from nishpaksh.db import Store
    store = Store(f"sqlite:///{tmp_path / 'n.db'}")
    store.init()
    dupescore.record(store, [(r["a"], r["b"], r["label"]) for r in _rows()])
    out = dupescore.refresh(store)
    assert out["fitted"] and dupescore.refresh(store) is None
    dupescore.set_model(None)
    assert dupescore.load(store)

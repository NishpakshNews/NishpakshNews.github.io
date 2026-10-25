import random

import numpy as np

from nishpaksh import positions


def _world(sides: bool, verbosity: bool, seed: int = 0):
    rng = random.Random(seed)
    units = [f"o{k}" for k in range(8)]
    side = {u: (1 if k < 4 else -1) for k, u in enumerate(units)}
    talk = {u: (2.0 if k % 2 else -1.0) for k, u in enumerate(units)} if verbosity else {u: 0.0 for u in units}
    per = {}
    for s in range(40):
        items = []
        for _ in range(8):
            lean = rng.choice([1, -1])
            d = {}
            for u in units:
                z = talk[u] * 0.8 + (1.6 * lean * side[u] if sides else 0)
                d[u] = int(rng.random() < 1 / (1 + np.exp(-z)))
            if len(set(d.values())) > 1:
                items.append(("omission", d))
        per[s] = items
    return per, units


def test_curveball_keeps_both_margins():
    per, units = _world(True, True)
    null = positions._curveball(per, random.Random(1))
    for u in units:
        assert sum(d.get(u, 0) for v in per.values() for _, d in v) == sum(d.get(u, 0) for v in null.values() for _, d in v)
    for sid in per:
        assert [sum(d.values()) for _, d in per[sid]] == [sum(d.values()) for _, d in null[sid]]


def test_planted_sides_are_recovered_even_with_verbosity():
    per, units = _world(True, True)
    th = positions.fit([it for v in per.values() for it in v], units)
    side = np.array([1 if k < 4 else -1 for k in range(8)])
    assert abs(np.corrcoef(th, side)[0, 1]) >= 0.9


def test_verbosity_alone_leaves_no_stable_sides():
    per, units = _world(False, True)
    real = positions._measure(per, units, 8, 1)
    null = [positions._measure(positions._curveball(per, random.Random(k)), units, 5, 2 + k) for k in range(3)]
    assert real["separated"] <= max(x["separated"] for x in null) + 0.15

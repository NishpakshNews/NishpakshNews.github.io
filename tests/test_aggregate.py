from nishpaksh import aggregate


def test_prior_only_below_min_items_and_agreement_passes():
    post, _, _ = aggregate.fit([[1, 1, 1], [0, 0, 0]])
    assert post[0] > 0.95 and post[1] < 0.05


def test_lone_yes_against_two_noes_is_blocked():
    post, _, _ = aggregate.fit([[1, 0, 0]])
    assert post[0] < aggregate.POSTERIOR_MIN


def test_missing_judges_are_absent_not_no():
    post, _, _ = aggregate.fit([[1, None, None]])
    assert abs(post[0] - 0.8) < 1e-9


def test_em_learns_a_noisy_judge():
    import random
    random.seed(3)
    rows = []
    for _ in range(300):
        t = random.random() < 0.5
        good = int(t) if random.random() < 0.95 else int(not t)
        ok = int(t) if random.random() < 0.9 else int(not t)
        noisy = int(t) if random.random() < 0.6 else int(not t)
        rows.append([good, ok, noisy])
    _, rel, _ = aggregate.fit(rows)
    acc = [(s + p) / 2 for s, p in rel]
    assert acc[0] > acc[1] > acc[2]


def test_a_lone_judge_is_not_gated():
    assert aggregate.gate([("a b c", "x y z")], [True]) == [True]


def test_gate_never_turns_no_into_yes():
    out = aggregate.gate([("Five men were arrested", "Five men were arrested")], [False])
    assert out == [False]
    assert aggregate.gate([("a", "b")], [None]) == [None]

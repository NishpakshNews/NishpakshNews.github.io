from nishpaksh.perspectives import pair_means


def _rows(*vals):
    return [dict(story_id=i + 1, a="A", b="B", value=v) for i, v in enumerate(vals)]


def test_a_story_with_more_evidence_counts_for_more():
    rows = _rows(1.0, -1.0)
    plain = pair_means(rows, {})
    assert plain[("A", "B")] == 0.0
    heavy = pair_means(rows, {(1, "A", "B"): 9.0, (2, "A", "B"): 1.0})
    assert abs(heavy[("A", "B")] - 0.8) < 1e-9


def test_pairs_without_a_stored_weight_count_as_one_and_a_single_story_is_not_enough():
    assert pair_means(_rows(0.5), {(1, "A", "B"): 5.0}) == {}
    assert abs(pair_means(_rows(0.2, 0.4), {(1, "A", "B"): 0.0})[("A", "B")] - 0.3) < 1e-9

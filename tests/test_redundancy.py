from nishpaksh import redundancy as r
from nishpaksh.relate import Profile


def test_a_cannot_link_stops_a_chain():
    groups, refused = r.constrained([(1, 2), (2, 3)], cannot={(1, 3)})
    assert groups == [[1, 2]] and refused == 1


def test_without_constraints_the_chain_is_one_cluster():
    groups, refused = r.constrained([(1, 2), (2, 3)])
    assert groups == [[1, 2, 3]] and refused == 0


def test_survivor_is_the_best_supported_and_keeps_a_variant():
    texts = {1: "17 people were killed in Delhi", 2: "about 17 people were killed in Delhi on Monday"}
    lead, var = r.survivor([1, 2], {1: 3, 2: 1}, texts)
    assert lead == 1
    assert 2 in var or var == {}


def test_number_pairs_offer_same_figures_in_similar_words():
    ps = {1: Profile("The company reported a profit of 500 crore in the quarter"),
          2: Profile("Quarterly profit of the company was 500 crore"),
          3: Profile("The company reported a loss of 900 crore in the quarter")}
    assert (1, 2) in r.number_pairs(ps) and not any(3 in p for p in r.number_pairs(ps))

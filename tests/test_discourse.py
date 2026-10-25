from nishpaksh import discourse


def _run(sentences):
    return discourse.inspect([[{"text": t} for t in sentences]])


def test_a_surname_before_the_full_name_is_unintroduced():
    r = _run(["Kabir said the road is shut.", "Humayun Kabir is the district magistrate."])
    assert r["unintroduced"] == 1


def test_full_name_first_then_surname_is_fine():
    r = _run(["Humayun Kabir said the road is shut.", "Kabir added that the bridge fell."])
    assert r["unintroduced"] == 0


def test_a_date_going_backwards_without_a_word_is_counted():
    r = _run(["The bridge fell on 12 October 2026.", "The tender was issued on 3 March 2026."])
    assert r["time_back"] == 1
    r = _run(["The bridge fell on 12 October 2026.", "The tender had been issued on 3 March 2026."])
    assert r["time_back"] == 0

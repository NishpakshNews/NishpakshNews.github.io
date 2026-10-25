from nishpaksh import split


def test_a_piece_set_that_loses_a_content_word_is_refused():
    o = "The minister inaugurated the new bridge in Patna and announced a metro extension to Gaya"
    ok = ["The minister inaugurated the new bridge in Patna", "The minister announced a metro extension to Gaya"]
    lost = ["The minister inaugurated the bridge in Patna", "The minister announced an extension to Gaya"]
    assert split.why_not(o, ok) is None or split.why_not(o, ok) != "words_lost"
    assert split._uncovered(o, lost)
    assert not split._uncovered(o, ok)


def test_belong_answers_are_read_from_the_first_listed_tag():
    from nishpaksh import belong
    assert belong._norm("History / background") == "history"
    assert belong._norm("lead-up.") == "leadup"
    assert belong._norm("it is unclear") is None


def test_topics_join_whole_topics_whatever_the_link_order(monkeypatch):
    from nishpaksh import belong, dupes, plan, narrative
    import types
    items = [{"id": k, "text": f"t{k}"} for k in range(1, 7)]
    groups = [[1, 2], [3, 4], [5, 6]]
    monkeypatch.setattr(dupes, "topics", lambda *a, **k: groups)
    monkeypatch.setattr(narrative, "ordered_items", lambda p: items)
    store = types.SimpleNamespace(one=lambda q: {"analysis": {}}, exec=lambda q: None)
    results = []
    for order in (("l3", "l5"), ("l5", "l3")):
        its = [dict(i) for i in items]
        links = {3: [1], 5: [3]} if order[0] == "l3" else {5: [3], 3: [1]}
        monkeypatch.setattr(plan, "_links", lambda i, links=links: links.get(i["id"], []))
        monkeypatch.setattr(narrative, "ordered_items", lambda p, its=its: its)
        belong.assign_topics(store, object(), 1, {})
        results.append([i["topic"] for i in its])
    assert results[0] == results[1] == [0, 0, 0, 0, 0, 0]

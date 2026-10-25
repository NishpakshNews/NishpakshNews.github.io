import pytest

from nishpaksh import events, order


@pytest.fixture(autouse=True)
def learned_course(monkeypatch):
    """What events.refresh learns from dated stories: detained early, charged, then released. Verbs by a stand-in."""
    events.set_ranks({"detain": 0.1, "charge": 0.4, "release": 0.8})
    lem = {"detained": "detain", "released": "release", "charged": "charge"}
    monkeypatch.setattr(events, "verb_lemma", lambda t: next((v for k, v in lem.items() if k in t), None))
    yield
    events.set_ranks({})


def item(i, text, start=None, precision="day"):
    return {"id": i, "text": text, "time": {"start": start, "end": start, "precision": precision} if start else {}}


def test_detained_comes_before_released_on_the_same_day_whatever_the_input_order():
    items = [item(1, "He was released on bail", "2026-10-15T00:00:00"), item(2, "Police detained him", "2026-10-15T00:00:00")]
    assert [i["id"] for i in order.chronological(items)] == [2, 1]


def test_days_decide_before_stages():
    items = [item(1, "Police detained him", "2026-10-16T00:00:00"), item(2, "He was released on bail", "2026-10-15T00:00:00")]
    assert [i["id"] for i in order.chronological(items)] == [2, 1]


def test_a_clock_time_is_not_overruled_by_the_usual_course():
    items = [item(1, "He was released", "2026-10-15T09:00:00", "minute"), item(2, "Police detained him", "2026-10-15T11:00:00", "minute")]
    assert [i["id"] for i in order.chronological(items)] == [1, 2]


def test_undated_statements_keep_their_order_after_the_dated_ones():
    items = [item(1, "Background A"), item(2, "Police detained him", "2026-10-15T00:00:00"), item(3, "Background B")]
    assert [i["id"] for i in order.chronological(items)] == [2, 1, 3]


def test_a_stated_relation_orders_undated_statements_and_a_cycle_does_not_fail():
    items = [item(1, "Background A"), item(2, "Background B")]
    assert [i["id"] for i in order.chronological(items, [(2, 1)])] == [2, 1]
    assert len(order.chronological(items, [(2, 1), (1, 2)])) == 2


def test_close_ranks_and_unknown_verbs_make_no_order():
    assert events.earlier(0.1, 0.8) is True and events.earlier(0.8, 0.1) is False
    assert events.earlier(0.4, 0.45) is None and events.earlier(None, 0.5) is None

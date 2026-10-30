"""Tense from the day (tense.py) and the bracket of a gloss (refs.py), owner Oct 30 2026 (stories 48583, 49893)."""
import datetime as dt

import pytest

from nishpaksh import nlp, refs, tense

NOW = dt.datetime(2026, 10, 30, 4, 0)


@pytest.fixture
def real_parser():
    old = nlp._parser
    nlp.set_parser(None)
    if nlp._doc("A test.") is None:
        nlp.set_parser(old)
        pytest.skip("spaCy model not installed")
    nlp._parse_cache.clear()
    yield
    nlp.set_parser(old)
    nlp._parse_cache.clear()


def _by(day_end=None, published=None, i=1):
    return {i: {"id": i, "time": {"end": day_end} if day_end else {}, "sources": [{"published_at": published}] if published else []}}


def test_item_day_prefers_its_own_end_then_first_report():
    assert tense.item_day(_by("2026-10-06T23:59")[1]) == dt.date(2026, 10, 6)
    assert tense.item_day(_by(published="2026-10-28T10:00")[1]) == dt.date(2026, 10, 28)
    assert tense.item_day({"time": {}, "sources": []}) is None


def test_a_sentence_is_past_only_when_every_statement_is(real_parser):
    by = {**_by("2026-10-06T23:59", i=1), **_by("2026-10-30T23:59", i=2), **_by(i=3)}
    today = dt.date(2026, 10, 30)
    assert tense.is_past([1], by, today)
    assert not tense.is_past([1, 2], by, today)      # one is today's
    assert not tense.is_past([1, 3], by, today)      # one has no day: code never guesses
    assert not tense.is_past([], by, today)


def test_present_auxiliaries_become_past_outside_quotes(real_parser):
    assert tense.to_past("On Tuesday, voting is taking place in Assam.") == "On Tuesday, voting was taking place in Assam."
    assert tense.to_past("Vote counting will take place on 9 October.") == "Vote counting would take place on 9 October."
    out = tense.to_past('The court said "the roll is being revised" and counting is being held.')
    assert 'roll is being revised' in out and 'counting was being held' in out
    assert tense.to_past("The firm is a Mumbai-based company.") is None       # a copula is not an event


def test_article_fix_changes_only_past_sentences(real_parser):
    by = {**_by("2026-10-06T23:59", i=1), **_by("2026-10-30T23:59", i=2)}
    paras = [[{"text": "Voting is taking place in Assam.", "ids": [1]}, {"text": "Counting is taking place in Delhi.", "ids": [2]}]]
    assert tense.fix_article(paras, by, NOW) == 1
    assert paras[0][0]["text"] == "Voting was taking place in Assam."
    assert paras[0][1]["text"] == "Counting is taking place in Delhi."


def test_the_lead_of_an_old_event_names_its_day(real_parser):
    by = _by(published="2026-10-28T10:00")
    paras = [[{"text": "Bharatiya Janata Party won the Lucknow teacher seat.", "ids": [1]}]]
    assert tense.name_lead_day(paras, ["news"], by, NOW)
    assert paras[0][0]["text"].startswith("On 28 October, Bharatiya Janata Party won")
    paras = [[{"text": "The party won the seat.", "ids": [1]}]]
    tense.name_lead_day(paras, ["news"], by, NOW)
    assert paras[0][0]["text"] == "On 28 October, the party won the seat."


def test_a_lead_with_a_day_or_a_todays_fact_is_left_alone(real_parser):
    by = _by(published="2026-10-28T10:00")
    paras = [[{"text": "On Wednesday the party won the seat.", "ids": [1]}]]
    assert not tense.name_lead_day(paras, ["news"], by, NOW)
    today = _by(published="2026-10-30T01:00")
    paras = [[{"text": "The party won the seat.", "ids": [1]}]]
    assert not tense.name_lead_day(paras, ["news"], today, NOW)


def test_an_undated_statement_tells_the_writer_when_it_was_first_reported():
    from nishpaksh import narrative
    item = {"id": 1, "kind": "event", "text": "The party won the seat.", "verdict": "unverified", "n_sources": 1,
            "n_articles": 1, "sources": [{"published_at": "2026-10-28T10:00"}], "time": {}}
    line = narrative._statement_line(item)
    assert "first reported: 28 October" in line


def test_a_gloss_never_carries_a_bracket_it_did_not_open():
    src = "The court looked at the special intensive revision (SIR) in West Bengal on Wednesday."
    ref = {"head": "revision", "mods": ["special", "intensive"]}
    assert refs.find_antecedent(ref, src) == "SIR"
    assert not refs.balanced("SIR) in West Bengal")
    assert refs.usable_gloss("SIR) in West Bengal", "the revision", src) is None
    assert refs.gloss_text("during the special intensive revision.", [{"phrase": "special intensive revision",
                           "gloss": "SIR) in West Bengal"}], "", set()) == ("during the special intensive revision.", 0)

"""Context for learned entries (context.py): sightings grouped into senses, applied only where the context fits."""
import datetime as dt
import itertools

import pytest

from nishpaksh import context as C

RIVER = ["Villages on the bank of the Kosi were flooded after the river rose",
         "The river bank gave way and floodwater entered villages",
         "Flood relief camps were set up along the river bank near villages"]
MONEY = ["The bank raised its loan rates after the central bank policy",
         "Customers queued at the bank to withdraw deposits from their accounts",
         "The bank reported higher loan growth and deposits this quarter"]


def keys():
    c = itertools.count(1)
    return lambda: f"s{next(c)}"


def build(sentences_by_section):
    senses, new = {}, keys()
    for section, sents in sentences_by_section:
        for s in sents:
            C.assign(senses, section, C.words(s, "en", "bank"), new)
    got = {}
    for k, sense in senses.items():                      # the senses left after joining
        got.setdefault(sense.section, set()).add(k)
    return senses, got


def test_words_are_content_words_without_names_numbers_or_the_word_itself():
    assert C.words("Villages on the bank of the Kosi were flooded on 15 October", "en", "bank") == {"villag", "flood"}
    from nishpaksh.names import fold_hi
    assert fold_hi("बाढ़") in C.words("कोसी नदी के किनारे बसे गांवों में बाढ़ आई", "hi", "किनारे")   # folded: बाढ
    assert "किनारे" not in C.words("कोसी नदी के किनारे बसे गांवों में बाढ़ आई", "hi", "किनारे")


def test_two_contexts_make_two_senses_not_rivals():
    senses, got = build([("weather", RIVER), ("markets", MONEY)])
    assert len(got["weather"]) == 1 and len(got["markets"]) == 1 and got["weather"] != got["markets"]
    river, money = got["weather"].pop(), got["markets"].pop()
    assert senses[river].sightings == 3 and senses[money].sightings == 3
    assert {"river", "villag", "flood"} <= senses[river].signature()


def test_a_new_sentence_uses_only_the_sense_its_context_matches():
    senses, got = build([("weather", RIVER), ("markets", MONEY)])
    river, money = got["weather"].pop(), got["markets"].pop()
    w = C.words("Floodwater from the river reached villages near the bank", "en", "bank")
    assert C.best(senses, "weather", w) == river
    assert C.best(senses, "markets", C.words("The bank cut loan rates for deposits", "en", "bank")) == money
    # a context never saved: nothing is used (not the commonest sense)
    assert C.best(senses, "courts", C.words("The court heard the matter near the bank", "en", "bank")) is None
    # the right words in the wrong section: nothing
    assert C.best(senses, "markets", w) is None


def test_an_unknown_section_needs_more_shared_words():
    senses, got = build([("weather", RIVER)])
    river = got["weather"].pop()
    assert C.best(senses, "", C.words("The river flooded villages", "en", "bank")) == river           # 3 words
    assert C.best(senses, "", C.words("The river bank collapsed", "en", "bank")) is None             # 1 word


def test_a_sighting_that_bridges_two_senses_of_a_section_joins_them():
    senses = {"a": C.Sense("markets", 1, {"loan": 1}), "b": C.Sense("markets", 1, {"deposit": 1})}
    k = C.assign(senses, "markets", {"loan", "deposit"}, lambda: "new")
    assert list(senses) == [k] and senses[k].sightings == 3


def test_a_tie_between_senses_uses_nothing():
    senses = {"a": C.Sense("weather", 5, {"river": 3, "flood": 3}), "b": C.Sense("weather", 5, {"river": 3, "flood": 3})}
    assert C.best(senses, "weather", {"river", "flood"}) is None


def test_section_of_and_round_trip():
    assert C.section_of({"primary": ["justice"], "secondary": ["courts"]}) == "courts"
    assert C.section_of({"primary": ["business"]}) == "business" and C.section_of(None) == ""
    s = C.Sense("courts", 2, {"bail": 2})
    assert C.Sense.from_dict(s.to_dict()) == s


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_story_sections_come_from_published_pages(store):
    from nishpaksh.db import insert, published
    store.exec(insert(published).values(story_id=7, version=1, updated_at=dt.datetime(2026, 10, 16),
                                        payload_en={"category": {"primary": ["business"], "secondary": ["markets"]}}))
    assert C.story_sections(store, [7, 8]) == {7: "markets"}

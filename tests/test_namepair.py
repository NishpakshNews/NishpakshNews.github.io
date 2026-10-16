"""Pairing a story's names before reading (namepair.py, session 4): the model points, code checks every answer
against the Hindi outlet's own words, and Hindi readings get the English outlets' spellings."""
import datetime as dt
import json
import types

import pytest

from nishpaksh import names as N
from nishpaksh import namepair as P

EN1 = ("Prime Minister Narendra Modi will inaugurate the new terminal of Kushok Bakula Rimpochee Airport in Leh. "
       "Lieutenant Governor Kavinder Gupta said the work was done. Modi will also open a park. The Supreme Court "
       "and the BJP were not involved.")
EN2 = "Modi will open the Kushok Bakula Rimpochee Airport terminal, Kavinder Gupta said."
HI = ("प्रधानमंत्री नरेंद्र मोदी लेह में कुशोक बकुला रिम्पोछे हवाई अड्डे के नए टर्मिनल का उद्घाटन करेंगे। "
      "उपराज्यपाल कविंदर गुप्ता ने कहा कि काम पूरा हो गया है।")
HI2 = "मोदी ने कुशोक बकुला रिम्पोछे हवाई अड्डे का दौरा किया। कविंदर गुप्ता भी मौजूद थे।"


def test_english_names_are_people_and_places_as_spelt():
    got = P.english_names(EN1)
    assert "Narendra Modi" in got and "Kushok Bakula Rimpochee" in got   # "Airport" is translated, not spelt
    assert "Kavinder Gupta" in got
    assert not any("Supreme" in g or g == "BJP" for g in got)        # bodies and acronyms are not spellings
    assert "Lieutenant" not in " ".join(got)                         # titles taken off


def test_answers_must_be_copied_agree_and_match_word_counts():
    names = ["Narendra Modi", "Kavinder Gupta", "Rahul Gandhi", "Rimpochee"]
    first = ["नरेंद्र मोदी", "कविंदर गुप्ता", "राहुल गांधी", "रिम्पोछे"]       # राहुल गांधी is not in the report
    second = list(reversed(["नरेंद्र मोदी", "कविन्दर गुप्ता", "राहुल गांधी", "रिम्पोछे"]))
    got = P.agreed(names, first, second, [HI])
    assert got == {"Narendra Modi": "नरेंद्र मोदी", "Rimpochee": "रिम्पोछे"}  # Gupta: answers differ
    assert P.agreed(["Narendra Modi"], ["मोदी"], ["मोदी"], [HI]) == {}       # one word for a two-word name
    assert P.agreed(["Rimpochee", "Rimpoche"], ["रिम्पोछे"] * 2, ["रिम्पोछे"] * 2, [HI]) == {}  # used twice
    assert P.agreed(["Kavinder Gupta"], ["NONE"], ["NONE"], [HI]) == {}


def test_in_text_is_whole_words_only():
    assert P.in_text("मोदी", HI, "hi")
    assert not P.in_text("मोद", HI, "hi")


class Router:
    """Copies the right words from the report, like an honest model; counts calls."""
    table = {"Narendra Modi": "नरेंद्र मोदी", "Kavinder Gupta": "कविंदर गुप्ता", "Kushok Bakula Rimpochee": "कुशोक बकुला रिम्पोछे",
             "Leh": "लेह"}

    def __init__(self, remaining=10):
        self.remaining, self.calls = remaining, 0

    def remaining_now(self, tier):
        assert tier == "quality"
        return self.remaining

    def call(self, tier, prompt, **kw):
        assert tier == "quality"
        self.calls += 1
        items = [l.split(". ", 1)[1] for l in prompt.split("English names:")[1].split("HINDI REPORT")[0].strip().splitlines()]
        return types.SimpleNamespace(data={"names": [self.table.get(i, "NONE") for i in items]}, text="")


T = dt.datetime(2026, 10, 16)


def test_learn_then_confirm_without_a_call_then_hint():
    reg = N.Registry()
    r = Router()
    en = [dict(text=EN1, source="owner:ht"), dict(text=EN2, source="owner:et")]
    hi = [dict(text=HI, source="owner:au"), dict(text=HI2, source="owner:n18")]
    stored = P.learn_story(r, reg, 1, en, hi, T)
    assert stored and r.calls == 2                                    # asked twice, names in both orders
    assert reg.hindi("Rimpochee").form == "रिम्पोछे"
    p = reg.pairs[("Rimpochee", "रिम्पोछे")]
    assert sorted(p.en_sources) == ["owner:et", "owner:ht"] and sorted(p.hi_sources) == ["owner:au", "owner:n18"]
    assert p.status == "seen"
    # a second story: the stored forms are in the Hindi text, so no question
    r2 = Router()
    P.learn_story(r2, reg, 2, en, hi, T)
    assert r2.calls == 0 and p.status == "attested"
    # a Hindi-only story later: its reading gets the English outlets' spelling
    block = P.hint_block(P.hints("कुशोक बकुला रिम्पोछे हवाई अड्डे पर मोदी पहुंचे", reg))
    assert "कुशोक बकुला रिम्पोछे = Kushok Bakula Rimpochee" in block and "मोदी = Modi" in block


def test_no_quota_means_no_question_and_nothing_breaks():
    reg = N.Registry()
    r = Router(remaining=0)
    assert P.learn_story(r, reg, 1, [dict(text=EN1, source="owner:a")], [dict(text=HI, source="owner:b")], T) == 0
    assert r.calls == 0

    class Refuses(Router):
        def call(self, *a, **k):
            from nishpaksh.router import QuotaExhausted
            raise QuotaExhausted("quality: no key")
    assert P.learn_story(Refuses(), reg, 1, [dict(text=EN1, source="owner:a")], [dict(text=HI, source="owner:b")], T) == 0


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_prepare_learns_saves_and_hints_hindi_articles_only(store):
    pending = [
        dict(id=1, story_id=9, lang="en", outlet="Hindustan Times", url="https://www.hindustantimes.com/a", text=EN1),
        dict(id=2, story_id=9, lang="hi", outlet="Amar Ujala", url="https://www.amarujala.com/b", text=HI),
        dict(id=3, story_id=10, lang="hi", outlet="News18 Hindi", url="https://hindi.news18.com/c", text=HI2),
    ]
    out = P.prepare(store, Router(), pending)
    assert set(out) == {2, 3}                                         # the English article gets no block
    assert "Rimpochee" in out[3]                                      # learned from story 9, used in story 10
    assert N.load(store).hindi("Gupta").form == "गुप्ता"


def test_prepare_never_raises(store):
    class Broken:
        def remaining_now(self, tier):
            raise RuntimeError("boom")
    P.prepare(store, Broken(), [dict(id=1, story_id=1, lang="hi", text=HI)])   # no exception


def test_reading_prompt_carries_the_names_block():
    from nishpaksh.extract import EXTRACT_PROMPT
    p = EXTRACT_PROMPT.format(outlet="o", published="p", title="t", text="x", part="", names=P.hint_block([("मोदी", "Modi")]))
    assert "मोदी = Modi" in p and p.index("मोदी = Modi") < p.index("Return ONE JSON")

"""A reading checked against its report (readcheck.py, session 7)."""
import types

import pytest

from nishpaksh import names as N
from nishpaksh import readcheck as R

SRC = ("राहुल गांधी ने कोर्ट में अपनी सफाई में कहा कि उन्होंने किसी पार्टी का नाम नहीं लिया। "
       "राहुल गांधी ने कहा कि उन्होंने अपने बयान में भाजपा या किसी राजनीतिक दल का सीधे नाम नहीं लिया था।")
METRO = "एसजी तुषार मेहता ने कहा कि 10 अक्टूबर को 303 में से केवल 45 स्टेशनों पर रोक लगाई गई थी।"


def reg():
    r = N.Registry()
    r.add_manual("Gandhi", "गांधी")
    return r


class Router:
    def __init__(self, answer, remaining=10):
        self.answer, self.remaining, self.prompts = answer, remaining, []

    def remaining_now(self, tier):
        assert tier == "quality"
        return self.remaining

    def call(self, tier, prompt, **kw):
        assert tier == "quality"
        self.prompts.append(prompt)
        return types.SimpleNamespace(data=self.answer, text="")


@pytest.fixture(autouse=True)
def fresh():
    R.reset_run()
    R.STATS.clear()
    yield
    R.DROP_UNREPAIRED = False


def ex(*texts, stance="asserts"):
    return {"events": [], "claims": [{"id": f"c{k}", "text": t, "stance": stance} for k, t in enumerate(texts)],
            "context": [], "relations": []}


def test_a_lost_word_is_repaired_once_with_the_report_sentence_shown():
    e = ex("He did not name the BJP or any specific political party in his statement, Gandhi said.")
    r = Router({"statements": ["He did not directly name the BJP or any political party in his statement, Gandhi said."]})
    got = R.check(e, SRC, "hi", r, reg())
    assert got["flagged"] == 1 and got["repaired"] == 1
    assert e["claims"][0]["text"].startswith("He did not directly name")
    assert "सीधे" in r.prompts[0] and "drops it" in r.prompts[0] and "adds 'specific" in r.prompts[0]


def test_a_repair_that_changes_numbers_or_still_fails_is_refused():
    st = "Solicitor General Tushar Mehta stated that 45 out of 303 metro stations were closed on October 10."
    e = ex(st)
    got = R.check(e, METRO, "hi", Router({"statements": ["Only 46 of 303 metro stations were closed on 10 October."]}))
    assert got["kept"] == 1 and e["claims"][0]["text"] == st
    e = ex(st)
    assert R.check(e, METRO, "hi", Router({"statements": [st]}))["kept"] == 1
    fixed = "Solicitor General Tushar Mehta stated that only 45 out of 303 metro stations were closed on October 10."
    e = ex(st)
    assert R.check(e, METRO, "hi", Router({"statements": [fixed]}))["repaired"] == 1 and e["claims"][0]["text"] == fixed


def test_a_denial_is_not_checked_for_negation():
    e = ex("Gandhi named the BJP or any political party directly in his statement.", stance="denies")
    r = Router({"statements": ["x"]})
    assert R.check(e, SRC, "hi", r, reg())["flagged"] == 0 and r.prompts == []


def test_no_quota_or_the_cap_keeps_the_reading_as_it_was():
    st = "Solicitor General Tushar Mehta stated that 45 out of 303 metro stations were closed on October 10."
    e = ex(st)
    assert R.check(e, METRO, "hi", Router({}, remaining=0))["kept"] == 1
    R.MAX_CALLS_PER_RUN, old = 0, R.MAX_CALLS_PER_RUN
    try:
        r = Router({"statements": ["x"]})
        R.check(ex(st), METRO, "hi", r)
        assert r.prompts == [] and R.STATS.get("over_cap") == 1
    finally:
        R.MAX_CALLS_PER_RUN = old


def test_dropping_is_a_switch_off_by_default():
    st = "Solicitor General Tushar Mehta stated that 45 out of 303 metro stations were closed on October 10."
    R.DROP_UNREPAIRED = True
    e = ex(st, "Tushar Mehta spoke.")
    e["relations"] = [{"from": "c0", "to": "c1", "type": "before"}]
    assert R.check(e, METRO, "hi", None)["dropped"] == 1
    assert [c["id"] for c in e["claims"]] == ["c1"] and e["relations"] == []


def test_the_reading_prompt_asks_to_keep_the_small_words():
    from nishpaksh.extract import EXTRACT_PROMPT
    assert "सीधे" in EXTRACT_PROMPT and "Never add one" in EXTRACT_PROMPT

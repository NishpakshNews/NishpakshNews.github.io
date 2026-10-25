"""The Hindi page (hindi.py, session 6): names in Devanagari from the registry, the checks, and the edit pass on
the quality tier."""
import datetime as dt
import json
import types

import pytest

from nishpaksh import hindi as H
from nishpaksh import nli
from nishpaksh import names as N

EN = "Amrit Vats and Muhammad Yahya won the boys' doubles title in Djibouti."
DRAFT = "Amrit Vats और Muhammad Yahya ने Djibouti में लड़कों का युगल खिताब जीता।"
NAMES = {"Amrit": "अमृत", "Vats": "वत्स", "Muhammad": "मुहम्मद", "Yahya": "याह्या", "Djibouti": "जिबूती"}


def test_names_by_code_whole_words_brackets_kept():
    assert H.devanagari_names(DRAFT, NAMES) == "अमृत वत्स और मुहम्मद याह्या ने जिबूती में लड़कों का युगल खिताब जीता।"
    assert H.devanagari_names("वत्स (Vats) ने Vatsal से कहा", {"Vats": "वत्स"}) == "वत्स (Vats) ने Vatsal से कहा"


def test_name_parts_are_people_and_places_only():
    got = H.name_parts([EN, "The Supreme Court and the BJP spoke on Monday."])
    assert {"Amrit", "Vats", "Djibouti"} <= set(got)
    assert not {"Supreme", "Court", "BJP", "Monday", "The"} & set(got)


class Router:
    def __init__(self, answer=None, remaining=10):
        self.answer, self.remaining, self.prompts = answer, remaining, []

    def remaining_now(self, tier):
        assert tier == "quality"
        return self.remaining

    def call(self, tier, prompt, **kw):
        assert tier == "quality"
        self.prompts.append(prompt)
        return types.SimpleNamespace(data=self.answer(prompt) if callable(self.answer) else self.answer, text="")


@pytest.fixture(autouse=True)
def scripted_nli():
    """NLI stand-in keyed on the two things these tests turn on: "directly" must be carried (सीधे) and a "not" kept (नहीं)."""
    def fn(pairs):
        out = []
        for a, b in pairs:
            en, hi = (a, b) if a.isascii() else (b, a)
            if "not" in en and "नहीं" not in hi:
                out.append((0.02, 0.08, 0.90))
            elif "directly" in en and "सीधे" not in hi:
                out.append((0.20, 0.75, 0.05) if a.isascii() else (0.95, 0.04, 0.01))
            else:
                out.append((0.95, 0.04, 0.01))
        return out
    nli.set_backend(fn)
    yield
    nli.set_backend(None)


def test_edit_fixes_a_lost_qualifier_and_names_and_is_told_the_problems():
    en = ["Gandhi said he did not directly name the BJP.", EN]
    drafts = {0: "गांधी ने कहा कि उन्होंने भाजपा का नाम नहीं लिया।", 1: DRAFT}
    good = {"0": "गांधी ने कहा कि उन्होंने भाजपा का सीधे नाम नहीं लिया।",
            "1": "अमृत वत्स और मुहम्मद याह्या ने जिबूती में लड़कों का युगल खिताब जीता।"}
    r = Router(good)
    keep, why = H.finish(r, en, drafts, {})
    assert keep == {0: good["0"], 1: good["1"]} and why == {}
    assert "leaves out part of what the English says" in r.prompts[0] and "'Amrit' is still in English letters" in r.prompts[0]


def test_a_worse_edit_is_refused_and_no_quota_keeps_the_draft():
    en = ["Gandhi said he did not directly name the BJP."]
    draft = {0: "गांधी ने कहा कि उन्होंने भाजपा का सीधे नाम नहीं लिया।"}
    worse = Router({"0": "गांधी ने कहा कि उन्होंने भाजपा का नाम लिया।"})          # drops the negation too
    assert H.finish(worse, en, draft, {})[0] == draft
    echo = Router({"0": en[0]})                                                   # an echo is a hard problem
    assert H.finish(echo, en, draft, {})[0] == draft
    assert H.finish(Router({}, remaining=0), en, draft, {})[0] == draft
    assert H.finish(None, en, draft, {})[0] == draft


def test_a_missing_draft_can_come_from_the_edit_and_a_hard_problem_is_never_cached():
    en = ["Rs 3,350 crore projects will open on 15 October."]
    keep, why = H.finish(Router({"0": "15 अक्टूबर को 3,350 करोड़ रुपये की परियोजनाएं खुलेंगी।"}), en, {}, {})
    assert 0 in keep
    keep, why = H.finish(Router({}), en, {0: "परियोजनाएं खुलेंगी।"}, {})            # numbers dropped
    assert keep == {} and why == {0: "numbers changed"}


def test_blocks_list_only_what_the_batch_uses():
    assert H.names_block(NAMES, ["Amrit Vats won."]) == "\nNAMES (write them exactly so): Amrit = अमृत; Vats = वत्स\n"
    assert "आपराधिक मानहानि" in H.terms_block(["a criminal defamation case"]) and H.terms_block(["rain"]) == ""


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_name_map_uses_the_registry_then_transliterates_once(store):
    reg = N.load(store)
    reg.add_evidence("Vats", "वत्स", ["owner:a"], ["owner:b"], 1, dt.datetime(2026, 10, 16))
    N.save(store, reg)
    r = Router({"parts": ["अमृत", "जिबूती"]})                               # Amrit, Djibouti: in reading order
    got = H.name_map(store, r, ["Amrit Vats won in Djibouti."])
    assert got["Vats"] == "वत्स" and got["Amrit"] == "अमृत" and got["Djibouti"] == "जिबूती"
    assert len(r.prompts) == 1                                                    # Vats needed no call


def test_a_name_learned_later_mends_cached_pages(store):
    from nishpaksh import compose
    store.translation_put({compose._key("Vats won."): "Vats जीते।"})
    assert compose.translate_strings(store, None, ["Vats won."]) == {"Vats won.": "Vats जीते।"}
    reg = N.load(store)
    reg.add_evidence("Vats", "वत्स", ["owner:a"], ["owner:b"], 1, dt.datetime(2026, 10, 16))
    N.save(store, reg)
    assert compose.translate_strings(store, None, ["Vats won."]) == {"Vats won.": "वत्स जीते।"}


def test_the_cache_key_follows_the_binding_terms(monkeypatch):
    from nishpaksh import compose
    a = compose._key("x")
    monkeypatch.setattr(H, "cache_version", lambda: "changed")
    assert compose._key("x") != a


def test_translation_prompt_asks_for_devanagari_names_and_lists_them():
    from nishpaksh.compose import TRANSLATE_PROMPT
    p = TRANSLATE_PROMPT.format(payload=json.dumps({"0": EN}), names=H.names_block(NAMES, [EN]), terms="")
    assert "Write names" in p and "Devanagari" in p and "Amrit = अमृत" in p
    assert json.loads(p[p.index("{"):]) == {"0": EN}                             # the batch stays last (tests' fake)

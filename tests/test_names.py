"""The name registry (names.py, session 3 of the translation/learning plan): exact lookup, outlets' own spellings,
the trust bar, the vote, the quality-tier fallback, and the table living only in the newsroom."""
import datetime as dt
import types

import pytest

from nishpaksh import names
from nishpaksh.names import Pair, Registry

T = dt.datetime(2026, 10, 16, 9)


def test_parts_and_pairing_need_equal_counts():
    assert names.parts("Modi's") == ["Modi"]
    assert names.parts("Aisam-ul-Haq Qureshi") == ["Aisam-ul-Haq", "Qureshi"]
    assert names.pair_parts("Kushok Bakula Rimpochee", "कुशोक बकुला रिम्पोछे") == [
        ("Kushok", "कुशोक"), ("Bakula", "बकुला"), ("Rimpochee", "रिम्पोछे")]
    assert names.pair_parts("Rahul Gandhi", "गांधी") == []           # a lone surname only with a lone surname
    assert names.pair_parts("Gandhi", "Gandhi") == []                # no Devanagari: not a Hindi form


def test_lookup_is_exact_only():
    r = Registry()
    r.add_evidence("Sharma", "शर्मा", ["owner:a"], ["owner:b"], 1, T)
    assert r.hindi("Sharma").form == "शर्मा"
    assert r.hindi("Shrma") is None and r.hindi("Sarma") is None and r.hindi("sharma") is None
    assert r.hindi_name("Rahul Sharma") == (None, ["Rahul"])


def test_trust_bar_needs_two_sources_each_side_and_two_stories():
    r = Registry()
    p = r.add_evidence("Rimpochee", "रिम्पोछे", ["owner:ht", "owner:et"], ["owner:au", "owner:n18"], 1, T)
    assert p.status == "seen"                                        # one story
    r.add_evidence("Rimpochee", "रिम्पोछे", ["owner:ht"], ["owner:au"], 2, T)
    assert p.status == "attested"
    q = r.add_evidence("Vats", "वत्स", ["owner:toi"], ["owner:au"], 1, T)
    r.add_evidence("Vats", "वत्स", ["owner:toi"], ["owner:au"], 2, T)
    assert q.status == "seen"                                        # one source a side, however many stories


def test_state_media_never_counts():
    r = Registry()
    assert r.add_evidence("Vats", "वत्स", [None], ["owner:au"], 1, T) is None
    art = {"outlet": "PIB", "url": "https://pib.gov.in/x"}
    assert names.source_key(art) is None
    assert names.source_key({"outlet": "X", "agency": "PTI"}) == "agency:pti"


def test_most_used_spelling_wins_in_each_language_and_variants_count_together():
    r = Registry()
    for s, story in (("a", 1), ("b", 2), ("c", 3)):
        r.add_evidence("Gandhi", "गांधी", [f"owner:{s}"], [f"owner:h{s}"], story, T)
    r.add_evidence("Gandhi", "गाँधी", ["owner:d"], ["owner:hd"], 4, T)
    r.add_evidence("Gandhi", "गन्धी", ["owner:e"], ["owner:he"], 5, T)
    r.add_evidence("Gandhi", "गन्धी", ["owner:f"], ["owner:hf"], 6, T)
    assert r.hindi("Gandhi").form == "गांधी"                          # 4 sources (with गाँधी) beat 2
    # the English side: the spelling more English outlets used for the same Hindi word
    r.add_evidence("Rimpoche", "रिम्पोछे", ["owner:x"], ["owner:hx"], 7, T)
    for s, story in (("y", 8), ("z", 9)):
        r.add_evidence("Rimpochee", "रिम्पोछे", [f"owner:{s}"], [f"owner:h{s}"], story, T)
    assert r.english("रिम्पोछे").form == "Rimpochee"
    assert r.english_spelling("Rimpoche") == "Rimpochee"            # linked through the outlets' Hindi word only
    assert r.english_spelling("Kumar") == "Kumar"


def test_conflicting_attested_forms_are_flagged_not_overwritten():
    r = Registry()
    for h in ("सरमा", "शर्मा"):
        for s, story in (("a", 1), ("b", 2)):
            r.add_evidence("Sarma", h, [f"owner:{s}{h}"], [f"owner:h{s}{h}"], story, T)
    assert r.conflicts() == [("Sarma", sorted(["सरमा", "शर्मा"]))]
    assert len(r.pairs) == 2


def test_manual_pairs_win_and_seed_states(tmp_path):
    f = tmp_path / "names.yaml"
    f.write_text("pairs:\n  - {en: Amrit Vats, hi: अमृत वत्स}\n", encoding="utf-8")
    r = Registry()
    for s, story in (("a", 1), ("b", 2)):
        r.add_evidence("Vats", "वाट्स", [f"owner:{s}"], [f"owner:h{s}"], story, T)
    names.with_manual(r, f)
    assert r.hindi("Vats") == names.Choice("वत्स", "manual")
    assert r.hindi_name("Uttar Pradesh") == ("उत्तर प्रदेश", [])


class FakeRouter:
    def __init__(self, answer, remaining=10):
        self.answer, self.remaining, self.calls = answer, remaining, []

    def remaining_now(self, tier):
        assert tier == "quality"                                      # never the publication tiers
        return self.remaining

    def call(self, tier, prompt, **kw):
        self.calls.append((tier, prompt))
        return types.SimpleNamespace(data=self.answer, text="")


def test_transliteration_is_validated_and_skipped_without_quota():
    r = FakeRouter({"parts": ["जिबूती", "Djibouti", ""]})
    out = names.transliterate(r, ["Djibouti", "Awayo", "Srouji"], "hi")
    assert out == {"Djibouti": "जिबूती"}                              # an echo and an empty answer are dropped
    assert names.transliterate(FakeRouter({"parts": ["x"]}, remaining=0), ["Djibouti"], "hi") == {}
    assert names.transliterate(FakeRouter({"parts": ["a", "b"]}), ["Djibouti"], "hi") == {}   # wrong count
    from nishpaksh.router import QuotaExhausted

    class NoKey(FakeRouter):
        def call(self, *a, **k):
            raise QuotaExhausted("quality: no key")
    assert names.transliterate(NoKey({}), ["Djibouti"], "hi") == {}


def test_outlets_replace_a_transliteration():
    r = Registry()
    r.add_translated("Vats", "वाट्स", T)
    assert r.hindi("Vats").status == "translated"
    r.add_evidence("Vats", "वत्स", ["owner:a"], ["owner:b"], 1, T)
    assert r.hindi("Vats") == names.Choice("वत्स", "seen")
    assert r.english_spelling("Vats") == "Vats"


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_table_lives_in_the_newsroom_only(store):
    from sqlalchemy import inspect
    assert "name_pairs" in inspect(store.engine).get_table_names()
    assert "name_pairs" not in inspect(store.readers.engine).get_table_names()


def test_resolve_stores_translations_and_round_trips(store):
    r = names.load(store)
    r.add_evidence("Rimpochee", "रिम्पोछे", ["owner:a"], ["owner:b"], 7, T)
    names.save(store, r)
    router = FakeRouter({"parts": ["जिबूती"]})
    got = names.resolve(store, router, ["Rimpochee", "Djibouti"], "hi", when=T)
    assert got["Rimpochee"].form == "रिम्पोछे" and got["Djibouti"] == names.Choice("जिबूती", "translated")
    again = names.resolve(store, FakeRouter({"parts": []}, remaining=0), ["Djibouti"], "hi")
    assert again["Djibouti"].form == "जिबूती"                         # stored: no second call needed
    back = names.load(store)
    assert back.pairs[("Rimpochee", "रिम्पोछे")].stories == [7]
    assert names.resolve(store, None, ["जिबूती"], "en")["जिबूती"].form == "Djibouti"

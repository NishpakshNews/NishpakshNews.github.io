"""bodies.py: Wikidata answers are scripted (the sandbox has no network)."""
from nishpaksh import bodies, voice


def _fake(name, ctx):
    n = bodies.norm(name)
    table = {
        "government of india": [{"id": "Q1", "label": "Government of India", "aliases": ["Union Government", "Central Government"],
                                 "countries": ["Q668"], "gov": True, "court": False}],
        "union government": [{"id": "Q1", "label": "Government of India", "aliases": ["Union Government"],
                              "countries": ["Q668"], "gov": True, "court": False}],
        "supreme court": [{"id": "Q2", "label": "Supreme Court of India", "aliases": [], "countries": ["Q668"], "gov": False, "court": True},
                          {"id": "Q3", "label": "Supreme Court of the United States", "aliases": [], "countries": ["Q30"], "gov": False, "court": True}],
        "bench": [{"id": "Q4", "label": "bench", "aliases": [], "countries": [], "gov": False, "court": False},
                  {"id": "Q5", "label": "bench", "aliases": [], "countries": [], "gov": False, "court": False}],
        "washington post": [{"id": "Q6", "label": "The Washington Post", "aliases": [], "countries": ["Q30"], "gov": False, "court": False}],
    }
    return {"found": True, "candidates": table[n]} if n in table else {"found": False}


def setup_function(_):
    bodies.reset()
    bodies.set_backend(_fake)


def teardown_function(_):
    bodies.set_backend(None)
    bodies.reset()


class _NoStore:
    def rows(self, *a):
        raise RuntimeError("no table")
    def route(self, *a):
        raise RuntimeError("no table")


def test_one_government_however_named():
    bodies.prefetch(_NoStore(), ["Union Government", "the Government of India"])
    assert voice.speaker_key("the Union government") == voice.speaker_key("Government of India") == "gov:Q668"


def test_ambiguous_names_take_the_context_country_or_nothing():
    bodies.prefetch(_NoStore(), ["Supreme Court", "bench"])
    assert voice.speaker_key("the Supreme Court") == "court:Q2"
    assert voice.speaker_key("bench") == "bench"                     # two matches, none in India: own key, no guess


def test_a_newspaper_is_never_a_government_and_unknown_names_keep_their_own_key():
    bodies.prefetch(_NoStore(), ["Washington Post", "the panel"])
    assert voice.speaker_key("Washington Post") == "org:Q6"
    assert voice.speaker_key("the panel") == "panel"


def test_could_not_ask_is_not_an_answer():
    bodies.set_backend(lambda n, c: bodies.UNAVAILABLE)
    st = bodies.prefetch(_NoStore(), ["Union Government", "Supreme Court", "Washington Post"])
    assert st["unavailable"] == 2 and st["found"] == 0               # stops after two failures
    assert bodies.key_for("Union Government") is None and bodies.norm("Union Government") not in bodies._missing


def test_choose_only_on_exact_matches():
    assert bodies.choose("x", {"candidates": []}).key is None

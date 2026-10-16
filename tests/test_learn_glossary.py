"""English-Hindi terms learned from the outlets (learn_glossary.py, session 11): evidence from Hindi and English
outlets on the same stories, a code-only devil's advocate, the owner's file."""
import datetime as dt

import pytest
import yaml

from nishpaksh import learn_glossary as G
from nishpaksh import learning as L
from nishpaksh import names as N

T0 = dt.datetime(2026, 10, 1, 9)
TOPICS = [("flood", "बाढ़"), ("drought", "सूखा"), ("earthquake", "भूकंप"), ("cyclone", "चक्रवात")]


def story(k, en_word, hi_word, day=0, extra_hi=""):
    when = T0 + dt.timedelta(days=day)
    en = [{"source": f"owner:e{k}{i}", "when": when,
           "text": f"Officials said the {en_word} hit villages and the {en_word} relief camps opened"} for i in range(2)]
    hi = [{"source": f"owner:h{k}{i}", "when": when,
           "text": f"अधिकारियों ने कहा कि {hi_word} से गांव प्रभावित हुए और {hi_word} राहत शिविर खुले {extra_hi}"} for i in range(2)]
    return {"en": en, "hi": hi}


def window(n_each=2, start_day=0, extra=None):
    out, k = {}, 0
    for en, hi in TOPICS:
        for j in range(n_each):
            k += 1
            out[k] = story(k, en, hi, day=start_day + j, extra_hi=(extra or {}).get(en, ""))
    return out


def test_pairs_come_from_outlets_and_need_mutual_best_partners():
    found, partners = G.pairs(window())
    got = {(p["en"], p["hi"]) for p in found}
    assert {("flood", "बाढ़"), ("drought", "सूखा"), ("earthquake", "भूकंप"), ("cyclone", "चक्रवात")} <= got
    # words every story shares (villages / गांव, relief / राहत) pair with nothing in particular
    assert not any(p["en"] in ("villages", "relief") for p in found)


def test_names_the_registry_knows_are_not_terms():
    reg = N.Registry()
    reg.add_manual("Baadh", "बाढ़")
    found, _ = G.pairs(window(), reg)
    assert ("flood", "बाढ़") not in {(p["en"], p["hi"]) for p in found}


def accumulate(runs=3):
    cands = {}
    for r in range(runs):
        found, partners = G.pairs(window(start_day=2 * r))
        # new stories each run: renumber
        for p in found:
            p["stories"] = {f"r{r}s{sid}": v for sid, v in p["stories"].items()}
        G.record(cands, found)
    return cands, partners


def test_evidence_adds_up_over_runs_and_a_clean_pair_is_learned():
    cands, partners = accumulate()
    c = cands["flood = बाढ़"]
    assert G.BAR.fails(c) == [] and G.extra_rules(c) == []
    learned, proposed = G.decide(cands, partners=partners)
    assert "flood = बाढ़" in {x.key for x in learned} and c.status == "learned"


def test_a_competing_rendering_goes_to_the_owner_not_into_translations():
    cands, partners = accumulate()
    partners = {"flood": {"बाढ़": 1.0, "सैलाब": 0.7}}
    learned, proposed = G.decide({"flood = बाढ़": cands["flood = बाढ़"]}, partners=partners)
    c = cands["flood = बाढ़"]
    assert c.status == "proposed" and "सैलाब" in c.reason and proposed == [c]


def test_blocks_loaded_words_qualifiers_insults_and_the_owners_refusal():
    cands, partners = accumulate()
    c = cands["drought = सूखा"]
    assert G.advocate(c, loaded={"drought"}).state == "block"
    q = L.Candidate("glossary", "alleged = कथित")
    assert G.advocate(q).state == "block"
    insult = L.Candidate("glossary", "remark = तंज")
    assert G.advocate(insult).state == "block"
    G.decide(cands, partners=partners, struck={"cyclone"})
    assert cands["cyclone = चक्रवात"].status == "blocked"


def test_an_unstable_pair_is_held():
    c = L.Candidate("glossary", "flood = बाढ़")
    for i, d in enumerate([0, 0, 0, 0, 1, 2]):
        c.add(f"s{i}", f"owner:{i}", f"st{i}", L.day_of(T0 + dt.timedelta(days=d)), T0 + dt.timedelta(days=d))
    v = G.advocate(c)
    assert v.state == "hold" and "unstable" in v.reason


def test_the_file_keeps_the_owners_edits_and_has_no_article_text(tmp_path):
    cands, partners = accumulate()
    G.decide(cands, partners=partners)
    path = tmp_path / "glossary_learned.yaml"
    G.write(path, cands, dt.date(2026, 10, 7))
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert {"en": "flood", "hi": "बाढ़"}.items() <= doc["terms"][[t["en"] for t in doc["terms"]].index("flood")].items()
    assert "villages" not in path.read_text(encoding="utf-8")
    # the owner refuses one: next write drops it
    doc["rejected"] = ["flood"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    G.decide(cands, partners=partners, struck={"flood"})
    G.write(path, cands, dt.date(2026, 10, 8))
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["rejected"] == ["flood"] and "flood" not in [t["en"] for t in doc["terms"]]


def test_learned_terms_bind_translations_but_hand_written_ones_win(monkeypatch):
    from nishpaksh import fidelity as F
    monkeypatch.setattr("nishpaksh.learn_glossary.learned_terms",
                        lambda path=None: [("flood", "बाढ़"), ("FIR", "प्राथमिकी")])
    F._learned_terms.cache_clear()
    try:
        assert ("flood", "बाढ़") in F.terms_in("The flood hit Assam")
        assert F.terms_in("An FIR was filed") == [("FIR", "एफआईआर")]           # hand-written wins
        from nishpaksh import hindi
        before = hindi.cache_version()
        assert hindi.cache_version() == before                                 # learned terms never re-translate
    finally:
        F._learned_terms.cache_clear()


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_a_run_on_an_empty_newsroom_writes_a_valid_file(store, tmp_path):
    res = G.run(store, path=tmp_path / "g.yaml")
    assert res["mixed_stories"] == 0
    assert yaml.safe_load((tmp_path / "g.yaml").read_text(encoding="utf-8"))["terms"] == []

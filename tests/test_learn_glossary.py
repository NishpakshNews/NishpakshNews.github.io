"""English-Hindi terms learned from the outlets, by context (learn_glossary.py + context.py): evidence from Hindi and
English outlets on the same stories, one candidate per word, sense and rendering, a code-only devil's advocate, the
owner's file, and translations that bind a learned term only where its context matches."""
import datetime as dt

import pytest
import yaml

from nishpaksh import learn_glossary as G
from nishpaksh import learning as L
from nishpaksh import names as N

T0 = dt.datetime(2026, 10, 1, 9)
TOPICS = [("flood", "बाढ़"), ("drought", "सूखा"), ("earthquake", "भूकंप"), ("cyclone", "चक्रवात")]


def story(k, en_word, hi_word, day=0, aligned=True, en_text=None, hi_text=None):
    """Two English and two Hindi reports of one story; with `aligned` their sentences share a number (40)."""
    when = T0 + dt.timedelta(days=day)
    n_hi = "40" if aligned else "75"
    en_t = en_text or "Officials said the {w} hit 40 villages and the {w} relief camps opened."
    hi_t = hi_text or "अधिकारियों ने कहा कि {w} से {n} गांव प्रभावित हुए और {w} राहत शिविर खुले।"
    en = [{"source": f"owner:e{k}{i}", "when": when, "text": en_t.format(w=en_word)} for i in range(2)]
    hi = [{"source": f"owner:h{k}{i}", "when": when, "text": hi_t.format(w=hi_word, n=n_hi)} for i in range(2)]
    return {"en": en, "hi": hi}


def window(n_each=2, start_day=0):
    out, k = {}, 0
    for en, hi in TOPICS:
        for j in range(n_each):
            k += 1
            out[k] = story(k, en, hi, day=start_day + j)
    return out


def keys_of(cands, en):
    return {k for k in cands if G.split_key(k)[0] == en and cands[k].status != "merged"}


def accumulate(windows, sections_of=None, runs=3):
    cands, senses = {}, {}
    for r in range(runs):
        for w in windows:
            stories = {f"r{r}{sid}": s for sid, s in w(r).items()}
            sections = {sid: sections_of(sid) for sid in stories} if sections_of else {}
            found, _ = G.pairs(stories, None, sections)
            G.record(cands, found, senses)
    return cands, senses


def test_pairs_come_from_aligned_outlets_and_need_mutual_best_partners():
    found, _ = G.pairs(window())
    got = {(p["en"], p["hi"]) for p in found}
    assert {("flood", "बाढ़"), ("drought", "सूखा"), ("earthquake", "भूकंप"), ("cyclone", "चक्रवात")} <= got
    assert not any(p["en"] in ("villages", "relief") for p in found)


def test_names_the_registry_knows_are_not_terms():
    reg = N.Registry()
    reg.add_manual("Baadh", "बाढ़")
    found, _ = G.pairs(window(), reg)
    assert ("flood", "बाढ़") not in {(p["en"], p["hi"]) for p in found}


def test_words_that_only_share_a_story_are_not_paired():
    stories = {k: story(k, en, hi, aligned=False) for k, (en, hi) in enumerate(TOPICS * 2)}
    assert G.pairs(stories)[0] == []


# the owner's example: "bank" is बैंक in markets stories and किनारा by a river
# each sense's Hindi word stands in every story of its section, the words around it only in some (real coverage:
# otherwise every word shared by all stories ties with it)
MONEY = [("The {w} opened 40 new branches and its loan book grew at the {w}.",
          "{w} ने {n} नई शाखाएं खोलीं और {w} का ऋण बढ़ा।"),
         ("Customers of the {w} withdrew deposits after 40 branches shut at the {w}.",
          "{w} के ग्राहकों ने {n} शाखाएं बंद होने पर जमा निकाली।"),
         ("The {w} cut its loan rate and 40 customers took deposits at the {w}.",
          "{w} ने ब्याज घटाया और {n} ग्राहकों ने {w} में जमा रखी।")]
RIVER = [("Floodwater crossed the river {w} and 40 villages near the {w} were evacuated.",
          "{w} टूटने से {n} गांवों में पानी घुसा और {w} के पास लोग निकाले गए।"),
         ("The river rose over its {w} and 40 villages along the {w} went under water.",
          "नदी उफनकर {w} से ऊपर बही और {w} के {n} गांव डूब गए।"),
         ("Villagers repaired the {w} of the river after 40 homes along the {w} flooded.",
          "ग्रामीणों ने नदी का {w} ठीक किया जब {w} के {n} घर डूबे।")]


def bank_windows(r):
    out = {}
    for j in range(3):
        out[f"m{j}"] = story(f"m{r}{j}", "bank", "बैंक", day=r, en_text=MONEY[j][0], hi_text=MONEY[j][1])
        out[f"w{j}"] = story(f"w{r}{j}", "bank", "किनारा", day=r, en_text=RIVER[j][0], hi_text=RIVER[j][1])
    return out


def test_bank_is_two_senses_learned_side_by_side_not_rivals():
    cands, senses = accumulate([bank_windows], lambda sid: "markets" if "m" in sid else "weather", runs=4)
    ks = keys_of(cands, "bank")
    by_hi = {G.split_key(k)[1]: k for k in ks}
    assert set(by_hi) == {"बैंक", "किनारा"} and G.split_key(by_hi["बैंक"])[2] != G.split_key(by_hi["किनारा"])[2]
    learned, proposed = G.decide(cands)
    assert {G.split_key(c.key)[1] for c in learned if G.split_key(c.key)[0] == "bank"} == {"बैंक", "किनारा"}
    assert G.rivals(cands[by_hi["बैंक"]], cands) == []


def test_two_renderings_in_the_same_context_are_rivals_for_the_owner():
    def w(r):
        return {f"a{j}": story(f"a{r}{j}", "flood", "बाढ़" if j == 0 else "सैलाब", day=r) for j in range(2)} | \
            {f"b{j}": story(f"b{r}{j}", "flood", "सैलाब" if j == 0 else "बाढ़", day=r) for j in range(2)}
    cands, _ = accumulate([w], lambda sid: "weather")
    ks = keys_of(cands, "flood")
    if len(ks) == 2:                       # both found: each is the other's rival in the one sense
        c = cands[sorted(ks)[0]]
        assert G.rivals(c, cands)
        G.decide(cands)
        assert all(cands[k].status != "learned" for k in ks)


def test_evidence_adds_up_and_a_clean_pair_is_learned():
    cands, _ = accumulate([lambda r: window(start_day=2 * r)])
    k = next(iter(keys_of(cands, "flood")))
    c = cands[k]
    assert G.BAR.fails(c) == [] and G.extra_rules(c) == []
    learned, _ = G.decide(cands)
    assert k in {x.key for x in learned} and c.status == "learned"


def test_blocks_loaded_words_qualifiers_insults_and_the_owners_refusal():
    cands, _ = accumulate([lambda r: window(start_day=2 * r)])
    c = cands[next(iter(keys_of(cands, "drought")))]
    assert G.advocate(c, loaded={"drought"}).state == "block"
    assert G.advocate(L.Candidate("glossary3", "alleged = कथित @alleged#1")).state == "block"
    assert G.advocate(L.Candidate("glossary3", "remark = तंज @remark#1")).state == "block"
    G.decide(cands, struck={"cyclone"})
    assert cands[next(iter(keys_of(cands, "cyclone")))].status == "blocked"


def test_an_unstable_pair_is_held():
    c = L.Candidate("glossary3", "flood = बाढ़ @flood#1")
    for i, d in enumerate([0, 0, 0, 0, 1, 2]):
        c.add(f"s{i}", f"owner:{i}", f"st{i}", L.day_of(T0 + dt.timedelta(days=d)), T0 + dt.timedelta(days=d))
    v = G.advocate(c)
    assert v.state == "hold" and "unstable" in v.reason


def test_the_file_carries_each_sense_with_its_context_and_keeps_the_owners_edits(tmp_path):
    cands, senses = accumulate([bank_windows], lambda sid: "markets" if "m" in sid else "weather", runs=4)
    G.decide(cands)
    path = tmp_path / "glossary_learned.yaml"
    G.write(path, cands, dt.date(2026, 10, 7), senses)
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    by_hi = {t["hi"]: t for t in doc["terms"] if t["en"] == "bank"}
    assert by_hi["बैंक"]["section"] == "markets" and {"loan", "deposit"} <= set(by_hi["बैंक"]["context"])
    assert by_hi["किनारा"]["section"] == "weather" and {"river", "villag"} <= set(by_hi["किनारा"]["context"])
    assert "evacuated" not in text                                             # context words only, no sentences
    doc["rejected"] = ["bank"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    G.decide(cands, struck={"bank"})
    G.write(path, cands, dt.date(2026, 10, 8), senses)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["rejected"] == ["bank"] and not [t for t in doc["terms"] if t["en"] == "bank"]


BANK_TERMS = [{"en": "bank", "hi": "बैंक", "section": "markets", "context": ["loan", "rate", "deposit"]},
              {"en": "bank", "hi": "किनारा", "section": "weather", "context": ["river", "villag", "flood"]},
              {"en": "FIR", "hi": "प्राथमिकी", "section": "", "context": []}]


@pytest.fixture
def bank_terms(monkeypatch):
    from nishpaksh import fidelity as F
    monkeypatch.setattr("nishpaksh.learn_glossary.learned_terms", lambda path=None: BANK_TERMS)
    F._learned_terms.cache_clear()
    yield F
    F._learned_terms.cache_clear()


def test_a_learned_term_binds_only_where_its_context_matches(bank_terms):
    F = bank_terms
    assert ("bank", "बैंक") in F.terms_in("The bank raised its loan rate for deposits", "markets")
    assert ("bank", "किनारा") in F.terms_in("Villages along the river bank flooded", "weather")
    assert not any(e == "bank" for e, _ in F.terms_in("The court sat near the bank", "courts"))     # new context
    assert not any(e == "bank" for e, _ in F.terms_in("Villages along the river bank flooded", "markets"))
    assert F.terms_in("An FIR was filed") == [("FIR", "एफआईआर")]                  # hand-written wins
    from nishpaksh import hindi
    before = hindi.cache_version()
    assert hindi.cache_version() == before                                     # learned terms never re-translate


def test_a_new_context_keeps_the_models_choice_as_a_temporary_sense(bank_terms, tmp_path):
    from nishpaksh import hindi
    from nishpaksh.db import Store
    store = Store(f"sqlite:///{tmp_path / 'n.db'}")
    store.init()
    hindi.SECTION.set("courts")
    en = "The court sat near the river bank where the villages flooded"
    choices = hindi.temporary_choices(en, "अदालत नदी के किनारा के पास बैठी जहां गांवों में बाढ़ आई")
    assert [(c["en"], c["hi"], c["section"]) for c in choices] == [("bank", "किनारा", "courts")]
    hindi.save_temps(store, choices)
    hindi.TEMPS.set(hindi.load_temps(store))
    assert ("bank", "किनारा") in hindi.terms_for("Water rose at the river bank and villages flooded")
    hindi.SECTION.set("markets")                       # the learned sense of the section comes first
    assert ("bank", "बैंक") in hindi.terms_for("The bank raised its loan rate for deposits")
    hindi.SECTION.set("")
    hindi.TEMPS.set(())


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

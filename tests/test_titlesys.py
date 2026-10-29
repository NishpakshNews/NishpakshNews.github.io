"""The analyser answers who is a person and what the title is; the lists are the fallback (owner, Oct 28 2026)."""
from nishpaksh import auditcount, nlp, people, titles, titlesys
from nishpaksh.nlp import Ent, Tok


def _setup(monkeypatch, text, toks, ents):
    """toks: [(word, pos, dep, head_index)] in order; ents: [(substring, label)]."""
    out, pos = [], 0
    for i, (w, p, d, h) in enumerate(toks):
        st = text.index(w, pos)
        pos = st + len(w)
        out.append(Tok(i, w, st, pos, w.lower(), p, p, d, h))
    monkeypatch.setattr(nlp, "_parser", lambda t: out if t == text else None)
    monkeypatch.setattr(nlp, "_backend", lambda t: [Ent(s, lab, text.index(s), text.index(s) + len(s)) for s, lab in ents] if t == text else [])
    nlp._parse_cache.clear()
    nlp._cache.clear()
    titlesys.reset()


TEXT = "Assam Chief Minister Himanta Biswa Sarma said it."
TOKS = [("Assam", "PROPN", "compound", 2), ("Chief", "PROPN", "compound", 2), ("Minister", "PROPN", "compound", 5),
        ("Himanta", "PROPN", "compound", 5), ("Biswa", "PROPN", "compound", 5), ("Sarma", "PROPN", "nsubj", 6),
        ("said", "VERB", "ROOT", 6), ("it", "PRON", "dobj", 6), (".", "PUNCT", "punct", 6)]


def test_the_title_is_the_noun_run_before_the_person(monkeypatch):
    _setup(monkeypatch, TEXT, TOKS, [("Himanta Biswa Sarma", "PERSON")])
    a = TEXT.index("Himanta")
    assert titlesys.title_start(TEXT, a) == 0
    assert titles.title_before(TEXT, "Himanta Biswa Sarma") == "Assam Chief Minister"


def test_the_system_wins_and_a_disagreement_with_the_list_is_counted(monkeypatch):
    text = "Veteran Sarma said it."
    _setup(monkeypatch, "Zorbo Handler Sarma said it.", [("Zorbo", "PROPN", "compound", 1), ("Handler", "NOUN", "compound", 2),
                                                          ("Sarma", "PROPN", "nsubj", 3), ("said", "VERB", "ROOT", 3), ("it", "PRON", "dobj", 3), (".", "PUNCT", "punct", 3)],
           [("Sarma", "PERSON")])
    t = "Zorbo Handler Sarma said it."
    assert titles.title_before(t, "Sarma") == "Zorbo Handler"       # a title the list has never heard of
    assert auditcount.snapshot()["titles"]["title:differ"] == 1
    assert "system:Zorbo Handler | list:-" in titlesys.snapshot_examples()["title"][0][0]


def test_an_adjective_touching_the_run_leaves_it_to_the_list(monkeypatch):
    t = "Former Chief Minister Sarma said it."
    _setup(monkeypatch, t, [("Former", "ADJ", "amod", 2), ("Chief", "PROPN", "compound", 2), ("Minister", "PROPN", "compound", 3),
                            ("Sarma", "PROPN", "nsubj", 4), ("said", "VERB", "ROOT", 4), ("it", "PRON", "dobj", 4), (".", "PUNCT", "punct", 4)],
           [("Sarma", "PERSON")])
    assert titlesys.title_start(t, t.index("Sarma")) is None
    assert titles.title_before(t, "Sarma") == "Former Chief Minister"   # the list answers whole
    assert auditcount.snapshot()["titles"]["title:undecided"] >= 1


def test_not_a_person_or_no_part_of_speech_is_not_decided(monkeypatch):
    t = "Supreme Court said it."
    _setup(monkeypatch, t, [("Supreme", "PROPN", "compound", 1), ("Court", "PROPN", "nsubj", 2), ("said", "VERB", "ROOT", 2),
                            ("it", "PRON", "dobj", 2), (".", "PUNCT", "punct", 2)], [("Supreme Court", "ORG")])
    assert titlesys.title_start(t, t.index("Court")) is None
    monkeypatch.setattr(nlp, "_parser", None)
    nlp._parse_cache.clear()
    assert titlesys.title_start(t, 0) is None


def test_people_clean_takes_the_person_entity_and_falls_back_to_the_list(monkeypatch):
    t = "Zorbo Handler Sarma said it."
    _setup(monkeypatch, t, [("Zorbo", "PROPN", "compound", 1), ("Handler", "NOUN", "compound", 2), ("Sarma", "PROPN", "nsubj", 3),
                            ("said", "VERB", "ROOT", 3), ("it", "PRON", "dobj", 3), (".", "PUNCT", "punct", 3)], [("Sarma", "PERSON")])
    assert people._clean("Zorbo Handler Sarma", t, 0) == "Sarma"
    assert people._clean("Chief Minister Siddaramaiah") == "Siddaramaiah"     # no text: the list


def test_a_title_with_in_the_lok_sabha_is_cut_whole_or_not_at_all():
    t = "Leader of the Opposition in the Lok Sabha Rahul Gandhi said it."
    assert titles.title_before(t, "Rahul Gandhi") == "Leader of the Opposition in the Lok Sabha"
    t2 = "He was in the Lok Sabha Rahul Gandhi said it."
    assert titles.title_before(t2, "Rahul Gandhi") == ""          # "in the Lok Sabha" alone is no title


def test_the_longer_title_wins_when_system_and_list_disagree(monkeypatch):
    t = "Lok Sabha Leader of Opposition Rahul Gandhi said it."
    a = t.index("Rahul")
    listed = titles.title_start(t[:a])
    assert listed == 0
    assert titlesys.compare_title(a, listed, t, a) == 0           # the system said "no title": the list's full title stands
    assert titlesys.compare_title(5, listed, t, a) == 0           # a shorter system run never cuts the list's title
    assert titlesys.compare_title(0, a, t, a) == 0                # a title only the system knows is kept


def test_a_blended_introduction_title_no_report_writes_is_replaced_by_the_codes():
    from nishpaksh import style
    srcs = ["Chief Minister Himanta Biswa Sarma said the road is open.", "Union Home Minister Himanta Biswa Sarma said the fund is set."]
    blend = [[{"text": "Union Chief Minister Himanta Biswa Sarma said the road is open."}, {"text": "Sarma said the fund is set."}]]
    style.shorten_names(blend, speakers=["Himanta Biswa Sarma"], sources=srcs)
    assert blend[0][0]["text"] == "Union Home Minister Himanta Biswa Sarma said the road is open."
    ok = [[{"text": "Chief Minister Himanta Biswa Sarma said the road is open."}]]
    style.shorten_names(ok, speakers=["Himanta Biswa Sarma"], sources=srcs)
    assert ok[0][0]["text"] == "Chief Minister Himanta Biswa Sarma said the road is open."     # a title the reports write stays

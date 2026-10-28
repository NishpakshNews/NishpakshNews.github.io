"""The technical systems that replaced hand-written lists (Oct 28 2026): capword, speech from the parse, language id, gazetteer.
Each answers first, the old list answers when the system does not decide, and the disagreements are counted (auditcount)."""
import re

import pytest

from nishpaksh import agreement, auditcount, capword, compose, langid, nlp, people, places, recap, videoquery, worldgate


def toks(spec):
    """spec: [(text, pos, dep, head_index)] -> Tok list with offsets in the joined text."""
    out, pos = [], 0
    for i, (w, p, d, h) in enumerate(spec):
        tag = "VBD" if p == "VERB" else "NN"
        out.append(nlp.Tok(i, w, pos, pos + len(w), w.lower(), tag, p, d, h))
        pos += len(w) + 1
    return out


def with_parse(text, pos_of, ents=()):
    """A parser giving every word the part of speech pos_of[word] (default NOUN) and these entities."""
    def parser(t):
        res = []
        for i, m in enumerate(re.finditer(r"[A-Za-z’']+", t)):
            w = m.group(0)
            p = pos_of.get(w, "NOUN")
            res.append(nlp.Tok(i, w, m.start(), m.end(), w.lower(), "VBD" if p == "VERB" else "NN", p, "dep", i))
        return res
    nlp.set_parser(parser)
    old = nlp._backend
    nlp.set_backend(lambda t: [nlp.Ent(e, l, t.find(e), t.find(e) + len(e)) for e, l in ents if e in t])
    return old


# ---------------------------------------------------------------------------------------------------------- capword
def test_capword_uses_part_of_speech_and_entities_not_the_list():
    text = "Meanwhile Authorities in October said Modi met Nitish again before the vote"
    with_parse(text, {"Meanwhile": "ADV", "in": "ADP", "said": "VERB", "Modi": "PROPN", "Nitish": "PROPN"},
               ents=[("October", "DATE")])
    v = capword.verdicts(text)
    at = lambda w: text.index(w)
    assert v[at("Meanwhile")] is False               # a closed-class word, never a name
    assert v[at("Authorities")] is False             # a noun the old list did not have
    assert v[at("October")] is False                 # a date entity
    assert v[at("Modi")] is True and v[at("Nitish")] is True


def test_capword_headline_case_decides_only_closed_classes_and_entities():
    text = "Police Arrest Man After Court Ruling Stuns Delhi"
    with_parse(text, {"After": "ADP", "Police": "PROPN", "Arrest": "PROPN", "Delhi": "PROPN"}, ents=[("Delhi", "GPE")])
    assert capword.headline_case(text)
    v = capword.verdicts(text)
    assert v[text.index("After")] is False
    assert v[text.index("Delhi")] is True
    assert v[text.index("Police")] is None           # a part of speech in headline case is not trusted: the list answers
    auditcount.reset()
    assert capword.is_name("Police", text, text.index("Police"), listed_name=False) is False     # the list's answer
    assert capword.is_name("Police", text, text.index("Police"), listed_name=True) is True


def test_capword_counts_disagreements_with_the_list_in_both_directions():
    text = "India said Authorities will act"
    with_parse(text, {"India": "PROPN", "said": "VERB", "will": "AUX"})
    auditcount.reset()
    assert capword.is_name("India", text, 0, listed_name=False) is True            # the list wrongly called it common
    assert capword.is_name("Authorities", text, text.index("Authorities"), listed_name=True) is False
    c = auditcount.snapshot()["capword"]
    assert c["system_name_list_not"] == 1 and c["system_not_list_name"] == 1 and c["asked"] == 2


def test_capword_falls_back_to_the_list_without_a_part_of_speech():
    # the conftest parser gives no part of speech: nothing is decided, the old list answers (and is counted as unread)
    auditcount.reset()
    assert capword.is_name("Foo", "Foo said", 0, listed_name=True) is True
    assert capword.is_name("The", "The Foo said", 0, listed_name=False) is False
    assert auditcount.snapshot()["capword"].get("unread", 0) + auditcount.snapshot()["capword"].get("undecided", 0) == 2


def test_worldgate_names_drop_a_common_word_the_old_list_lacked():
    text = "Authorities arrest Macron aide"
    with_parse(text, {"Authorities": "NOUN", "arrest": "VERB", "Macron": "PROPN", "aide": "NOUN"})
    from nishpaksh.textmatch import skeleton
    got = worldgate.names(text)
    assert skeleton("Macron") in got and skeleton("Authorities") not in got


def test_people_clean_takes_a_function_word_off_by_part_of_speech():
    text = "Meanwhile Narendra Modi spoke"
    with_parse(text, {"Meanwhile": "ADV", "Narendra": "PROPN", "Modi": "PROPN", "spoke": "VERB"})
    assert people._clean("Meanwhile Narendra Modi", text, 0) == "Narendra Modi"
    # a word the analyser calls a name stays even if the old list had it as common
    text2 = "India Today reported"
    with_parse(text2, {"India": "PROPN", "Today": "PROPN", "reported": "VERB"}, ents=[("India Today", "ORG")])
    assert people._not_names("India Today", ["India", "Today"], text2, 0) == [False, False]


def test_recap_common_words_by_part_of_speech():
    t = "Meanwhile Hasina fled"
    with_parse(t, {"Meanwhile": "ADV", "Hasina": "PROPN", "fled": "VERB"})
    assert recap._common("Meanwhile", t, 0) is True and recap._common("Hasina", t, t.index("Hasina")) is False


# ---------------------------------------------------------------------------------------------------------- speech
def test_a_verb_of_saying_is_found_by_its_reported_clause_not_by_a_list():
    # "Kabir lamented that rain fell": "lament" is on no list, but it reports a clause
    t = toks([("Kabir", "PROPN", "nsubj", 1), ("lamented", "VERB", "ROOT", 1), ("that", "SCONJ", "mark", 3),
              ("rain", "NOUN", "nsubj", 4), ("fell", "VERB", "ccomp", 1)])
    auditcount.reset()
    assert nlp.is_speech(t, t[1]) is True
    assert auditcount.snapshot()["speech"]["parse_only"] == 1
    # a verb with an infinitive or an expletive subject is no speech verb
    t2 = toks([("Kabir", "PROPN", "nsubj", 1), ("decided", "VERB", "ROOT", 1), ("to", "PART", "aux", 3), ("go", "VERB", "xcomp", 1)])
    assert nlp.is_speech(t2, t2[1]) is False
    t3 = toks([("It", "PRON", "expl", 1), ("seems", "VERB", "ROOT", 1), ("rain", "NOUN", "nsubj", 3), ("fell", "VERB", "ccomp", 1)])
    assert nlp.is_speech(t3, t3[1]) is False


def test_a_bare_listed_verb_is_still_speech_by_the_fallback_list():
    t = toks([("He", "PRON", "nsubj", 1), ("added", "VERB", "ROOT", 1)])
    t[1] = nlp.Tok(1, "added", 3, 8, "add", "VBD", "VERB", "ROOT", 1)
    auditcount.reset()
    assert nlp.is_speech(t, t[1]) is True
    assert auditcount.snapshot()["speech"]["list_only"] == 1


def test_speech_stems_of_a_line_come_from_the_parse():
    spec = toks([("Bedi", "PROPN", "nsubj", 1), ("reiterating", "VERB", "ROOT", 1), ("that", "SCONJ", "mark", 3),
                 ("India", "PROPN", "nsubj", 4), ("stands", "VERB", "ccomp", 1)])
    spec[1] = nlp.Tok(1, "reiterating", 5, 16, "reiterate", "VBG", "VERB", "ROOT", 1)
    nlp.set_parser(lambda text: spec)
    stems = compose._speech_stems("Bedi reiterating that India stands")
    from nishpaksh.frames import _stem
    assert _stem("reiterating") in stems


def test_parse_same_clause_follows_complements_not_coordination():
    # "The court said it was" -> it (was, ccomp of said) is the court's clause; "The court said X and it was" is not
    a = toks([("The", "DET", "det", 1), ("court", "NOUN", "nsubj", 2), ("said", "VERB", "ROOT", 2), ("it", "PRON", "nsubj", 4),
              ("was", "VERB", "ccomp", 2)])
    assert agreement._parse_same_clause(a, a[3], a[1].end) is True
    b = toks([("The", "DET", "det", 1), ("court", "NOUN", "nsubj", 2), ("sat", "VERB", "ROOT", 2), ("and", "CCONJ", "cc", 2),
              ("it", "PRON", "nsubj", 5), ("rose", "VERB", "conj", 2)])
    assert agreement._parse_same_clause(b, b[4], b[1].end) is False
    c = toks([("The", "DET", "det", 1), ("court", "NOUN", "nsubj", 2), ("sat", "VERB", "ROOT", 2)])
    c = [nlp.Tok(t.i, t.text, t.start, t.end, t.lemma, t.tag, "", t.dep, t.head) for t in c]
    assert agreement._parse_same_clause(c, c[1], c[1].end) is None        # no part of speech: not decided


# ---------------------------------------------------------------------------------------------------------- language
def test_video_language_asks_the_model_and_keeps_the_list_as_fallback():
    L = videoquery.video_language
    auditcount.reset()
    # romanised Hindi that the model reads as another language (Swahili): not English even with a tag
    langid.set_backend(lambda t: ("swahili", 0.8, 0.7))
    assert L("Aaj ki badi khabar", "en") is None
    # English leading clearly: sure, with no function word and no tag
    langid.set_backend(lambda t: ("english", 0.3, 0.2))
    assert L("Kejriwal Mamata Adani") == "en"
    # the model unsure: the old words decide
    langid.set_backend(lambda t: ("albanian", 0.2, 0.05))
    assert L("Kejriwal slams BJP over Delhi pollution") == "en"
    assert L("Modi ne kiya bada elaan") is None
    c = auditcount.snapshot()["language"]
    assert c["en_asked"] == 4
    assert c["en_model_yes_list_no"] == 1


def test_hindi_needs_the_model_to_lead_and_the_other_languages_veto_stays():
    L = videoquery.video_language
    langid.set_backend(lambda t: ("hindi", 0.8, 0.6))
    assert L("दिल्ली पुलिस ने नेता को छोड़ा") == "hi"
    langid.set_backend(lambda t: ("marathi", 0.8, 0.6))
    assert L("दिल्ली पुलिस ने नेता को छोड़ा") is None
    langid.set_backend(lambda t: ("hindi", 0.64, 0.28))              # Nepali read as Hindi: the margin is too thin
    assert L("दिल्लीमा प्रहरीले नेतालाई छोड्यो") is None
    langid.set_backend(lambda t: ("hindi", 0.9, 0.8))
    assert L("दिल्ली में नेता गरेको") is None                        # OTHER_DEVA veto (a Nepali word)


# ---------------------------------------------------------------------------------------------------------- places
def test_places_come_from_the_gazetteer_with_the_tables_as_fallback():
    pytest.importorskip("geonamescache")
    auditcount.reset()
    assert places.is_place("Washington") and places.is_place("Kyiv") and places.is_place("Russia")
    assert not places.is_place("Highlights") and not places.is_place("Reading") and not places.is_place("Police")
    assert places.is_place("United Nations")                         # not in the gazetteer: the table answers
    assert places.is_place("वॉशिंगटन")                                # Devanagari by consonant skeleton
    c = auditcount.snapshot()["places"]
    assert c.get("list_only", 0) >= 1 and c.get("gazetteer_only", 0) >= 1


def test_government_names_for_countries_use_iso_names_and_the_list_for_the_rest():
    pytest.importorskip("geonamescache")
    assert places.government_name("Russia") == places.government_name("Russian Federation") == "Russia"
    assert places.government_name("UK") == "UK"                      # an abbreviation the gazetteer lacks: the table answers
    assert places.government_name("India") == "Union"
    assert places.government_name("Narnia") is None


def test_systems_audit_lists_the_words_the_two_disagree_on():
    from nishpaksh.tools import evaluate
    text = "Police said Meanwhile Hasina fled the country after the vote"
    with_parse(text, {"Police": "PROPN", "said": "VERB", "Meanwhile": "ADV", "Hasina": "PROPN", "fled": "VERB"})
    rep = evaluate.systems_audit([{"headline": text}])
    assert rep["texts"] == 1
    assert rep["counts"]["worldgate:asked"] >= 3
    flat = {(w, d) for lst in rep["top_disagreements"].values() for w, d, n in lst}
    assert ("Police", "system:name") in flat        # the list calls "police" common, the analyser called it a name here

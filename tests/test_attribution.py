"""Attribution read from the parse (B18), not matched by a pattern."""
from nishpaksh import attribution as a, style


def test_subject_first_is_read_in_parts():
    sp = a.read("Kabir also stated on Monday that the road is shut.")
    assert (sp.subject, sp.adverb, sp.extras, sp.body, sp.subject_first) == ("Kabir", "also", "on Monday", "the road is shut", True)


def test_body_first_is_read():
    sp = a.read("The road is shut, Kabir said.")
    assert sp.subject == "Kabir" and not sp.subject_first and sp.body == "The road is shut"


def test_trailing_form_keeps_day_and_neutralises_the_verb():
    sp = a.read("Kabir also stated on Monday that the road is shut.")
    assert a.trailing(sp, "he") == "The road is shut, he said on Monday."
    assert a.trailing(a.read("Kabir alleged that the road is shut."), "he") == "The road is shut, he alleged."


def test_adverb_goes_and_verb_becomes_said():
    t = "Kabir further added that the road is shut."
    assert a.without_adverb(t, a.read(t)) == "Kabir said that the road is shut."


def test_a_quotation_or_a_plain_sentence_is_not_read():
    assert a.read('Kabir said "the road is shut".') is None
    assert a.read("The road is shut.") is None


def test_pronoun_subject_of_a_speech_verb_is_found():
    assert a.pronoun_subjects("The road is shut, he said.")[0][2] == "he"
    assert a.pronoun_subjects("He crossed the road.") == []


def test_run_of_one_speaker_ends_with_the_attribution():
    refs = style.Refs({"Humayun Kabir": "Kabir"}, {"Humayun Kabir": "he"}, {})
    para = [[{"text": "Humayun Kabir said that the road is shut."},
             {"text": "He also stated that the bridge fell."}]]
    style.vary_attribution(para, refs)
    assert para[0][1]["text"].endswith(", he said.") or para[0][1]["text"].endswith(", Kabir said.")

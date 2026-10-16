"""The fidelity checks (fidelity.py, session 5): the qualifiers a reading or a translation must keep, found in the
right source sentence by anchors only."""
from nishpaksh import fidelity as F
from nishpaksh import names as N

SRC = ("राहुल गांधी की क्या दलीलें?\n"
       "राहुल गांधी ने कोर्ट में अपनी सफाई में कहा कि उन्होंने किसी पार्टी का नाम नहीं लिया। "
       "राहुल गांधी ने कहा कि उन्होंने अपने बयान में भाजपा या किसी राजनीतिक दल का सीधे नाम नहीं लिया था। "
       "बता दें कि कानून के तहत आपराधिक मानहानि के लिए एक निश्चित और ‘पहचान योग्य वर्ग’ का होना अनिवार्य है।")


def reg():
    r = N.Registry()
    r.add_manual("Rahul", "राहुल")
    r.add_manual("Gandhi", "गांधी")
    return r


def test_the_rahul_gandhi_reading_is_caught():
    st = "He did not name the BJP or any specific political party in his statement, Gandhi said."
    win, probs = F.check_reading(st, SRC, "hi", reg())
    assert "सीधे" in win                                                # the BJP (भाजपा) sentence, not the other
    assert {str(p) for p in probs} == {"lost:directly", "added:specific"}
    good = "He did not directly name the BJP or any political party in his statement, Gandhi said."
    assert F.check_reading(good, SRC, "hi", reg())[1] == []


def test_the_rahul_gandhi_translation_is_caught():
    en = "Gandhi said he did not directly name the BJP or any political party in his statement."
    bad = "गांधी ने कहा कि उन्होंने अपने बयान में बीजेपी या किसी विशिष्ट राजनीतिक दल का नाम नहीं लिया।"
    assert {str(p) for p in F.check_translation(en, bad)} == {"lost:directly", "added:specific"}
    ok = "गांधी ने कहा कि उन्होंने अपने बयान में बीजेपी या किसी राजनीतिक दल का सीधे नाम नहीं लिया।"
    assert F.check_translation(en, ok) == []


def test_ordinary_words_never_choose_the_sentence():
    # सीधे once matched "side" by consonant skeleton; now only numbers, dates, names and entities count
    assert F.source_window("He stood by the side of the road.", SRC, "hi", reg()) is None
    # two sentences with the same anchors: unclear, so nothing is checked
    assert F.source_window("Rahul Gandhi did not name any party.", SRC, "hi", reg()) is None
    assert F.check_reading("Rahul Gandhi did not name any party.", SRC, "hi", reg()) == (None, [])


def test_numbers_and_dates_anchor_across_scripts():
    src = "मोदी १५ अक्टूबर को 3,350 करोड़ रुपये की पांच परियोजनाओं का उद्घाटन करेंगे। इससे पहले 40 गांवों में तालाब बने।"
    win = F.source_window("Modi will open five projects worth about Rs 3,350 crore on 15 October.", src, "hi")
    assert win.startswith("मोदी")
    assert [str(p) for p in F.check_reading("Modi will open projects worth about Rs 3,350 crore on 15 October.",
                                             src, "hi", strict_only=False)[1]] == ["added:approximately"]


def test_number_bound_qualifiers_and_negation_forms():
    assert F.qualifiers("over the years, talks about the case", "en") == set()
    assert F.qualifiers("about 40 people, over 2 lakh", "en") == {"approximately", "more_than"}
    assert F.qualifiers("करीब 40 लोग", "hi") == {"approximately"} and F.qualifiers("वह घर के करीब है", "hi") == set()
    assert F.qualifiers("He didn't come", "en") == {"negation"}
    assert F.qualifiers("Platform No. 5 opened", "en") == set()
    assert F.qualifiers("उसने कभी नहीं कहा", "hi") == {"never", "negation"}
    assert F.qualifiers("सिर्फ़ दो", "hi") == F.qualifiers("सिर्फ दो", "hi") == {"only"}


def test_latin_left_in_hindi():
    en = "Amrit Vats won in Djibouti (Djibouti City). See www.itf.com, 9 MW."
    hi = "Amrit Vats ने जिबूती (Djibouti City) में खिताब जीता। देखें www.itf.com, 9 MW।"
    assert F.latin_left(hi, en) == ["Amrit", "Vats"]
    assert {str(p) for p in F.check_translation(en, hi)} == {"latin:Amrit", "latin:Vats"}


def test_binding_terms():
    en = "He was granted anticipatory bail in the criminal defamation case."
    assert F.missing_terms(en, "उन्हें आपराधिक मानहानि मामले में जमानत मिली।") == ["anticipatory bail"]
    assert F.missing_terms(en, "उन्हें आपराधिक मानहानि मामले में अग्रिम जमानत मिली।") == []
    assert F.terms_in("An FIR was filed") == [("FIR", "एफआईआर")]

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


# cases from the first audit on stored data (Oct 16 2026): real catches stay, the noise goes
def test_real_catches_from_stored_statements():
    src = "He claimed that the Congress won only 14 of the 4,600 seats."
    assert [str(p) for p in F.check_reading("The Congress won 14 of the 4,600 seats.", src, "en")[1]] == ["lost:only"]
    hi = "एसजी तुषार मेहता ने कहा कि 10 अक्टूबर को 303 में से केवल 45 स्टेशनों पर रोक लगाई गई थी।"
    st = "Solicitor General Tushar Mehta stated that 45 out of 303 metro stations were closed on October 10."
    assert [str(p) for p in F.check_reading(st, hi, "hi")[1]] == ["lost:only"]


def test_a_statement_from_part_of_a_sentence_keeps_only_its_own_qualifiers():
    src = ("In Rejinagar, the BJP won by over 75,000 votes, snatching the seat from the Trinamool, while in "
           "Puducherry, the NDA candidate from ally AINRC won by 8,482 votes.")
    assert F.check_reading("In Puducherry, the NDA candidate from ally AINRC won by 8,482 votes.", src, "en")[1] == []
    src = "Rahul Gandhi and INDIA bloc leaders submitted a petition against the Election Commission over alleged 'vote chori'."
    assert F.check_reading("Rahul Gandhi and INDIA bloc leaders submitted a petition against the Election Commission.",
                           src, "en")[1] == []


def test_noise_words_are_not_qualifiers():
    assert F.qualifiers("Zelensky alleged that Russia struck a plant.", "en") == set()        # a verb: आरोप लगाया
    assert F.qualifiers("the alleged bribe", "en") == {"alleged"}
    assert F.qualifiers("विशेष गहन पुनरीक्षण के दौरान", "hi") == set()                       # "Special", not "specific"
    assert F.qualifiers("Shafali struck 100 not out", "en") == set()                         # cricket: नाबाद
    assert F.qualifiers("he had no prior information", "en") == {"negation"}                 # YAML once read no as false
    en = "UPI transactions exceeding 2,000 rupees"
    assert F.compare(en, "2,000 रुपये से अधिक के UPI लेनदेन", "en", "hi") == []
    assert F.check_translation(en, "2,000 रुपये से अधिक के UPI लेनदेन", strict_only=True) == [F.Problem("latin", "UPI")]


def test_number_bound_qualifiers_compare_number_by_number():
    src = "देश में 100 से अधिक भाषाएं हैं, करीब 80,000 पंजीकृत समाचार पत्र हैं।"
    assert F.check_reading("India has approximately 80,000 registered newspapers.", src, "hi", strict_only=False)[1] == []
    assert [str(p) for p in F.compare("India has more than 100 languages.", "भारत में 100 भाषाएं हैं।", "en", "hi")] == \
        ["lost:more_than"]


def test_glossary_refuses_yaml_booleans(tmp_path):
    import pytest
    f = tmp_path / "g.yaml"
    f.write_text("qualifiers:\n  - {id: negation, en: [no], hi: [नहीं]}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        F.glossary(str(f))


def test_second_audit_cases():
    # Hindi "never" stands around the verb
    assert "never" in F.qualifiers("भाजपा की लोकतंत्र को बनाने में कभी कोई भूमिका नहीं रही।", "hi")
    en = "Hockey India never informed them of any retirement decision."
    assert F.check_translation(en, "हॉकी इंडिया ने उन्हें कभी भी किसी संन्यास के निर्णय के बारे में सूचित नहीं किया।") == []
    # "over" binds only to a number right after it
    assert F.qualifiers("India won by 14 runs over West Indies", "en") == set()
    assert F.qualifiers("an investment over the next six years", "en") == set()
    assert F.qualifiers("a terminal spread over 23,800 square metres", "en") == set()
    # hyphenated "-specific", "fixed" papers, महज़
    assert F.qualifiers("भारत-विशिष्ट उपकरण", "hi") == set() and F.qualifiers("India-specific tools", "en") == set()
    assert F.qualifiers("निश्चित प्रश्नपत्रों", "hi") == set()
    assert F.qualifiers("महज़ एक हफ़्ते पहले", "hi") == {"only"}
    # an attributing verb keeps the caveat of "alleged"
    assert F.check_translation("The petition is against Kumar and alleged vote theft.",
                               "याचिका कुमार और कथित वोट चोरी के खिलाफ है।") == []
    src = "The remarks came ahead of a planned march over alleged electoral irregularities in Delhi."
    assert F.check_reading("Opposition leaders alleged electoral irregularities in Delhi.", src, "en")[1] == []


def test_third_audit_cases():
    assert F.check_translation("tariffs of up to 100% on countries", "देशों पर 100% तक शुल्क") == []
    assert F.qualifiers("15 अक्टूबर तक", "hi") == set()                         # until, not "up to"
    assert F.check_translation("a crowd beyond 1,000", "1,000 से अधिक की भीड़") == []
    assert F.check_reading("Russia will supply over 300,000 tons of diesel.",
                           "ट्रंप ने कहा था कि रूस 3 लाख टन से अधिक डीजल की सप्लाई करेगा.", "hi")[1] == []
    assert F.check_translation("the 50 percent maximum limit for reservations",
                               "आरक्षण के लिए 50 प्रतिशत की अधिकतम सीमा") == []
    assert F.qualifiers("सीधे सेटों में हराया", "hi") == set()
    assert F.qualifiers("चुना जाना चाहिए या नहीं.", "hi") == set()


# -- every statement checked: the reading model copies its sentence's first words (context plan session 6) ---------

QSRC = "राहुल गांधी ने कहा कि वे किसी दल का सीधे नाम नहीं लेंगे। बाद में उन्होंने भाजपा पर हमला किया। बाद में उन्होंने रैली की।"


def test_a_quote_finds_its_sentence_word_for_word_and_only_once():
    assert F.quoted_window("राहुल गांधी ने कहा कि वे", QSRC).startswith("राहुल गांधी ने कहा")
    assert F.quoted_window("बाद में उन्होंने भाजपा पर हमला", QSRC) == "बाद में उन्होंने भाजपा पर हमला किया।"
    assert F.quoted_window("राहुल गांधी ने कहा, कि वे गलत शब्द", QSRC).startswith("राहुल")     # a slip at its end
    assert F.quoted_window("बाद में उन्होंने", QSRC) is None                       # too short
    assert F.quoted_window("बाद में उन्होंने कहा", QSRC) is None                   # not in the report
    assert F.quoted_window("Rahul Gandhi said that he", QSRC) is None             # translated, not copied


def test_a_hindi_statement_with_no_anchor_is_checked_through_its_quote():
    st = "Rahul Gandhi said he would not name any party."
    assert F.check_reading(st, QSRC, "hi") == (None, [])                          # anchors alone: unchecked
    win, probs = F.check_reading(st, QSRC, "hi", quote="राहुल गांधी ने कहा कि वे")
    assert win and [str(p) for p in probs] == ["lost:directly"]
    assert F.find_source(st, QSRC, "hi", quote="no such words in it at all")[1] == "none"

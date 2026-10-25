"""The fidelity checks (fidelity.py): the right source sentence is found by anchors only; the NLI model (scripted here)
decides whether a statement or a translation keeps the meaning."""
from nishpaksh import fidelity as F
from nishpaksh import names as N
from nishpaksh import nli

SRC = ("राहुल गांधी की क्या दलीलें?\n"
       "राहुल गांधी ने कोर्ट में अपनी सफाई में कहा कि उन्होंने किसी पार्टी का नाम नहीं लिया। "
       "राहुल गांधी ने कहा कि उन्होंने अपने बयान में भाजपा या किसी राजनीतिक दल का सीधे नाम नहीं लिया था। "
       "बता दें कि कानून के तहत आपराधिक मानहानि के लिए एक निश्चित और ‘पहचान योग्य वर्ग’ का होना अनिवार्य है।")


def reg():
    r = N.Registry()
    r.add_manual("Rahul", "राहुल")
    r.add_manual("Gandhi", "गांधी")
    return r


def scripted(entail_fwd=0.95, entail_bwd=0.95, contra=0.02):
    """An NLI stand-in: the premise-to-hypothesis answer is `entail_fwd`, the reverse `entail_bwd`."""
    def fn(pairs):
        out = []
        for a, _ in pairs:
            e = entail_fwd if a.isascii() else entail_bwd       # English premise = English -> Hindi
            out.append((e, max(0.0, 1 - e - contra), contra))
        return out
    return fn


def test_the_rahul_gandhi_reading_is_found_in_the_right_sentence_and_judged_by_meaning():
    st = "He did not name the BJP or any specific political party in his statement, Gandhi said."
    quote = "राहुल गांधी ने कहा कि उन्होंने अपने"
    seen = []

    def backend(pairs):
        seen.extend(pairs)
        return [(0.12, 0.80, 0.08)] * len(pairs)           # the report's sentence does not support the statement
    nli.set_backend(backend)
    win, probs = F.check_reading(st, SRC, "hi", reg(), quote=quote)
    assert "सीधे" in win and seen[0][0] == win and seen[0][1] == st     # the BJP sentence, premise = the report
    assert [str(p) for p in probs] == ["unsupported:meaning"]
    nli.set_backend(scripted())
    assert F.check_reading(st, SRC, "hi", reg(), quote=quote)[1] == []
    nli.set_backend(lambda pairs: [(0.02, 0.08, 0.90)] * len(pairs))
    assert [str(p) for p in F.check_reading(st, SRC, "hi", reg(), quote=quote)[1]] == ["contradicted:meaning"]
    # a denial is written as the positive claim it denies: only the sentence is found, nothing is asked of its meaning
    assert F.check_reading(st, SRC, "hi", reg(), quote=quote, stance="denies")[1] == []


def test_a_pair_the_model_could_not_read_flags_nothing():
    nli.set_backend(lambda pairs: [None] * len(pairs))
    assert F.check_reading("He did not name any party.", SRC, "hi", reg(),
                           quote="राहुल गांधी ने कहा कि उन्होंने अपने")[1] == []
    assert F.check_translation("The court agreed.", "अदालत सहमत हुई।") == []


def test_a_translation_is_read_both_ways():
    en, hi = "Gandhi said he did not directly name the BJP.", "गांधी ने कहा कि उन्होंने भाजपा का नाम नहीं लिया।"
    nli.set_backend(scripted(entail_fwd=0.2, entail_bwd=0.95))
    assert [str(p) for p in F.check_translation(en, hi)] == ["lost:meaning"]
    nli.set_backend(scripted(entail_fwd=0.95, entail_bwd=0.2))
    assert [str(p) for p in F.check_translation(en, hi)] == ["added:meaning"]
    nli.set_backend(scripted(contra=0.9, entail_fwd=0.05, entail_bwd=0.05))
    assert [str(p) for p in F.check_translation(en, hi)] == ["contradicted:meaning"]
    nli.set_backend(scripted())
    assert F.check_translation(en, hi) == []


def test_ordinary_words_never_choose_the_sentence():
    # सीधे once matched "side" by consonant skeleton; only numbers, dates and names count
    assert F.source_window("He stood by the side of the road.", SRC, "hi", reg()) is None
    assert F.source_window("Rahul Gandhi did not name any party.", SRC, "hi", reg()) is None
    assert F.check_reading("Rahul Gandhi did not name any party.", SRC, "hi", reg()) == (None, [])


def test_numbers_and_dates_anchor_across_scripts():
    src = "मोदी १५ अक्टूबर को 3,350 करोड़ रुपये की पांच परियोजनाओं का उद्घाटन करेंगे। इससे पहले 40 गांवों में तालाब बने।"
    win = F.source_window("Modi will open five projects worth about Rs 3,350 crore on 15 October.", src, "hi")
    assert win.startswith("मोदी")


def test_latin_left_in_hindi():
    en = "Amrit Vats won in Djibouti (Djibouti City). See www.itf.com, 9 MW."
    hi = "Amrit Vats ने जिबूती (Djibouti City) में खिताब जीता। देखें www.itf.com, 9 MW।"
    assert F.latin_left(hi, en) == ["Amrit", "Vats"]
    nli.set_backend(scripted())
    assert {str(p) for p in F.check_translation(en, hi)} == {"latin:Amrit", "latin:Vats"}


def test_binding_terms():
    en = "He was granted anticipatory bail in the criminal defamation case."
    assert F.missing_terms(en, "उन्हें आपराधिक मानहानि मामले में जमानत मिली।") == ["anticipatory bail"]
    assert F.missing_terms(en, "उन्हें आपराधिक मानहानि मामले में अग्रिम जमानत मिली।") == []
    assert F.terms_in("An FIR was filed") == [("FIR", "एफआईआर")]

"""Negation written into a word (polarity.py, context plan session 5): "unaffected" = "प्रभावित नहीं"."""
from nishpaksh import fidelity as F
from nishpaksh import polarity as P
from nishpaksh import relate as R


def test_forms_strong_by_list_and_rule_weak_by_the_un_rule():
    got = {(f.word, f.base, f.strong) for f in P.forms("Roads were unaffected, the illegal unit was unhurt and "
                                                        "the charge is non-bailable; until then it was unclear", "en")}
    assert got == {("unaffected", "affected", True), ("illegal", "legal", True), ("unhurt", "hurt", False),
                   ("non-bailable", "bailable", True), ("unclear", "clear", True)}
    hi = {(f.word, f.strong) for f in P.forms("सड़कें अप्रभावित रहीं, गैर-कानूनी खनन और गैरजमानती धारा", "hi")}
    assert hi == {("अप्रभावित", True), ("गैर-कानूनी", True), ("गैरजमानती", True)}
    assert P.forms("एक गैर सरकारी संगठन ने और a nongovernmental group", "hi") == []      # NGO: a kind, not a negation
    assert P.forms("a non-governmental organisation, the union and a unique plan", "en") == []


def test_a_negated_form_answers_a_negation_word_across_languages():
    assert F.compare("Roads were unaffected by the flood", "सड़कें बाढ़ से प्रभावित नहीं हुईं", "en", "hi") == []
    assert F.compare("सड़कें बाढ़ से प्रभावित नहीं हुईं", "Roads were unaffected by the flood", "hi", "en") == []
    assert F.compare("खनन अवैध था", "The mining was not legal", "hi", "en") == []
    assert F.compare("The passengers were unhurt in the crash", "यात्री हादसे में घायल नहीं हुए", "en", "hi") == []


def test_a_reading_that_drops_the_prefix_lost_the_negation():
    lost = [F.Problem("lost", "negation", True)]
    assert F.compare("Roads were unaffected by the flood", "Roads were affected by the flood", "en", "en") == lost
    assert F.compare("The passengers were unhurt in the crash", "The passengers were hurt in the crash", "en", "en") == lost
    assert F.compare("सड़कें अप्रभावित रहीं", "सड़कें प्रभावित रहीं", "hi", "hi") == lost


def test_a_weak_form_alone_is_never_a_negation():
    assert F.compare("The turnout was unprecedented", "मतदान अभूतपूर्व रहा", "en", "hi") == []
    assert "negation" not in F.qualifiers("The turnout was unprecedented", "en")


def test_statement_matching_reads_the_form_as_the_word_negated():
    a = "Roads in the district were unaffected by the flood"
    assert R.relate(a, "Roads in the district were not affected by the flood") == "same"
    assert R.relate(a, "Roads in the district were affected by the flood") == "different"

from nishpaksh import relate
from nishpaksh.relate import Profile, fold_latin, soft_candidate


def test_accents_are_folded_for_latin_only():
    assert fold_latin("Flávio Inácio") == "Flavio Inacio"
    assert fold_latin("गांधी ज़") == "गांधी ज़"
    assert Profile("Lula defeated Flávio Bolsonaro").names == Profile("Lula defeated Flavio Bolsonaro").names


def test_a_title_or_demonym_does_not_keep_two_lines_apart_from_the_model():
    a = "Prime Minister Narendra Modi congratulated Luiz Inácio Lula da Silva on his presidential re-election win in Brazil"
    b = "Prime Minister Narendra Modi congratulated Brazilian President Luiz Inácio Lula da Silva on his electoral victory."
    assert soft_candidate(a, b)


def test_facts_still_veto():
    assert not soft_candidate("Police arrested Ravi in Patna", "Police did not arrest Ravi in Patna")
    assert not soft_candidate("Police arrested 5 men in Patna", "Police arrested 7 men in Patna")
    assert not soft_candidate("Rahul Gandhi met the Prime Minister", "Priyanka Gandhi met the Prime Minister")
    assert not soft_candidate("The court heard the case on 5 October 2024", "The court heard the case on 5 October 2025")
    assert not soft_candidate("The meeting is at 10:30 AM", "The meeting is at 4:00 PM")

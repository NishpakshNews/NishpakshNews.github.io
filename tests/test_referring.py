"""style.Refs.next: the form of a repeated mention is chosen by centering, not rotated."""
from nishpaksh.style import Refs


def test_pronoun_only_for_the_topic_and_with_evidence_never_twice_in_a_row():
    r = Refs({"Humayun Kabir": "Kabir"}, {"Humayun Kabir": "he"}, {"Humayun Kabir": "the MLA"})
    assert r.next("Humayun Kabir", topic=False) == "the MLA"   # not yet the topic: the role
    assert r.next("Humayun Kabir") == "he"               # the run continues: evidenced pronoun
    assert r.next("Humayun Kabir") == "the MLA"          # not "he" twice
    assert r.next("Humayun Kabir") == "he"


def test_without_evidence_it_is_the_surname_never_a_pronoun():
    r = Refs({"Raj Puri": "Puri"}, {}, {})
    assert [r.next("Raj Puri"), r.next("Raj Puri")] == ["Puri", "Puri"]

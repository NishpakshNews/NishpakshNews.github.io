"""agreement.py: roles from the parse, verb forms from lemminflect (no database, stand-in parser from conftest)."""
from nishpaksh import agreement, nlp


def test_a_court_is_they_with_a_plural_verb():
    t, n = agreement.fix_text("The Supreme Court said it was examining the plea.")
    assert t == "The Supreme Court said they were examining the plea." and n == 1
    t, _ = agreement.fix_text("The bench said it has reserved its order.")
    assert t == "The bench said they have reserved their order."


def test_object_expletive_and_non_bodies_are_left():
    assert agreement.fix_text("The court asked it to reply.")[0] == "The court asked them to reply."
    assert agreement.fix_text("The court said it is clear that the plea failed.")[0].startswith("The court said it is clear")
    assert agreement.fix_text("The ministry said it was examining the plea.")[1] == 0


def test_without_a_parse_nothing_changes():
    nlp.set_parser(lambda text: None)
    assert agreement.fix_text("The court said it was examining the plea.") == ("The court said it was examining the plea.", 0)


def test_plural_forms_come_from_the_library():
    T = lambda text, lemma, tag: nlp.Tok(0, text, 0, len(text), lemma, tag, "VERB", "ROOT", 0)
    assert agreement._plural(T("Says", "say", "VBZ")) == "Say"
    assert agreement._plural(T("is", "be", "VBZ")) == "are"
    assert agreement._plural(T("was", "be", "VBD")) == "were"
    assert agreement._plural(T("decided", "decide", "VBD")) is None

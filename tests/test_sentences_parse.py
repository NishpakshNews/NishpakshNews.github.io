"""Sentences come from the parser, and a verbless piece is never a sentence (story 46150: "[17] ... chief Adm." was shown
to the reading model as a sentence of its own and came back as a statement with nothing in it)."""
from nishpaksh import fidelity, nlp


def test_a_verbless_piece_is_joined_to_the_next():
    parts = [("On Sunday, US Central Command chief Adm.", False), ("Brad Cooper said the strikes were over.", True),
             ("Talks resume on Monday.", True)]
    assert nlp.merge_fragments(parts) == ["On Sunday, US Central Command chief Adm. Brad Cooper said the strikes were over.",
                                          "Talks resume on Monday."]


def test_a_trailing_verbless_piece_joins_the_last_sentence():
    assert nlp.merge_fragments([("Prices fell.", True), ("Photo: PTI.", False)]) == ["Prices fell. Photo: PTI."]


def test_sentences_use_the_segmenter_when_there_is_one_and_the_punctuation_rule_otherwise():
    nlp.set_segmenter(lambda p: [(p, True)])
    try:
        fidelity._cache.clear()
        assert fidelity.sentences("Adm. Cooper spoke. He left.") == ["Adm. Cooper spoke. He left."]
    finally:
        nlp.set_segmenter(None)
        fidelity._cache.clear()
    assert fidelity.sentences("एक बात। दूसरी बात।") == ["एक बात।", "दूसरी बात।"]

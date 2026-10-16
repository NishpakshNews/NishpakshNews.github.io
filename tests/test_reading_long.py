"""Long reports read in pieces and exact words kept (step 1 of the express plan, Oct 16 2026)."""
import types

from nishpaksh import extract as X
from nishpaksh import narrative as N


def test_a_long_report_is_read_in_overlapping_pieces():
    paras = [f"Paragraph {k} says the team scored {k} runs in over {k}." * 8 for k in range(40)]
    text = "\n".join(paras)
    ps = X.pieces(text, cap=7000)
    assert len(ps) >= 3 and all(len(p) <= X.PIECE_CHARS + 600 for p in ps)
    for a, b in zip(ps, ps[1:]):
        assert a.split("\n")[-1] == b.split("\n")[0]                  # each piece starts with the last paragraph
    assert X.pieces("short text", cap=7000) == ["short text"]
    huge = "\n".join(paras * 5)
    assert len(X.pieces(huge, cap=7000)) == X.MAX_PIECES


class Router:
    def __init__(self):
        self.prompts = []

    def call(self, tier, prompt, **kw):
        self.prompts.append(prompt)
        k = len(self.prompts)
        items = [{"id": "c1", "text": f"Fact number {k} about the match.", "stance": "asserts"},
                 {"id": "c2", "text": "The match was played in Ranchi on Sunday.", "stance": "asserts"}]
        return types.SimpleNamespace(data={"signature": f"sig {k}", "claims": items}, model="m")


def test_pieces_are_one_reading_with_the_overlap_read_once():
    a = {"id": 1, "outlet": "o", "published_at": None, "title": "t",
         "text": "\n".join(f"Paragraph {k}. " * 60 for k in range(30))}
    r = Router()
    ex, model = X.read_report(r, a)
    n = len(r.prompts)
    assert n >= 2 and "PART 2 of" in r.prompts[1] and "The article opened with" in r.prompts[1]
    texts = [c["text"] for c in ex["claims"]]
    assert texts.count("The match was played in Ranchi on Sunday.") == 1     # read in every piece, kept once
    assert len(texts) == n + 1 and ex["signature"] == "sig 1"
    assert {c["id"] for c in ex["claims"]} >= {"c1", "p2-c1"}


def test_exact_words_must_stand_word_for_word_in_an_english_report():
    src = 'Shaw said, “It is me versus me. That is it,” before the match.'
    ex = {"claims": [{"text": "a", "words": "It is me versus me"}, {"text": "b", "words": "It is only me versus me"},
                     {"text": "c", "words": "me"}], "events": [], "context": []}
    assert X.check_words(ex, src, "en") == 2 and [c["words"] for c in ex["claims"]] == ["It is me versus me", "", ""]
    hi = {"claims": [{"text": "a", "words": "It is me versus me"}], "events": [], "context": []}
    assert X.check_words(hi, src, "hi") == 1


def item(i, text, words=None, speaker="Prithvi Shaw"):
    return {"id": i, "kind": "claim", "text": text, "verdict": "single", "speaker": speaker, "sources": [],
            "time": None, "check": None, "words": words}


def test_the_writer_may_quote_exact_words_and_nothing_else():
    by = {1: item(1, "Prithvi Shaw said returning to the Indian team is his ultimate goal.",
                  "It is not about proving anything to anyone. It is me versus me."),
          2: item(2, "Prithvi Shaw said he is focusing on cricket.")}
    v = lambda t, ids: N._validate({"text": t, "ids": ids}, by, {"thug"}, [])   # noqa: E731
    assert v('"It is me versus me," Shaw said of his goal of returning to the Indian team.', [1]) == [1]
    assert v('"It is all about me and nobody else," Shaw said.', [1]) is None
    assert N._TL.last == "quote not in statements"
    by[3] = item(3, "Prithvi Shaw said critics called him a thug.", "They called me a thug")
    assert v('"They called me a thug," Shaw said.', [3]) == [3]                  # his word, inside his quote
    assert "EXACT WORDS" in N._statement_line(dict(by[1], role="core", sources=[], n_sources=1))

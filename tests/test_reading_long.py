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


def test_a_piece_does_not_start_by_pointing_at_a_paragraph_it_was_not_given(monkeypatch):
    from nishpaksh import extract, nlp
    monkeypatch.setattr(extract, "PIECE_CHARS", 60)
    first = lambda s: s.split()[0]
    monkeypatch.setattr(nlp, "parse", lambda t: [nlp.Tok(0, first(t), 0, 1, first(t).lower(),
                                                         "PRP" if first(t) in ("He", "It") else "NN", "PRON" if first(t) in ("He", "It") else "NOUN",
                                                         "nsubj", 0)])
    paras = ["Ramesh was arrested in Patna on Monday.", "He denied the charge before the court.", "It was adjourned.",
             "Police filed a second report."]
    out = extract.pieces("\n".join(paras), cap=10)
    assert out[1].split("\n")[0] == paras[0]          # the second piece starts back at the paragraph that names "He"


def test_pieces_cluster_duplicates_and_remap_relations():
    from nishpaksh.extract import _merge_pieces
    a = {"signature": "s", "events": [{"id": "e1", "text": "Police arrested 5 men in Pune"}],
         "claims": [{"id": "c1", "text": "The minister said the bridge is safe"}],
         "relations": [{"from": "c1", "to": "e1", "type": "response"}], "context": []}
    b = {"signature": "s", "events": [{"id": "e1", "text": "Police arrested 5 men in Pune"}],
         "claims": [{"id": "c1", "text": "Traffic was diverted for two hours"}],
         "relations": [{"from": "c1", "to": "e1", "type": "response"}], "context": []}
    out = _merge_pieces([a, b])
    assert [e["id"] for e in out["events"]] == ["e1"]            # the repeat is gone
    assert {c["id"] for c in out["claims"]} == {"c1", "p2-c1"}
    assert {"from": "p2-c1", "to": "e1", "type": "response"} in out["relations"]   # remapped onto the survivor
    assert all(r["from"] != r["to"] for r in out["relations"])


def test_schema_fields_are_closed_and_counted():
    from nishpaksh import extract
    extract.SCHEMA.clear()
    ex = extract.normalize_extraction({"signature": "s", "events": [
        {"id": "e1", "text": "Police arrested 5 men", "stance": "maybe", "polarity": "pos", "certainty": "stated"},
        {"id": "e2", "text": "The bridge may collapse", "stance": "asserts", "polarity": "pos", "certainty": "possible"},
        {"id": "e3", "text": "Talks will begin", "stance": "asserts"}]})
    a, b, c = ex["events"]
    assert a["stance"] == "attributes"                      # an unknown stance is never the article's own voice
    assert b["certainty"] == "possible"                     # either reader saying possible makes it possible
    assert c["polarity"] in ("pos", "unknown") and c["certainty"] in ("stated", "unknown")
    assert extract.SCHEMA["stance_invalid"] == 1 and extract.SCHEMA["certainty_missing"] == 1


def test_past_the_budget_the_central_pieces_are_kept_not_the_first_ones():
    from nishpaksh import extract
    parts = ["Opening paragraph about the flood in Assam and rescue teams."] + \
            ["Cricket scores and film releases of the week."] + \
            [f"Flood relief camps in Assam, rescue teams and the flood toll, part {i}." for i in range(4)] + \
            ["Film releases and cricket scores again."]
    kept = extract._most_central(parts, 3)
    assert kept[0] == parts[0] and len(kept) == 3
    assert not any("Cricket" in k or "cricket" in k for k in kept)


def test_slots_is_empty_without_a_parse_and_never_raises():
    from nishpaksh import extract
    assert isinstance(extract.slots("Nobody here."), str)


def test_tavily_failure_is_a_wait_not_a_verdict():
    import datetime as dt
    from nishpaksh import extract
    now = dt.datetime(2026, 10, 26, 12, tzinfo=dt.timezone.utc)
    a = {"extraction": None, "extract_failures": 0, "published_at": now}
    assert extract._tavily_due(a, now)
    a["extraction"] = {"tavily": {"fails": 1, "at": (now - dt.timedelta(hours=3)).isoformat()}}
    assert not extract._tavily_due(a, now)
    a["extraction"] = {"tavily": {"fails": 1, "at": (now - dt.timedelta(hours=13)).isoformat()}}
    assert extract._tavily_due(a, now)
    a["extraction"] = {"tavily": {"fails": 3, "at": (now - dt.timedelta(days=9)).isoformat()}}
    assert not extract._tavily_due(a, now)


def test_greedy_prefers_new_coverage_and_respects_the_budget():
    from nishpaksh import selection
    items = [("a", {1, 2}), ("b", {1, 2}), ("c", {3})]
    got = selection.greedy(items, 2, lambda i: 1, lambda i, ch: len(i[1] - set().union(*[c[1] for c in ch]) if ch else i[1]))
    assert [g[0] for g in got] == ["a", "c"]

from nishpaksh import evidence, extract


def test_numbering_and_pointers_resolve_to_the_reports_own_sentences():
    text = "Police arrested 17 men near Kalka. The minister visited the site. Rain fell on Sunday."
    numbered, sents = evidence.number(text)
    assert numbered.startswith("[1] Police arrested 17 men near Kalka.") and len(sents) == 3
    assert evidence.span([1], sents, "Police arrested 17 men") == sents[0]
    assert evidence.span(["[2]"], sents, "The minister visited") == sents[1]


def test_a_pointer_to_a_sentence_without_the_statements_figure_is_dropped():
    sents = ["Police arrested 17 men near Kalka.", "The minister visited the site."]
    evidence.STATS.clear()
    assert evidence.span([2], sents, "Police arrested 17 men") is None
    assert evidence.span([9], sents, "x") is None
    assert evidence.span(None, sents, "x") is None
    assert evidence.STATS["no_shared_anchor"] == 1 and evidence.STATS["out_of_range"] == 1


def test_resolve_spans_sets_src_text():
    ex = extract.normalize_extraction({"signature": "s", "events": [
        {"id": "e1", "text": "Police arrested 17 men", "src": [1], "stance": "asserts"}]})
    extract.resolve_spans(ex, ["Police arrested 17 men near Kalka."], "en")
    assert ex["events"][0]["src_text"] == "Police arrested 17 men near Kalka."
    assert extract._rel(ex["events"][0])["span"].startswith("Police arrested")

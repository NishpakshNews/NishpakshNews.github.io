from nishpaksh import checkworthy, factuality, nlp


def _parse(text):
    """Stand-in parse: 'may'/'might' are modals attached to the next word, 'not' a negation of the root, the last word the root."""
    import re
    ms = list(re.finditer(r"[A-Za-z]+", text))
    root = len(ms) - 1
    out = []
    for i, m in enumerate(ms):
        w = m.group(0).lower()
        tag = "MD" if w in ("may", "might", "could", "will") else "NN"
        dep = "ROOT" if i == root else "neg" if w == "not" else "aux" if tag == "MD" else "dep"
        out.append(nlp.Tok(i, m.group(0), m.start(), m.end(), w, tag, "X", dep, root))
    return out


def test_possibility_and_negation_come_from_the_parse(monkeypatch):
    monkeypatch.setattr(nlp, "parse", _parse)
    assert factuality.read("The bridge may collapse") == {"polarity": "pos", "certainty": "possible"}
    assert factuality.read("The bridge did not collapse") == {"polarity": "neg", "certainty": "stated"}
    assert factuality.read("The bridge will collapse")["certainty"] == "stated"


def test_a_possible_statement_is_never_a_checkable_fact(monkeypatch):
    monkeypatch.setattr(nlp, "parse", _parse)
    assert checkworthy.classify(["The bridge may collapse", "Police arrested the engineer"]) == [False, True]


def test_no_parse_changes_nothing(monkeypatch):
    monkeypatch.setattr(nlp, "parse", lambda t: [])
    assert factuality.read("The bridge may collapse")["certainty"] == "unknown"

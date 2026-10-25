from nishpaksh import langcheck


def test_issues_are_counted_and_names_spelling_left_out():
    langcheck.set_backend(lambda t: [("AGREEMENT", "GRAMMAR", "x"), ("MORFOLOGIK", "TYPOS", "y")] if "was" in t else [])
    try:
        out = langcheck.article_stats([[{"text": "They was late."}, {"text": "Fine."}]])
        assert out == {"checked": 2, "issues": 1, "by_rule": {"AGREEMENT": 1}}
    finally:
        langcheck.set_backend(None)


def test_unavailable_is_none_not_zero():
    langcheck.set_backend(None)
    langcheck._tool = False
    assert langcheck.article_stats([[{"text": "x"}]]) is None
    langcheck._tool = None

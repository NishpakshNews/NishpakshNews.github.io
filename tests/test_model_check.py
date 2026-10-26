from nishpaksh.tools import model_check


def test_timed_reports_errors_and_ok():
    assert model_check.timed(lambda: {"x": 1})["ok"] is True
    r = model_check.timed(lambda: 1 / 0)
    assert r["ok"] is False and "ZeroDivisionError" in r["error"]


def test_snapshot_never_raises_and_has_keys():
    s = model_check.snapshot()
    assert {"nli", "embed", "spacy", "langtool"} <= set(s) or "error" in s


def test_embed_check_flags_fallback_with_fake_backend():
    r = model_check.embed_check()
    assert r["how"] in ("bi-encoder", "tfidf") and "fallback" in r

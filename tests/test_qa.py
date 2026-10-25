from nishpaksh import qa


def test_changed_figure_and_swapped_name_are_found(monkeypatch):
    qa.set_backend(lambda pairs: [("19", 0.9) for _ in pairs])
    try:
        assert qa.mismatches("Police arrested 17 men near the bridge.", "Police arrested 19 men near the bridge.") == ["17"]
        qa.set_backend(lambda pairs: [("19", 0.2) for _ in pairs])        # not confident: nothing
        assert qa.mismatches("Police arrested 17 men.", "Police arrested 19 men.") == []
        qa.set_backend(lambda pairs: [("seventeen", 0.9) for _ in pairs])  # the same figure, spelled
        assert qa.mismatches("Police arrested 17 men.", "Police arrested seventeen men.") == []
        qa.set_backend(lambda pairs: [None for _ in pairs])                # could not ask: nothing
        assert qa.mismatches("Police arrested 17 men.", "x") == []
    finally:
        qa.set_backend(None)


def test_no_model_is_not_a_problem():
    qa.set_backend(None)
    assert isinstance(qa.mismatches("Police arrested 17 men.", "Police arrested 19 men."), list)

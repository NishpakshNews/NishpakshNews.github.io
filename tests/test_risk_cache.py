"""The express reader remembers its scores across runs and stops at a time budget (risk.py, Oct 28 2026: one run spent 76
minutes re-reading headlines it had read the hour before)."""
from nishpaksh import nli, risk

DEFS = {"harm": {"crime": "The news is about a crime."}}


def counting_backend(calls):
    def fn(pairs):
        calls.append(len(pairs))
        return [(0.9 if "arrest" in a else 0.1, 0.05, 0.05) for a, _ in pairs]
    return fn


def test_a_headline_is_read_once_and_remembered_by_the_next_run():
    calls = []
    nli.set_backend(counting_backend(calls))
    try:
        assert risk.reasons(["Police arrest man"], [None], DEFS, {}) == ["harm:crime"]
        saved = risk.dump_cache()
        risk.load_cache(saved)                            # the next run: a new process, the stored scores
        nli._cache.clear()
        assert risk.reasons(["Police arrest man"], [None], DEFS, {}) == ["harm:crime"]
        assert calls == [1]                               # the model was asked once, not twice
        assert risk.STATS["cached"] == 1
    finally:
        nli.set_backend(None)


def test_out_of_time_leaves_unread_never_fine_and_the_next_run_goes_on():
    calls = []
    nli.set_backend(counting_backend(calls))
    try:
        risk.set_budget(-1)                               # the budget is already used
        assert risk.reasons(["Fine headline"], [None], DEFS, {}) == [risk.UNREAD]
        assert calls == [] and risk.STATS["out_of_time"] == 1
        risk.set_budget(60)                               # the next run
        assert risk.reasons(["Fine headline"], [None], DEFS, {}) == [None]
    finally:
        nli.set_backend(None)


def test_a_fired_concern_still_excludes_when_other_pairs_ran_out_of_time():
    defs = {"harm": {"crime": "The news is about a crime.", "death": "Someone died."}}
    nli.set_backend(lambda pairs: [(0.9, 0.05, 0.05) for _ in pairs])
    try:
        risk.load_cache({risk._key("Police arrest man", "The news is about a crime."): 0.9})
        risk.set_budget(-1)
        assert risk.reasons(["Police arrest man"], [None], defs, {}) == ["harm:crime"]
    finally:
        nli.set_backend(None)


def test_the_cache_is_bounded():
    risk.load_cache({str(i): 0.1 for i in range(risk.CACHE_MAX + 5)})
    assert len(risk.dump_cache()) == risk.CACHE_MAX

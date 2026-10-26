"""E1: an invalid stance is asked once more; only closed answers are taken."""
from types import SimpleNamespace

from nishpaksh import extract, reask


class R:
    def __init__(self, answers, quota=1):
        self.answers, self.quota, self.calls = answers, quota, 0

    def remaining_now(self, tier):
        return self.quota

    def call(self, tier, prompt, **kw):
        self.calls += 1
        return SimpleNamespace(data={"answers": self.answers}, text="")


def _ex(*stances, who="article"):
    data = {"signature": "s", "claims": [{"id": f"c{i}", "text": f"Statement {i} happened.", "stance": s,
                                          "attributed_to": who} for i, s in enumerate(stances)]}
    return extract.normalize_extraction(data)


def setup_function(_):
    reask.reset_run()
    reask.STATS.clear()


def test_invalid_is_flagged_missing_is_not():
    ex = _ex("claims", None, "asserts")
    flags = [c["stance_invalid"] for c in ex["claims"]]
    assert flags == [True, False, False]


def test_closed_answer_replaces_default():
    ex = _ex("claims", "reports", who="Police")
    r = R(["attributes", "denies"])
    assert reask.check(ex, r) == 2 and r.calls == 1
    assert [c["stance"] for c in ex["claims"]] == ["attributes", "denies"]
    assert not any(c["stance_defaulted"] for c in ex["claims"])


def test_bad_answer_or_asserts_with_named_speaker_keeps_default():
    ex = _ex("claims", "reports", who="Police")
    assert reask.check(ex, R(["maybe", "asserts"])) == 0
    assert all(c["stance"] == "attributes" and c["stance_defaulted"] for c in ex["claims"])


def test_no_quota_no_call_and_wrong_count_ignored():
    ex = _ex("claims")
    r = R(["asserts"], quota=0)
    assert reask.check(ex, r) == 0 and r.calls == 0
    assert reask.check(_ex("claims"), R(["asserts", "denies"])) == 0


def test_coreference_counts_dangling_pronouns_and_unknown_is_not_zero():
    from nishpaksh import coref
    text = "He left. Modi spoke. He said so."
    coref.set_backend(lambda t: [[(0, 2), (9, 13), (text.rfind('He'), text.rfind('He') + 2)]])
    try:
        assert coref.dangling(text) == {"pronouns": 2, "dangling": 1}
        coref.set_backend(lambda t: None)
        assert coref.dangling(text) is None
    finally:
        coref.set_backend(None)

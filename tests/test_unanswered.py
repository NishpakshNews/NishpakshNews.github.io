"""A model question that could not be asked is "not answered", never "no" or "unsure" (F94, F123).

Before: a quota blip or an error made match.same_facts / covers_facts return False and check_conflicts "unsure";
the callers stored those in the story's analysis, so a real same-fact pair stayed apart and a real dispute stayed
doubtful until the entry aged out. Now the three functions return None for such a pair, and nothing remembers it."""
from types import SimpleNamespace

from nishpaksh import disputes, match
from nishpaksh.router import QuotaExhausted

PAIR = ("Police arrested the engineer on Friday.", "The engineer was arrested by police on Friday.")


class Dead:
    """A router whose every call fails: no quota."""
    def call(self, *a, **k):
        raise QuotaExhausted()


class Boom:
    def call(self, *a, **k):
        raise RuntimeError("503")


class Script:
    """Answers each call from a list of {'results': [...]} dicts (None = the call fails)."""
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def call(self, *a, **k):
        self.calls += 1
        r = self.replies.pop(0)
        if r is None:
            raise RuntimeError("503")
        return SimpleNamespace(data=r)


def _res(*answers):
    return {"results": [{"n": i + 1, "answer": a} for i, a in enumerate(answers)]}


def test_a_failed_asking_is_not_an_answer():
    for router in (None, Dead(), Boom()):
        firsts = {}
        assert match.same_facts(router, [PAIR, PAIR], firsts) == [None, None]
        assert not any(v for v in firsts.values())          # nothing recorded as a first "yes"
        assert match.covers_facts(router, [PAIR]) == [None]
        assert match.check_conflicts(router, [PAIR]) == [None]


def test_real_answers_are_still_answers():
    firsts = {}
    # first asking: same / different; second asking (only for the "same"): same
    router = Script(_res("same", "different"), _res("same"))
    assert match.same_facts(router, [PAIR, PAIR], firsts) == [True, False]
    assert firsts == {0: True, 1: False}
    assert match.covers_facts(Script(_res("yes", "no"), _res("yes")), [PAIR, PAIR]) == [True, False]
    assert match.check_conflicts(Script(_res("cannot_both_be_true", "both_true", "unsure")), [PAIR] * 3) == [
        "cannot_both_be_true", "both_true", "unsure"]


def test_a_second_asking_that_fails_leaves_the_pair_unanswered():
    firsts = {}
    router = Script(_res("same"), None)                      # first asking says same, the swapped one fails
    assert match.same_facts(router, [PAIR], firsts) == [None]
    assert firsts == {0: True}                               # the first answer is still a real answer
    assert match.covers_facts(Script(_res("yes"), None), [PAIR]) == [None]


def test_a_missing_item_is_unanswered_not_different():
    assert match.same_facts(Script({"results": []}), [PAIR]) == [None]
    assert match.covers_facts(Script({"results": []}), [PAIR]) == [None]
    assert match.check_conflicts(Script({"results": []}), [PAIR]) == [None]


A, B = "The blast killed 40 people in the market.", "The blast killed 50 people in the market."


def test_a_failed_dispute_check_is_not_cached_and_is_asked_again():
    texts = {1: A, 2: B}
    cache: dict = {}
    disp, doubtful, _ = disputes.judge(Dead(), texts, {}, set(), set(), cache)
    assert cache == {} and doubtful == {1, 2} and not disp   # doubtful for now: no amber, no green
    router = Script(_res("cannot_both_be_true", "cannot_both_be_true"))   # both orders in one batch
    disp, doubtful, _ = disputes.judge(router, texts, {}, set(), set(), cache)
    assert router.calls >= 1                                 # asked again: nothing stood in the way
    assert disp == {(1, 2)} and not doubtful

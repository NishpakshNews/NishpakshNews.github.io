"""Could not ask is not no (Oct 25 2026): a pair the local NLI model could not read is None, never "different"."""
from nishpaksh import disputes, match, nli

PAIR = ("The blast killed 40 people.", "The blast killed 50 people.")
A, B = "The blast killed 40 people in the market.", "The blast killed 50 people in the market."
YES, NO, CON = (0.95, 0.03, 0.02), (0.1, 0.85, 0.05), (0.03, 0.07, 0.90)


def test_a_pair_the_model_could_not_read_is_not_an_answer():
    nli.set_backend(lambda ps: [None] * len(ps))
    firsts = {}
    assert match.same_facts(None, [PAIR, PAIR], firsts) == [None, None]
    assert firsts == {}                                      # nothing recorded
    assert match.covers_facts(None, [PAIR]) == [None]
    assert match.check_conflicts(None, [PAIR]) == [None]


def test_real_answers_are_still_answers():
    firsts = {}
    nli.set_backend(lambda ps: [YES if a == b else NO for a, b in ps])
    assert match.same_facts(None, [("x", "x"), ("x", "y")], firsts) == [True, False]
    assert firsts == {0: True, 1: False}
    assert match.covers_facts(None, [("x", "x"), ("x", "y")]) == [True, False]
    assert match.check_conflicts(None, [("x", "y")]) == ["both_true"]
    nli.set_backend(lambda ps: [CON for _ in ps])
    assert match.check_conflicts(None, [PAIR]) == ["cannot_both_be_true"]


def test_one_direction_unread_leaves_the_pair_unanswered():
    nli.set_backend(lambda ps: [YES if a == "x" else None for a, b in ps])
    assert match.same_facts(None, [("x", "y")]) == [None]


def test_a_failed_dispute_check_is_not_cached_and_is_asked_again():
    texts = {1: A, 2: B}
    cache: dict = {}
    nli.set_backend(lambda ps: [None] * len(ps))
    disp, doubtful, _ = disputes.judge(None, texts, {}, set(), set(), cache)
    assert cache == {} and doubtful == {1, 2} and not disp   # doubtful for now: no amber, no green
    nli.set_backend(lambda ps: [CON for _ in ps])
    disp, doubtful, _ = disputes.judge(None, texts, {}, set(), set(), cache)
    assert disp == {(1, 2)} and not doubtful

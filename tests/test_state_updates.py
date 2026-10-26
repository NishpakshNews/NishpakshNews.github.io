"""A state that changed is an update, not two lines (disputes.py, owner Oct 26 2026: "orange alert Sunday, red alert today")."""
import datetime as dt

import numpy as np
import pytest

from nishpaksh import disputes, embed, nli

ORANGE = "An orange alert is in force for the Odisha coast on Sunday."
RED = "A red alert is in force for the Odisha coast today."
CON, BOTH = (0.03, 0.07, 0.90), (0.9, 0.05, 0.05)


@pytest.fixture(autouse=True)
def close_texts():
    embed.set_backend(lambda texts: np.tile(np.array([[0.6, 0.8]]), (len(texts), 1)))
    yield
    embed.set_backend(None)


def _at(day, hour=9):
    return [dt.datetime(2026, 10, day, hour, 0)]


def test_the_same_question_about_a_state_with_another_answer_is_a_candidate():
    assert disputes.candidate(ORANGE, RED, sim=0.9, need=0.7) == "state"


def test_a_time_word_alone_is_not_a_state():
    assert disputes.candidate("A red alert is in force for the Odisha coast today.",
                              "A red alert is in force for the Odisha coast yesterday.", sim=0.95, need=0.7) is None


def test_other_names_or_figures_are_not_a_state():
    assert disputes.candidate("A red alert is in force for the Odisha coast.", "A red alert is in force for the Kerala coast.",
                              sim=0.9, need=0.7) is None
    assert disputes.candidate("An orange alert covers 5 districts of the Odisha coast.",
                              "A red alert covers 7 districts of the Odisha coast.", sim=0.9, need=0.7) != "state"


def test_two_lines_that_share_few_words_are_not_a_state():
    assert disputes.candidate("The court heard the plea.", "The court dismissed the plea.", sim=0.95, need=0.7) is None


def test_a_state_that_changed_between_the_reports_is_an_update():
    nli.set_backend(lambda ps: [CON] * len(ps))
    disp, doubtful, upd = disputes.judge(None, {1: ORANGE, 2: RED}, {1: _at(18), 2: _at(20)}, set(), set(), {})
    assert upd == {1: 2} and not disp and not doubtful


def test_the_reports_may_come_in_either_order():
    nli.set_backend(lambda ps: [CON] * len(ps))
    _, _, upd = disputes.judge(None, {1: ORANGE, 2: RED}, {1: _at(20), 2: _at(18)}, set(), set(), {})
    assert upd == {2: 1}


def test_two_states_at_the_same_time_are_a_dispute():
    nli.set_backend(lambda ps: [CON] * len(ps))
    disp, doubtful, upd = disputes.judge(None, {1: ORANGE, 2: RED}, {1: _at(20, 9), 2: _at(20, 9)}, set(), set(), {})
    assert disp == {(1, 2)} and not upd and not doubtful


def test_both_can_be_true_is_nothing_and_never_doubtful():
    nli.set_backend(lambda ps: [BOTH] * len(ps))
    disp, doubtful, upd = disputes.judge(None, {1: ORANGE, 2: RED}, {1: _at(18), 2: _at(20)}, set(), set(), {})
    assert not disp and not upd and not doubtful


def test_a_state_pair_the_model_could_not_read_changes_nothing():
    nli.set_backend(lambda ps: [None] * len(ps))
    disp, doubtful, upd = disputes.judge(None, {1: ORANGE, 2: RED}, {1: _at(18), 2: _at(20)}, set(), set(), {})
    assert not disp and not upd and not doubtful

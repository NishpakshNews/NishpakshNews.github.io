"""A figure is the same figure when it is the other one ROUNDED at its own written precision; a moved figure is an update
only when something orders the two (owner, Oct 26 2026)."""
import datetime as dt

from nishpaksh import disputes, figures
from nishpaksh.relate import Profile, numbers_close, numbers_near


def _agree(a, b):
    return numbers_close(Profile(a), Profile(b))


def test_the_unit_is_where_the_outlet_stopped_writing():
    u = lambda t: figures.unit(figures.find(t)[0])  # noqa: E731
    assert abs(u("82.10") - 0.01) < 1e-9
    assert abs(u("125.27 million") - 1e4) < 1e-3
    assert abs(u("125 million") - 1e6) < 1e-3
    assert u("50") == 1.0 and u("twenty-six") == 1.0 and u("1,000") == 1.0


def test_rounding_is_the_same_figure_a_moved_price_is_not():
    assert _agree("Output was 125.27 million tonnes", "Output was about 125 million tonnes")
    assert _agree("It rose 6.14 per cent", "It rose 6.1 per cent")
    assert not _agree("Brent traded at $82.10", "Brent traded at $82.35")        # both exact to 0.01: no rounding explains it
    assert not _agree("The toll rose to 42", "The toll is 40")                    # counts are exact
    assert not _agree("It cost 5 crore", "It cost 4.6 crore")                     # the precision test alone would pass this
    assert numbers_near(Profile("Brent traded at $82.10"), Profile("Brent traded at $82.35"))


def test_a_little_moved_figure_is_a_series_candidate_a_big_one_a_number():
    a, b = "Brent crude traded at $82.10 a barrel", "Brent crude traded at $82.35 a barrel"
    assert disputes.candidate(a, b) == "series"
    assert disputes.candidate("Police said the death toll in the bus crash has risen to 40 people",
                              "Police said the death toll in the bus crash has risen to 80 people") == "number"
    assert disputes.candidate("Output was 125.27 million tonnes", "Output was about 125 million tonnes") is None


def test_the_order_comes_from_the_reports_or_the_clock_in_the_text():
    t0 = dt.datetime(2026, 10, 26, 10, 0)
    a, b = "Brent crude traded at $82.10 a barrel", "Brent crude traded at $82.35 a barrel"
    assert disputes.series_order(a, b, [t0], [t0 + dt.timedelta(hours=2)]) == 1
    assert disputes.series_order(a, b, [t0], [t0 + dt.timedelta(minutes=30)]) == 0          # nothing says which is later
    ca, cb = "Brent crude traded at $82.10 a barrel at 10:05 am", "Brent crude traded at $82.35 a barrel at 10:40 am"
    assert disputes.series_order(ca, cb, [t0], [t0 + dt.timedelta(minutes=30)]) == 1
    assert disputes.series_order(cb, ca, [t0], [t0 + dt.timedelta(minutes=30)]) == -1


def test_judge_makes_an_update_never_a_dispute_and_never_asks_the_model():
    t0 = dt.datetime(2026, 10, 26, 10, 0)
    texts = {1: "Brent crude traded at $82.10 a barrel at 10:05 am", 2: "Brent crude traded at $82.35 a barrel at 10:40 am",
             3: "Brent crude traded at $82.40 a barrel"}

    class NoModel:
        def __getattr__(self, _):
            raise AssertionError("the model must not be asked")
    from nishpaksh import match
    saved = match.check_conflicts
    def _never(router, pairs):
        assert not pairs, "the model must not be asked"
        return []
    match.check_conflicts = _never
    try:
        disputes_, doubtful, updates = disputes.judge(NoModel(), texts, {1: [t0], 2: [t0 + dt.timedelta(minutes=30)],
                                                                          3: [t0 + dt.timedelta(minutes=31)]}, set(), set(), {})
    finally:
        match.check_conflicts = saved
    assert updates == {1: 2} and not disputes_ and not doubtful

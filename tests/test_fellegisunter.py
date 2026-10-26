import random

from nishpaksh import fellegisunter as fs
from nishpaksh.relate import Profile


def _story():
    base = ["The company reported a profit of {n} crore in the quarter", "Quarterly profit of the company was {n} crore",
            "Police arrested {w} in {c} on Monday", "{w} was arrested by police in {c}"]
    random.seed(3)
    texts = {}
    i = 0
    for n in (500, 700, 900, 1100, 1300, 1500):
        for t in base[:2]:
            texts[i] = t.format(n=n); i += 1
    for w, c in (("Rakesh", "Delhi"), ("Anil", "Pune"), ("Vijay", "Surat"), ("Sunil", "Jaipur"), ("Manoj", "Agra"), ("Ravi", "Patna")):
        for t in base[2:]:
            texts[i] = t.format(w=w, c=c); i += 1
    return {k: Profile(v) for k, v in texts.items()}


def test_model_fits_and_ranks_true_pairs_first():
    prof = _story()
    model = fs.fit_story(prof)
    assert model is not None
    true_pair, false_pair = (0, 1), (0, 12)
    assert model.weight(fs.gamma(prof[0], prof[1])) > model.weight(fs.gamma(prof[0], prof[12]))
    assert fs.order([false_pair, true_pair], prof)[0] == true_pair


def test_too_small_a_story_is_left_in_order():
    prof = {0: Profile("A fire broke out"), 1: Profile("A fire broke out in the market")}
    assert fs.order([(0, 1), (1, 0)], prof) == [(0, 1), (1, 0)]


def test_bands_add_up():
    prof = _story()
    pairs = [(a, b) for a in prof for b in prof if a < b]
    b = fs.bands(pairs, prof)
    assert b["upper"] + b["lower"] + b["middle"] == b["pairs"] == len(pairs)


def test_time_level_is_graded_and_unknown_is_its_own_level():
    day = lambda d: {"start": f"2026-10-{d:02d}"}  # noqa: E731
    assert fs.time_level(day(5), day(5)) == 3
    assert fs.time_level(day(5), day(6)) == 2
    assert fs.time_level(day(5), day(9)) == 0
    assert fs.time_level(day(5), None) == 1 and fs.time_level(None, None) == 1
    assert fs.time_level({"start": "2026-10-05", "end": "2026-10-08"}, day(7)) == 3     # ranges that overlap


def test_gamma_has_a_time_field_and_old_calls_still_work():
    a, b = Profile("Police arrested Ravi in Patna"), Profile("Ravi was arrested by police in Patna")
    assert len(fs.gamma(a, b)) == len(fs.FIELDS) == 6
    assert fs.gamma(a, b)[-1] == 1
    assert fs.gamma(a, b, {"start": "2026-10-05"}, {"start": "2026-10-05"})[-1] == 3


def test_times_that_agree_rank_a_pair_higher_when_the_story_has_dated_lines():
    prof = _story()
    times = {k: {"start": "2026-10-05"} if k < 12 else {"start": "2026-10-%02d" % (6 + k % 4)} for k in prof}
    model = fs.fit_story(prof, times)
    assert model is not None
    same = fs._g(prof, times, 0, 1)
    assert same[-1] == 3
    assert fs.order([(0, 12), (0, 1)], prof, times)[0] == (0, 1)

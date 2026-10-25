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

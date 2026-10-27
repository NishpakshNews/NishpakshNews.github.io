"""The news is what the outlets' own headlines say (news.head_support), not the best-reported setting fact.
Story 46081 (Oct 27 2026): seven headlines said "4 districts declared drought-hit"; a rainfall figure folded from four outlets led."""
from nishpaksh import news

TITLES = ["Gujarat declares 4 districts drought-hit",
          "Gujarat govt. declares Devbhoomi Dwarka, Kutch, Jamnagar and Porbandar as drought-affected",
          "Gujarat declares 4 districts as drought-affected",
          "Gujarat Declares 4 Districts Drought-Hit Despite 89% Rainfall: Govt Announces Major Relief Package"]


def item(i, text, outlets):
    return {"id": i, "kind": "event", "role": "core", "verdict": "unverified", "text": text, "time": None,
            "n_articles": len(outlets), "sources": [{"outlet": o} for o in outlets]}


def items():
    return [item(1, "The Gujarat government declared Devbhoomi Dwarka, Kutch, Porbandar and Jamnagar districts as drought-hit.", ["A", "B"]),
            item(2, "Devbhoomi Dwarka, Porbandar, Jamnagar and Kutch had rainfall deficits of 83.5%, 69.1%, 56.7% and 42.4% respectively by October 15.",
                 ["C", "D", "E", "F"])]


def test_the_headlines_decide_what_is_news():
    assert news.pick_news(items(), TITLES)[0] == 1


def test_without_headlines_nothing_changes():
    assert news.pick_news(items(), None) == news.pick_news(items())
    assert news.head_support(items(), ["only one title"]) == {}

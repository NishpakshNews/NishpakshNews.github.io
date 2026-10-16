"""The learners' base (learning.py) and the titles learner with its devil's advocate (learn.py, session 9)."""
import datetime as dt
import types

import pytest
import yaml

from nishpaksh import learn
from nishpaksh import learning as L

T0 = dt.datetime(2026, 10, 1, 9)


def day(n):
    return T0 + dt.timedelta(days=n)


# -- the base ------------------------------------------------------------------------------------------------------

def test_memory_adds_each_article_once_and_never_state_media():
    c = L.Candidate("title", "Skipper")
    assert c.add(1, "owner:a", 10, "2026-10-01", day(0))
    assert not c.add(1, "owner:a", 10, "2026-10-01", day(0))                    # read again: nothing new
    assert not c.add(2, None, 10, "2026-10-01", day(0))                          # state media (no source key)
    assert c.add(3, "owner:b", 11, "2026-10-04", day(3))
    assert c.sources == ["owner:a", "owner:b"] and c.days == {"2026-10-01": 1, "2026-10-04": 1}


def test_the_bar_names_the_first_rule_missing():
    bar = L.Bar(sources=3, days=3, max_day_share=0.5, probation_days=7)
    c = L.Candidate("title", "x")
    for i, (src, d) in enumerate([("a", 0), ("b", 0), ("c", 0)]):
        c.add(i, f"owner:{src}", i, L.day_of(day(d)), day(d))
    assert bar.fails(c) == ["days", "one_day", "probation"]
    for i, (src, d) in enumerate([("d", 3), ("e", 8)], start=10):
        c.add(i, f"owner:{src}", i, L.day_of(day(d)), day(d))
    assert bar.fails(c) == ["one_day"]                                           # 3 of 5 on the first day
    c.add(20, "owner:f", 20, L.day_of(day(9)), day(9))
    assert bar.fails(c) == []


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_memory_round_trips_in_the_newsroom_and_forgets_the_stale(store):
    from sqlalchemy import inspect
    assert "learn_candidates" in inspect(store.engine).get_table_names()
    assert "learn_candidates" not in inspect(store.readers.engine).get_table_names()
    c = L.Candidate("title", "Skipper")
    c.add(1, "owner:a", 7, "2026-10-01", day(0))
    c.bump("sightings")
    old = L.Candidate("title", "Stale")
    old.add(2, "owner:b", 8, "2026-09-01", day(-30))
    L.save(store, {"Skipper": c, "Stale": old}, day(1))
    back = L.load(store, "title")
    assert back["Skipper"].facets == {"sightings": 1} and back["Skipper"].stories == [7]
    assert L.save(store, back, day(31))["expired"] == 2 - 1 and "Stale" not in L.load(store, "title")


class Router:
    def __init__(self, answers, remaining=10):
        self.answers, self.remaining, self.prompts = answers, remaining, []

    def remaining_now(self, tier):
        assert tier == "quality"
        return self.remaining

    def call(self, tier, prompt, **kw):
        self.prompts.append(prompt)
        a = self.answers[len(self.prompts) - 1] if isinstance(self.answers[0], list) else self.answers
        return types.SimpleNamespace(data={"answers": a}, text="")


def test_ask_twice_keeps_only_agreed_answers():
    r = Router([["title", "label", "title"], ["title", "title", "unsure"]])
    assert L.ask_twice(r, "q", ["a", "b", "c"], ("title", "label", "unsure")) == ["title", None, None]
    assert "unsure, label, title" in r.prompts[1]                               # the choices in reverse order
    assert L.ask_twice(Router(["title"], remaining=0), "q", ["a"], ("title", "label")) == [None]


# -- titles -------------------------------------------------------------------------------------------------------

def corpus(word="Skipper", people=("Rohit Sharma", "Harmanpreet Kaur", "Shubman Gill")):
    arts, names = [], {}
    for i, p in enumerate(people * 2):
        arts.append({"id": i, "text": f"India won after {word} {p} scored a century, and the {word.lower()} said "
                                      f"the {word.lower()} was happy."})
        names[i] = {p}
    return arts, names


def info_for(arts, start=0, anchor_every=3):
    return {a["id"]: {"source": f"owner:o{a['id']}", "story": a["id"], "when": day(start + 2 * k),
                      "anchor": k % anchor_every == 0} for k, a in enumerate(arts)}


def test_a_shared_title_passes_the_bar_and_the_model_and_is_proposed(tmp_path):
    arts, names = corpus()
    seen = learn.sightings(arts, names)
    assert {s.word for s in seen} == {"Skipper"} and not any(s.label or s.dispute or s.quoted for s in seen)
    cands = {}
    learn.record(cands, seen, info_for(arts), " ".join(a["text"] for a in arts))
    c = cands["Skipper"]
    assert L.Bar.fails(learn.BAR, c) == [] and learn.extra_rules(c) == []
    r = Router(["title"])
    fresh, review, used = learn.decide(cands, router=r, no=set(), yes=set(), now=day(11))
    assert [x.key for x in fresh] == ["Skipper"] and c.status == "proposed" and used
    path = tmp_path / "titles_proposed.yaml"
    learn.write_proposals(path, [learn.entry(c)], [])
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["proposed"][0]["forms"] == ["Skipper"] and doc["review"] == []
    assert "century" not in path.read_text(encoding="utf-8")                    # no article text in the public repo


def test_pappu_is_a_label_not_a_title():
    # one person, "dubbed", "jibe": every code check objects
    arts = [{"id": i, "text": f"The minister took a jibe and dubbed him Pappu Rahul Gandhi, and the pappu remark "
                              f"spread; critics called it a pappu jibe."} for i in range(6)]
    names = {i: {"Rahul Gandhi"} for i in range(6)}
    cands = {}
    learn.record(cands, learn.sightings(arts, names), info_for(arts), " ".join(a["text"] for a in arts))
    v = learn.advocate(cands["Pappu"])
    assert v.state == "block" and "never list" in v.reason
    cands["Pappu"].key = "Babua"                                               # not on the list: still blocked
    v = learn.advocate(cands["Pappu"])
    assert v.state == "block" and "Rahul Gandhi" in v.reason


def test_label_and_dispute_cues_block_even_when_the_word_is_shared():
    arts, names = corpus("Chotu")
    for a in arts:
        a["text"] = a["text"].replace("after Chotu", "after critics dubbed Chotu")
    cands = {}
    learn.record(cands, learn.sightings(arts, names), info_for(arts), " ".join(a["text"] for a in arts))
    v = learn.advocate(cands["Chotu"])
    assert v.state == "block" and "called" in v.reason


def test_a_loaded_word_or_the_models_label_blocks_and_no_quota_holds():
    arts, names = corpus("Comrade")
    cands = {}
    learn.record(cands, learn.sightings(arts, names), info_for(arts), " ".join(a["text"] for a in arts))
    assert learn.advocate(cands["Comrade"], loaded={"comrade"}).state == "block"
    learn.decide(cands, router=Router(["label"]), no=set(), yes=set(), now=day(11))
    assert cands["Comrade"].status == "blocked" and "model" in cands["Comrade"].reason
    arts, names = corpus("Skipper")
    cands = {}
    learn.record(cands, learn.sightings(arts, names), info_for(arts), " ".join(a["text"] for a in arts))
    learn.decide(cands, router=None, no=set(), yes=set(), now=day(11))
    assert cands["Skipper"].status == "candidate" and cands["Skipper"].reason == learn.WAITING


def test_the_bar_wants_an_anchor_people_and_probation():
    arts, names = corpus(people=("Rohit Sharma",))
    cands = {}
    learn.record(cands, learn.sightings(arts, names), info_for(arts, anchor_every=99), "")
    c = cands["Skipper"]
    assert "people" in learn.extra_rules(c) and "lower_case" in learn.extra_rules(c)
    assert "probation" in learn.BAR.fails(c)                                    # 2 sightings 2 days apart


def test_the_owner_decides_refusal_approval_and_review():
    arts, names = corpus()
    cands = {}
    learn.record(cands, learn.sightings(arts, names), info_for(arts), " ".join(a["text"] for a in arts))
    learn.decide(cands, router=None, no={"skipper"}, yes=set(), now=day(11))
    assert cands["Skipper"].status == "blocked" and cands["Skipper"].reason == "refused by the owner"
    cands["Skipper"].status = "proposed"
    cands["Skipper"].facets["per_person"] = {"Rohit Sharma": 9, "Shubman Gill": 1}
    _, review, _ = learn.decide(cands, router=None, no=set(), yes={"skipper"}, now=day(12))
    assert cands["Skipper"].status == "learned" and review and "Rohit Sharma" in review[0]["reason"]

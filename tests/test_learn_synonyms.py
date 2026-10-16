"""The synonyms learner on the learners' base, with its devil's advocate (learn_synonyms.py, session 10)."""
import datetime as dt
import types

import pytest

from nishpaksh import learn_synonyms as ls
from nishpaksh import learning as L

T0 = dt.datetime(2026, 10, 1, 9)
FRAMES = [("Opposition leaders called the budget {w} in its scale and reach", 1),
          ("The minister said the turnout was {w} for the state election", 1),
          ("Experts described the rainfall as {w} for the month of October", 2)]


def corpus(a="unprecedented", b="historic", frames=FRAMES, both_source=True):
    """Merged statements told by independent outlets in the same words but for one; with `both_source`, one outlet
    writes the first word in one statement and the second in another."""
    by_canon, info, art = {}, {}, 0
    for cid, (frame, story) in enumerate(frames, start=1):
        cl = []
        for k, w in enumerate((a, b)):
            art += 1
            src = "owner:x" if (both_source and cid in (1, 2) and k == cid - 1) else f"owner:o{art}"
            info[art] = {"source": src, "story": story, "when": T0 + dt.timedelta(days=cid)}
            cl.append({"id": art, "article_id": art, "story_id": story, "text": frame.format(w=w), "time": None})
        by_canon[cid] = cl
    groups = {i: v["source"] for i, v in info.items()}
    return by_canon, groups, info


def learned(found_kw=None, **kw):
    by_canon, groups, info = corpus(**(found_kw or {}))
    cands = {}
    ls.record(cands, ls.scan(by_canon, kw.get("conflicts", {}), groups), info)
    return cands


class Router:
    def __init__(self, answer, remaining=10):
        self.answer, self.remaining, self.prompts = answer, remaining, []

    def remaining_now(self, tier):
        return self.remaining

    def call(self, tier, prompt, **kw):
        assert tier == "quality"
        self.prompts.append(prompt)
        n = prompt.count('" and "')
        return types.SimpleNamespace(data={"answers": [self.answer] * n}, text="")


def test_a_pair_past_the_bar_and_the_advocate_is_learned_and_written(tmp_path):
    cands = learned()
    c = cands[ls.pair_key("unprecedented", "historic")]
    assert ls.BAR.fails(c) == [] and ls.extra_rules(c) == []
    assert ls.advocate(c, never=[], struck=[]) == L.CLEAR
    fresh, withdrawn, used = ls.decide(cands, router=Router("same"), now=T0 + dt.timedelta(days=4), never=[], struck=[])
    assert [x.key for x in fresh] == [c.key] and c.status == "learned" and used
    path = tmp_path / "synonyms_learned.yaml"
    assert ls.append([ls.entry(c, dt.date(2026, 10, 5))], path) == 1
    text = path.read_text(encoding="utf-8")
    assert '"historic unprecedented"' in text and "budget" not in text           # counts only, no sentences
    assert ls.append([ls.entry(c, dt.date(2026, 10, 5))], path) == 0


def test_evidence_against_is_remembered_and_blocks():
    by_canon, groups, info = corpus()
    by_canon[9] = [{"id": 99, "article_id": 99, "story_id": 3, "time": None,
                    "text": "The turnout was historic and unprecedented for the state"}]
    cands = {}
    ls.record(cands, ls.scan(by_canon, {}, groups), info)
    c = cands[ls.pair_key("unprecedented", "historic")]
    assert c.facets["against"] is True and ls.advocate(c, never=[], struck=[]).state == "block"
    cands2 = {c.key: c}
    ls.record(cands2, ls.scan(corpus()[0], {}, groups), info)                   # a later clean run does not forget
    assert c.facets["against"] is True


def test_qualifiers_loaded_words_and_framing_splits():
    cands = learned({"a": "alleged", "b": "suspected"})
    v = ls.advocate(cands[ls.pair_key("alleged", "suspected")], never=[], struck=[])
    assert v.state == "block" and "limits a claim" in v.reason
    cands = learned({"a": "protesters", "b": "rioters"})
    c = cands[ls.pair_key("protesters", "rioters")]
    assert ls.advocate(c, loaded={"rioters"}, never=[], struck=[]).state == "block"
    cands = learned({"a": "scandal", "b": "controversy", "both_source": False})
    v = ls.advocate(cands[ls.pair_key("scandal", "controversy")], never=[], struck=[])
    assert v.state == "hold" and "framing split" in v.reason


def test_the_models_changes_blocks_no_quota_holds():
    cands = learned({"a": "scandal", "b": "controversy"})
    c = cands[ls.pair_key("scandal", "controversy")]
    ls.decide(cands, router=Router("changes"), now=T0 + dt.timedelta(days=4), never=[], struck=[])
    assert c.status == "blocked" and "changes" in c.reason
    cands = learned()
    ls.decide(cands, router=None, now=T0 + dt.timedelta(days=4), never=[], struck=[])
    c = cands[ls.pair_key("unprecedented", "historic")]
    assert c.status == "candidate" and c.reason == ls.WAITING


def test_too_little_evidence_waits():
    cands = learned({"frames": FRAMES[:2]})                                       # 2 statements
    c = cands[ls.pair_key("unprecedented", "historic")]
    assert ls.extra_rules(c) == ["statements"]
    ls.decide(cands, router=Router("same"), now=T0, never=[], struck=[])
    assert c.status == "candidate"


def test_a_learned_pair_the_advocate_later_blocks_is_withdrawn(tmp_path):
    cands = learned()
    c = cands[ls.pair_key("unprecedented", "historic")]
    path = tmp_path / "synonyms_learned.yaml"
    ls.append([ls.entry(c, dt.date(2026, 10, 5))], path)
    c.status = "learned"
    _, withdrawn, _ = ls.decide(cands, loaded={"historic"}, router=None, never=[], struck=[])
    assert withdrawn == [c] and c.status == "blocked"
    assert ls.withdraw([c.key], path) == 1 and "historic" not in path.read_text(encoding="utf-8").split("groups:")[1]


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_memory_adds_up_across_runs(store):
    by_canon, groups, info = corpus()
    first = {k: v for k, v in list(by_canon.items())[:1]}
    cands = L.load(store, ls.KIND)
    ls.record(cands, ls.scan(first, {}, groups), info)
    L.save(store, cands, T0)
    cands = L.load(store, ls.KIND)                                              # the next run
    ls.record(cands, ls.scan(by_canon, {}, groups), info)
    c = cands[ls.pair_key("unprecedented", "historic")]
    assert len(c.facets["statements"]) == 3 and len(c.sources) == 5           # article 1 was not counted twice

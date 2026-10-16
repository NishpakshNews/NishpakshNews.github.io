"""The synonyms learner on the learners' base, with its devil's advocate (learn_synonyms.py, session 10), learning
each pair in a context (context plan, session 3)."""
import datetime as dt
import types

import pytest
import yaml

from nishpaksh import learn_synonyms as ls
from nishpaksh import learning as L

T0 = dt.datetime(2026, 10, 1, 9)
FRAMES = [("Opposition leaders called the turnout {w} in the state election", 1),
          ("The minister said the turnout was {w} for the state election", 1),
          ("Experts described the voter turnout as {w} in the state election", 2)]
SECTIONS = {1: "elections", 2: "elections", 3: "elections"}


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
    cands, senses = {}, {}
    ls.record(cands, ls.scan(by_canon, kw.get("conflicts", {}), groups), info, None, senses, SECTIONS)
    SENSES[0] = senses
    return cands


SENSES = [{}]


def one(cands, x, y):
    """The candidate of a pair (its one sense in these tests)."""
    ks = [k for k, c in cands.items() if ls.pair_of(k) == ls.pair_key(x, y) and c.status != "merged"]
    assert len(ks) == 1, ks
    return cands[ks[0]]


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
    c = one(cands, "unprecedented", "historic")
    assert ls.BAR.fails(c) == [] and ls.extra_rules(c) == []
    assert ls.advocate(c, never=[], struck=[]) == L.CLEAR
    fresh, withdrawn, used = ls.decide(cands, router=Router("same"), now=T0 + dt.timedelta(days=4), never=[], struck=[])
    assert [x.key for x in fresh] == [c.key] and c.status == "learned" and used
    path = tmp_path / "synonyms_learned.yaml"
    ls.write(path, cands, dt.date(2026, 10, 5), SENSES[0])
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    (g,) = doc["groups"]
    assert g["words"] == "historic unprecedented" and g["section"] == "elections"
    assert {"turnout", "elect"} <= set(g["context"]) and "minister" not in path.read_text()   # no sentences


def test_evidence_against_is_remembered_and_blocks():
    by_canon, groups, info = corpus()
    by_canon[9] = [{"id": 99, "article_id": 99, "story_id": 3, "time": None,
                    "text": "The turnout was historic and unprecedented for the state"}]
    cands, senses = {}, {}
    ls.record(cands, ls.scan(by_canon, {}, groups), info, None, senses, SECTIONS)
    c = one(cands, "unprecedented", "historic")
    assert c.facets["against"] is True and ls.advocate(c, never=[], struck=[]).state == "block"
    cands2 = {c.key: c}
    ls.record(cands2, ls.scan(corpus()[0], {}, groups), info, None, senses, SECTIONS)   # a later clean run does not forget
    assert c.facets["against"] is True


def test_qualifiers_loaded_words_and_framing_splits():
    cands = learned({"a": "alleged", "b": "suspected"})
    v = ls.advocate(one(cands, "alleged", "suspected"), never=[], struck=[])
    assert v.state == "block" and "limits a claim" in v.reason
    cands = learned({"a": "protesters", "b": "rioters"})
    c = one(cands, "protesters", "rioters")
    assert ls.advocate(c, loaded={"rioters"}, never=[], struck=[]).state == "block"
    cands = learned({"a": "scandal", "b": "controversy", "both_source": False})
    v = ls.advocate(one(cands, "scandal", "controversy"), never=[], struck=[])
    assert v.state == "hold" and "framing split" in v.reason


def test_the_models_changes_blocks_no_quota_holds():
    cands = learned({"a": "scandal", "b": "controversy"})
    c = one(cands, "scandal", "controversy")
    ls.decide(cands, router=Router("changes"), now=T0 + dt.timedelta(days=4), never=[], struck=[])
    assert c.status == "blocked" and "changes" in c.reason
    cands = learned()
    ls.decide(cands, router=None, now=T0 + dt.timedelta(days=4), never=[], struck=[])
    c = one(cands, "unprecedented", "historic")
    assert c.status == "candidate" and c.reason == ls.WAITING


def test_too_little_evidence_waits():
    cands = learned({"frames": FRAMES[:2]})                                       # 2 statements
    c = one(cands, "unprecedented", "historic")
    assert ls.extra_rules(c) == ["statements"]
    ls.decide(cands, router=Router("same"), now=T0, never=[], struck=[])
    assert c.status == "candidate"


def test_a_learned_pair_the_advocate_later_blocks_is_withdrawn(tmp_path):
    cands = learned()
    c = one(cands, "unprecedented", "historic")
    path = tmp_path / "synonyms_learned.yaml"
    c.status = "learned"
    path.write_text('rejected: []\ngroups:\n  - {words: "killed murdered"}\n', encoding="utf-8")   # the owner's line
    ls.write(path, cands, dt.date(2026, 10, 5), SENSES[0])
    assert "historic" in path.read_text(encoding="utf-8")
    _, withdrawn, _ = ls.decide(cands, loaded={"historic"}, router=None, never=[], struck=[])
    assert withdrawn == [c] and c.status == "blocked"
    ls.write(path, cands, dt.date(2026, 10, 6), SENSES[0])
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["groups"] == [{"words": "killed murdered"}]


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_memory_adds_up_across_runs(store):
    by_canon, groups, info = corpus()
    first = {k: v for k, v in list(by_canon.items())[:1]}
    cands, senses = L.load(store, ls.KIND), L.load(store, ls.SENSE_KIND)
    ls.record(cands, ls.scan(first, {}, groups), info, None, senses, SECTIONS)
    L.save(store, cands, T0)
    L.save(store, senses, T0)
    cands, senses = L.load(store, ls.KIND), L.load(store, ls.SENSE_KIND)        # the next run
    ls.record(cands, ls.scan(by_canon, {}, groups), info, None, senses, SECTIONS)
    c = one(cands, "unprecedented", "historic")
    assert len(c.facets["statements"]) == 3 and len(c.sources) == 5           # article 1 was not counted twice


# the owner's point: "charge" is an allegation in a court story and a fee in a shop
COURT = [("The court framed the murder {w} against the accused on Monday", 7),
         ("Police filed the murder {w} against the accused in court", 7),
         ("The accused denied the murder {w} before the court", 8)]
FEES = [("The bank raised the processing {w} on every home loan", 9),
        ("Customers paid a processing {w} for each home loan", 9),
        ("The lender waived the processing {w} on the home loan", 10)]


def test_a_pair_is_learned_per_context_and_contexts_do_not_add_up():
    cands, senses, info, groups = {}, {}, {}, {}
    sections = {7: "courts", 8: "courts", 9: "markets", 10: "markets"}
    art = 0
    by_canon = {}
    for cid, (frame, story) in enumerate(COURT + FEES, start=1):
        cl = []
        for w in ("charge", "allegation"):
            art += 1
            info[art] = {"source": f"owner:o{art}", "story": story, "when": T0 + dt.timedelta(days=cid % 3)}
            groups[art] = f"g{art}"
            cl.append({"id": art, "article_id": art, "story_id": story, "text": frame.format(w=w), "time": None})
        by_canon[cid] = cl
    ls.record(cands, ls.scan(by_canon, {}, groups), info, None, senses, sections)
    live = {k: c for k, c in cands.items() if c.status != "merged"}
    assert len(live) == 2                                                       # one candidate per context
    by_section = {c.facets["section"]: c for c in live.values()}
    assert set(by_section) == {"courts", "markets"}
    assert all(len(c.facets["statements"]) == 3 for c in live.values())        # 3 each, not 6 in one


def test_relate_uses_a_learned_pair_only_where_its_context_fits(monkeypatch):
    from nishpaksh import relate
    a = "The court framed the murder charge against the accused on Monday"
    b = "The court framed the murder allegation against the accused on Monday"
    before = relate.relate(a, b)
    stems = tuple(relate._stem(w) for w in ("allegation", "charge"))
    senses = [{"stems": stems, "section": "courts", "context": {"court", "murder", "accus", "frame"}}]
    monkeypatch.setattr(relate, "LEARNED_SENSES", senses)
    assert relate.relate(a, b) == "same" and before != "same"
    fa = "The bank raised the processing charge on every home loan"           # a fee: the court sense does not fit
    fb = "The bank raised the processing allegation on every home loan"
    assert relate.relate(fa, fb) != "same"

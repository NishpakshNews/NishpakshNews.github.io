"""A story that develops a published one is judged like any story, only on what is new (owner, Oct 27 2026):
editions.judge_follow_up says what the parent already told, followup.py leaves it out and chooses the parent lines the
article needs, compose.publish_story waits only while nothing is new."""
import datetime as dt

import numpy as np
import pytest

from nishpaksh import editions, embed, followup
from nishpaksh.db import Store, insert, published, select, stories
from nishpaksh.router import Router

from .fixtures import NOW, FakeBackend


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 'f.db'}")
    s.init()
    return s


def _router(store, backend=None):
    from nishpaksh.config import load_yaml
    r = Router(load_yaml("models.yaml")["tiers"], backend or FakeBackend(), store)
    r.resolve()
    return r


def _item(n, text, **kw):
    return dict({"id": n, "text": text, "kind": "event", "minor": False, "role": "core", "verdict": "corroborated",
                 "n_sources": 3, "n_articles": 3, "sources": [], "conflicts_with": [], "responds_to": [], "responded_by": []}, **kw)


PARENT = ["A bridge collapsed in Kesarganj", "Four people died", "Police arrested the site engineer"]


def _publish_parent(store, sid=1, texts=PARENT):
    items = [_item(100 + n, t) for n, t in enumerate(texts)]
    page = {"timeline": [items], "undated": [], "established": [], "contested": [], "context": [],
            "headline": "Bridge collapses", "written_at": (NOW - dt.timedelta(days=1)).isoformat()}
    store.exec(insert(published).values(story_id=sid, version=1, updated_at=NOW - dt.timedelta(days=1),
                                        headline_en="Bridge collapses", headline_hi="h", payload_en=page, payload_hi={}))
    return items


def _candidate(store, sid):
    store.exec(insert(stories).values(id=sid, created_at=NOW, updated_at=NOW, dirty=False, qualifies=True, analysis={}))


def _payload(texts, base=1, **kw):
    items = [_item(base + n, t, **kw) for n, t in enumerate(texts)]
    return {"timeline": [], "undated": [], "established": [], "contested": items, "context": []}


# ---------------------------------------------------------------------------- the judge

def test_what_the_parent_told_is_told_and_the_rest_is_new(store):
    _publish_parent(store)
    _candidate(store, 10)
    p = _payload(PARENT[:2] + ["Rescue work ended", "A court granted bail to the site engineer"])
    fu = editions.judge_follow_up(store, _router(store), 10, p, [1], NOW)
    assert fu.state == "judged" and fu.ok and fu.parent_id == 1
    assert fu.told == [1, 2] and fu.new == [3, 4]
    assert fu.judged[1]["same_as"] == 100 and fu.judged[4]["major"] == "court"
    rec = store.one(select(stories.c.analysis).where(stories.c.id == 10))["analysis"]["edition"]["followup"]
    assert rec["v"] == editions.RECORD_VERSION and rec["new"] == 2 and rec["told"] == 2 and rec["ok"] is True
    assert rec["major"] == ["court"] and "need_new" not in rec and "outlets" not in rec


def test_one_new_statement_is_enough_no_outlet_count_and_no_major_kind(store):
    """The gate (4 new statements or half the parent's, carried by 3 outlets, or a major development) is gone."""
    _publish_parent(store)
    _candidate(store, 11)
    fu = editions.judge_follow_up(store, _router(store), 11, _payload(PARENT[:2] + ["Traffic was diverted"]), [1], NOW)
    assert fu.ok and fu.new == [3]


def test_nothing_new_waits_and_the_desk_is_told_when(store):
    _publish_parent(store)
    _candidate(store, 12)
    fu = editions.judge_follow_up(store, _router(store), 12, _payload(PARENT), [1], NOW)
    assert fu.state == "judged" and not fu.ok and fu.new == [] and fu.told == [1, 2, 3]
    rec = store.one(select(stories.c.analysis).where(stories.c.id == 12))["analysis"]["edition"]["followup"]
    assert rec["ok"] is False and rec["at"]            # desk.ready skips it until a new outlet joins


def test_new_statements_only_single_articles_carry_are_judged_and_two_are_enough(store):
    """Owner, Oct 28 2026: a development that one-article statements alone carry was never judged ('0 new of 0')."""
    _publish_parent(store)
    _candidate(store, 14)
    p = _payload(PARENT[:2] + ["Traffic was diverted", "Rescue work ended"], minor=True)
    fu = editions.judge_follow_up(store, _router(store), 14, p, [1], NOW)
    assert fu.state == "judged" and fu.new == [3, 4] and fu.ok
    assert fu.told == [1, 2]            # a one-article repeat of the parent is left out like any other


def test_one_single_article_statement_alone_is_not_enough(store):
    _publish_parent(store)
    _candidate(store, 15)
    p = _payload(PARENT[:2], minor=True)
    p["contested"].append(_item(3, "Traffic was diverted", minor=True))
    fu = editions.judge_follow_up(store, _router(store), 15, p, [1], NOW)
    assert fu.new == [3] and not fu.ok


def test_the_judgement_is_kept_per_statement_set(store):
    _publish_parent(store)
    _candidate(store, 13)
    p = _payload(PARENT[:1] + ["Traffic was diverted"])
    editions.judge_follow_up(store, _router(store), 13, p, [1], NOW)
    calls = []

    class Counting(FakeBackend):
        def generate(self, model, prompt, json_mode, grounded):
            calls.append(1)
            return super().generate(model, prompt, json_mode, grounded)
    fu = editions.judge_follow_up(store, _router(store, Counting()), 13, p, [1], NOW)
    assert calls == [] and fu.ok and fu.told == [1] and fu.new == [2]
    p2 = _payload(PARENT[:1] + ["Traffic was diverted", "An inquiry panel was formed"])    # a statement more: asked again
    editions.judge_follow_up(store, _router(store, Counting()), 13, p2, [1], NOW)
    assert calls == [1]


def test_a_record_of_the_old_form_is_asked_again(store):
    """Before Oct 27 2026 an unanswered statement was stored as 'not new'; that record must not be trusted."""
    _publish_parent(store)
    _candidate(store, 14)
    p = _payload(["Traffic was diverted"])
    editions.judge_follow_up(store, _router(store), 14, p, [1], NOW)
    row = store.one(select(stories.c.analysis).where(stories.c.id == 14))["analysis"]
    row["edition"]["followup"].pop("v")
    store.exec(stories.update().where(stories.c.id == 14).values(analysis=row))
    calls = []

    class Counting(FakeBackend):
        def generate(self, model, prompt, json_mode, grounded):
            calls.append(1)
            return super().generate(model, prompt, json_mode, grounded)
    editions.judge_follow_up(store, _router(store, Counting()), 14, p, [1], NOW)
    assert calls == [1]


def test_a_statement_the_model_did_not_answer_is_neither_new_nor_told(store):
    _publish_parent(store)
    _candidate(store, 15)

    class First(FakeBackend):                       # answers only statement 1
        def generate(self, model, prompt, json_mode, grounded):
            text, *rest = super().generate(model, prompt, json_mode, grounded)
            if "LATER STATEMENTS" in prompt:
                import json
                d = json.loads(text)
                d["items"] = d["items"][:1]
                return (json.dumps(d), *rest)
            return (text, *rest)
    p = _payload(["Traffic was diverted", PARENT[0], "Rescue work ended"])
    fu = editions.judge_follow_up(store, _router(store, First()), 15, p, [1], NOW)
    assert fu.new == [1] and fu.told == [] and fu.judged[2]["new"] is None and fu.judged[3]["new"] is None
    rec = store.one(select(stories.c.analysis).where(stories.c.id == 15))["analysis"]["edition"]["followup"]
    assert rec["unjudged"] == 2


def test_not_new_without_a_parent_line_to_point_to_is_not_told(store):
    """Nothing is left out on the model's word alone: it must name the parent's statement that says it."""
    _publish_parent(store)
    _candidate(store, 16)

    class NoPointer(FakeBackend):
        def generate(self, model, prompt, json_mode, grounded):
            text, *rest = super().generate(model, prompt, json_mode, grounded)
            if "LATER STATEMENTS" in prompt:
                import json
                d = json.loads(text)
                for it in d["items"]:
                    it["same_as"] = ""
                return (json.dumps(d), *rest)
            return (text, *rest)
    fu = editions.judge_follow_up(store, _router(store, NoPointer()), 16, _payload(PARENT[:1] + ["Traffic was diverted"]), [1], NOW)
    assert fu.told == [] and fu.new == [2]


def test_a_statement_that_replaces_a_parent_line_is_never_told(store):
    _publish_parent(store)
    _candidate(store, 17)

    class Replaces(FakeBackend):
        def generate(self, model, prompt, json_mode, grounded):
            text, *rest = super().generate(model, prompt, json_mode, grounded)
            if "LATER STATEMENTS" in prompt:
                import json
                d = json.loads(text)
                d["items"] = [{"n": 1, "new": False, "same_as": "E1", "updates": "E2", "major": "none"}]
                return (json.dumps(d), *rest)
            return (text, *rest)
    fu = editions.judge_follow_up(store, _router(store, Replaces()), 17, _payload(["Twelve people died"]), [1], NOW)
    assert fu.told == [] and fu.new == []


def test_no_parent_page_means_a_story_of_its_own(store):
    _candidate(store, 18)
    fu = editions.judge_follow_up(store, _router(store), 18, _payload(["Traffic was diverted"]), [999], NOW)
    assert fu.state == "own"


def test_no_router_and_no_record_is_unjudged_not_refused(store):
    _publish_parent(store)
    _candidate(store, 19)
    fu = editions.judge_follow_up(store, None, 19, _payload(["Traffic was diverted"]), [1], NOW)
    assert fu.state == "unjudged"


# ---------------------------------------------------------------------------- leaving out what was told

def test_told_lines_are_left_out_of_every_list_and_lines_others_lean_on_stay():
    a, b, c, d = _item(1, "Told one"), _item(2, "Told two"), _item(3, "New"), _item(4, "Told but disputed", verdict="disputed")
    e = _item(5, "Told, and answered by another", responded_by=[6])
    f = _item(6, "The answer", responds_to=[5])
    p = {"timeline": [[a, c], [b]], "undated": [], "established": [], "contested": [d, e, f], "context": []}
    gone = followup.drop_told(p, {1, 2, 4, 5})
    assert gone == [1, 2]
    assert [[i["id"] for i in t] for t in p["timeline"]] == [[3], []]
    assert [i["id"] for i in p["contested"]] == [4, 5, 6]


def test_dropping_nothing_leaves_the_payload_alone():
    p = _payload(["a"])
    before = {k: list(v) for k, v in p.items()}
    assert followup.drop_told(p, set()) == [] and p == before


# ---------------------------------------------------------------------------- choosing the parent lines

WORDS = ["bridge", "engineer", "bail", "contractor", "rescue", "weather", "inquiry", "minister"]


def _bag(texts):
    out = []
    for t in texts:
        low = t.lower()
        v = [float(low.count(w)) for w in WORDS] + [0.05]
        out.append(v)
    return np.array(out)


@pytest.fixture
def bag():
    embed.set_backend(_bag)
    yield
    embed.set_backend(None)


def _lines(*texts, parent=1):
    return [dict(_item(100 + n, t), id=-(100 + n), kind="background", parent=parent) for n, t in enumerate(texts)]


def _ids(chosen):
    return [-c["id"] for c in chosen]


def test_a_line_the_later_reports_restate_is_offered(bag):
    cands = _lines("The weather was clear", "Rescue was slow")
    kept = [_item(1, "The minister visited")]
    chosen, why = followup.choose_background(cands, kept, restated={101}, excluded=set())
    assert _ids(chosen) == [101] and why[0]["restated"] is True


def test_a_name_the_new_part_leaves_unexplained_brings_its_line(bag):
    cands = _lines("Kesarganj is a town in the district", "The weather was clear", "Rescue was slow")
    kept = [_item(1, "The bail hearing of the Kesarganj engineer was held")]
    chosen, why = followup.choose_background(cands, kept, restated=set(), excluded=set())
    assert 100 in _ids(chosen) and 101 not in _ids(chosen)
    assert why[0]["names"] == ["kesarganj"]


def test_a_line_close_in_meaning_is_offered(bag):
    cands = _lines("The bridge engineer was arrested", "The minister was elected")
    kept = [_item(1, "The bridge engineer got bail")]
    chosen, _ = followup.choose_background(cands, kept, restated=set(), excluded=set())
    assert _ids(chosen) == [100]


def test_two_lines_that_say_the_same_are_offered_once(bag):
    cands = _lines("The bridge engineer was arrested", "The bridge engineer was held")
    kept = [_item(1, "The bridge engineer got bail")]
    chosen, _ = followup.choose_background(cands, kept, restated=set(), excluded=set())
    assert len(chosen) == 1


def test_a_copy_of_a_new_statement_is_never_offered(bag):
    cands = _lines("The bridge engineer got bail")
    kept = [_item(1, "The bridge engineer got bail")]
    assert followup.choose_background(cands, kept, restated={100}, excluded=set())[0] == []


def test_a_line_something_new_replaces_is_never_offered(bag):
    cands = _lines("The bridge contractor counted four dead", "The bridge engineer was arrested")
    kept = [_item(1, "Twelve people died near the bridge")]
    assert _ids(followup.choose_background(cands, kept, restated={100, 101}, excluded=set())[0]) == [100, 101]
    chosen, _ = followup.choose_background(cands, kept, restated={100, 101}, excluded={100})
    assert _ids(chosen) == [101]


def test_at_most_the_budget_in_the_parents_order(bag):
    names = ["Alwar", "Bhopal", "Cuttack", "Dehradun", "Erode", "Faridabad", "Guntur", "Hubli"]
    cands = _lines(*[f"Bridge line about {n}" for n in names])
    kept = [_item(1, "A bridge inquiry covered " + " ".join(names))]
    chosen, why = followup.choose_background(cands, kept, restated=set(), excluded=set(), budget=3)
    assert len(chosen) == 3 and _ids(chosen) == sorted(_ids(chosen)) and len(why) == 3


def test_nothing_to_offer_or_nothing_to_serve_is_no_lines(bag):
    assert followup.choose_background([], [_item(1, "x")], set(), set()) == ([], [])
    assert followup.choose_background(_lines("a line"), [], set(), set()) == ([], [])


def test_a_line_that_helps_nothing_is_not_offered(bag):
    cands = _lines("The weather was clear")
    kept = [_item(1, "The bridge engineer got bail")]
    assert followup.choose_background(cands, kept, restated=set(), excluded=set())[0] == []


def test_if_the_embedding_fails_names_and_restatements_still_decide():
    def broken(texts):
        raise RuntimeError("no model")
    embed.set_backend(broken)
    try:
        cands = _lines("Kesarganj is a town", "The weather was clear", "Rescue was slow")
        kept = [_item(1, "The Kesarganj engineer got bail")]
        chosen, _ = followup.choose_background(cands, kept, restated={102}, excluded=set())
        assert _ids(chosen) == [100, 102]
    finally:
        embed.set_backend(None)


def test_candidates_are_the_established_lines_of_each_parent_in_its_own_order():
    a = _item(1, "First"), _item(2, "Second", kind="relation"), _item(3, "Third")
    parents = {7: {"payload_en": {"timeline": [[a[0]], [a[2]]], "established": [_item(1, "First"), _item(4, "Fourth")]}},
               8: {"payload_en": {"contested": [_item(9, "Weak", n_articles=1), _item(10, "Stronger", n_articles=4)]}}}
    got = followup.candidates(parents, [7, 8])
    assert [(c["id"], c["parent"], c["kind"]) for c in got] == [(-1, 7, "background"), (-3, 7, "background"),
                                                                (-4, 7, "background"), (-10, 8, "background"),
                                                                (-9, 8, "background")]


# ---------------------------------------------------------------------------- the whole step

def test_apply_makes_the_payload_of_a_follow_up(store, bag):
    parent_items = _publish_parent(store, texts=["A bridge collapsed in Kesarganj", "Four people died at the bridge",
                                                 "Police arrested the bridge engineer", "The weather was clear"])
    _candidate(store, 20)
    p = _payload(["A bridge collapsed in Kesarganj", "A court granted bail to the bridge engineer"])
    p["parents"] = [{"story_id": 1, "headline": "Bridge collapses"}]
    p["background"] = [dict(parent_items[0], id=-100, kind="background", parent=1)]       # build_payload's default lines
    fu = editions.judge_follow_up(store, _router(store), 20, p, [1], NOW)
    note = followup.apply(p, fu)
    assert note["dropped"] == [1] and note["new"] == 1 and note["told"] == 1
    assert [i["id"] for i in p["contested"]] == [2]                          # only what is new is written
    assert [-b["id"] for b in p["background"]][:1] == [100]                   # the restated opening line is the context
    assert all(b["kind"] == "background" and b["parent"] == 1 for b in p["background"])
    assert 103 not in [-b["id"] for b in p["background"]]                     # nothing to do with the new part
    assert [b["id"] for b in note["background"]][:1] == [100] and note["background"][0]["restated"] is True


# ---------------------------------------------------------------------------- publish_story

def _publish_with(store, monkeypatch, payload, backend=None):
    """publish_story on a payload we hand it; the writer is replaced by a recorder that writes nothing."""
    from nishpaksh import belong, compose, narrative
    seen = {}
    monkeypatch.setattr(compose, "build_payload", lambda *a, **k: payload)
    monkeypatch.setattr(belong, "check", lambda *a, **k: None)
    monkeypatch.setattr(belong, "assign_topics", lambda *a, **k: None)

    def recorder(router, pl, banned, **kw):
        seen["payload"] = pl
        return {"paragraphs": [], "model": None, "failure": "test"}
    monkeypatch.setattr(narrative, "write_narrative", recorder)
    ok = compose.publish_story(store, _router(store, backend), 30)
    return ok, compose.LAST_OUTCOME.get("outcome"), seen.get("payload")


def _story(store, sid=30):
    store.exec(insert(stories).values(id=sid, created_at=NOW, updated_at=NOW, dirty=True, qualifies=True,
                                      analysis={"priority": {"score": 4}}))


def test_a_story_with_nothing_new_waits_and_is_not_a_try(store, monkeypatch):
    _publish_parent(store)
    _story(store)
    p = dict(_payload(PARENT), parents=[{"story_id": 1, "headline": "Bridge collapses"}], background=[], sources=[],
             loaded_words=[], news=[1], counts={}, perspectives={}, framing=[])
    ok, outcome, seen = _publish_with(store, monkeypatch, p)
    assert (ok, outcome, seen) == (False, "nothing new yet", None)


def test_a_story_with_something_new_is_written_from_the_new_part_with_its_lead_from_it(store, monkeypatch):
    _publish_parent(store)
    _story(store)
    p = dict(_payload(PARENT[:2] + ["A court granted bail to the site engineer"]),
             parents=[{"story_id": 1, "headline": "Bridge collapses"}], background=[], sources=[], loaded_words=[],
             news=[1], counts={}, perspectives={}, framing=[])
    ok, outcome, seen = _publish_with(store, monkeypatch, p)
    assert outcome == "written short" and seen is not None               # it reached the writer
    assert [i["id"] for i in seen["contested"]] == [3]                   # the parent's lines were left out
    assert seen["news"] == [3] and seen["lead"][0] == 3                  # the lead is the new development, not a repeat
    assert seen["background"]                                            # and the parent line it needs is offered


def test_a_check_that_could_not_be_asked_waits(store, monkeypatch):
    _publish_parent(store)
    _story(store)
    p = dict(_payload(["Traffic was diverted"]), parents=[{"story_id": 1, "headline": "Bridge collapses"}], background=[],
             sources=[], loaded_words=[], news=[1], counts={}, perspectives={}, framing=[])
    from nishpaksh import belong, compose
    monkeypatch.setattr(compose, "build_payload", lambda *a, **k: p)
    monkeypatch.setattr(belong, "check", lambda *a, **k: None)
    monkeypatch.setattr(editions, "_classify", lambda *a, **k: None)
    assert compose.publish_story(store, _router(store), 30) is False
    assert compose.LAST_OUTCOME["outcome"] == "follow-up not judged yet"


def test_a_story_without_parents_is_untouched(store, monkeypatch):
    _story(store)
    p = dict(_payload(["Traffic was diverted", "Rescue work ended"]), parents=[], background=[], sources=[], loaded_words=[],
             news=[1], counts={}, perspectives={}, framing=[])
    ok, outcome, seen = _publish_with(store, monkeypatch, p)
    assert outcome == "written short" and [i["id"] for i in seen["contested"]] == [1, 2]
    rec = store.one(select(stories.c.analysis).where(stories.c.id == 30))["analysis"]
    assert "followup" not in (rec.get("edition") or {})


def test_a_parent_that_cannot_be_fetched_waits_instead_of_stopping_the_desk(store, monkeypatch):
    from nishpaksh import pagearchive
    _publish_parent(store)
    _story(store)
    p = dict(_payload(["Traffic was diverted"]), parents=[{"story_id": 1, "headline": "Bridge collapses"}], background=[],
             sources=[], loaded_words=[], news=[1], counts={}, perspectives={}, framing=[])

    def down(*a, **k):
        raise pagearchive.Unreachable("1")
    monkeypatch.setattr(editions, "parent_pages", down)
    ok, outcome, seen = _publish_with(store, monkeypatch, p)
    assert (ok, outcome, seen) == (False, "parent unreachable", None)


# ---------------------------------------------------------------------------- the desk's queue

def _ready_story(store, sid, followup=None, fetched=NOW - dt.timedelta(hours=1)):
    from nishpaksh.db import articles
    ed = {"met_at": (NOW - dt.timedelta(hours=3)).isoformat()}
    if followup is not None:
        ed["followup"] = followup
    store.exec(insert(stories).values(id=sid, created_at=NOW, updated_at=NOW, dirty=False, qualifies=True,
                                      analysis={"edition": ed}))
    for n in range(3):
        store.exec(insert(articles).values(url=f"https://o{sid}{n}.in/a", outlet=f"Outlet {sid} {n}", lang="en", role="news",
                                           title="t", published_at=fetched, fetched_at=fetched, text=None, text_source="full",
                                           minhash=[1], story_id=sid, extract_failures=0))


def test_the_desk_skips_a_story_with_nothing_new_until_a_new_outlet_joins(store):
    from nishpaksh import desk
    at = NOW.isoformat(timespec="minutes")
    _ready_story(store, 1)                                                                          # an ordinary story
    _ready_story(store, 2, {"v": editions.RECORD_VERSION, "ok": False, "at": at})                   # nothing new, no new outlet since
    _ready_story(store, 3, {"v": editions.RECORD_VERSION, "ok": False,
                            "at": (NOW - dt.timedelta(hours=2)).isoformat(timespec="minutes")})      # nothing new, an outlet joined since
    got = desk.ready(store, NOW)
    assert 1 in got and 3 in got and 2 not in got
    assert got.index(3) > got.index(1)                       # the one already turned away once goes after the others


def test_a_refusal_of_the_old_gate_does_not_hold_a_story_back(store):
    """Until Oct 27 2026 'not a follow-up yet' kept a story out until a new outlet joined; that gate is gone, so those
    stories (no record version) are looked at again, and are not queued behind the others."""
    from nishpaksh import desk
    _ready_story(store, 1)
    _ready_story(store, 2, {"ok": False, "at": NOW.isoformat(timespec="minutes"), "new": 1, "need_new": 4})
    got = desk.ready(store, NOW)
    assert sorted(got) == [1, 2]


def test_an_answer_that_covers_no_statement_is_not_kept_as_a_judgement(store):
    """A reply with no usable row for any statement must not be stored as 'nothing new' (the story would then wait for a new
    outlet): it is asked again on the next look."""
    _publish_parent(store)
    _candidate(store, 21)

    class Empty(FakeBackend):
        def generate(self, model, prompt, json_mode, grounded):
            text, *rest = super().generate(model, prompt, json_mode, grounded)
            if "LATER STATEMENTS" in prompt:
                return ('{"items": []}', *rest)
            return (text, *rest)
    p = _payload(["Traffic was diverted", "Rescue work ended"])
    fu = editions.judge_follow_up(store, _router(store, Empty()), 21, p, [1], NOW)
    assert fu.state == "unjudged"
    assert "followup" not in (store.one(select(stories.c.analysis).where(stories.c.id == 21))["analysis"].get("edition") or {})
    assert editions.judge_follow_up(store, _router(store), 21, p, [1], NOW).ok          # a later answer is used

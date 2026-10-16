"""Facts shared along a thread (threads.save_links, verify pooling, editions.attach_updates; owner Oct 16 2026)."""
import datetime as dt

import pytest
from sqlalchemy import insert, select

from nishpaksh import editions, threads
from nishpaksh.db import canonical, published


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'n.db'}")
    s.init()
    return s


def canon(store, sid, text, verdict="unverified", outlets=1, origins=("own:a",), keys=None):
    o = {"origins": list(origins), "n_origins": len(origins), "outlets": outlets}
    if keys is not None:
        o["outlet_keys"] = list(keys)
    return store.insert_returning_id(canonical, dict(story_id=sid, kind="event", text=text, verdict=verdict,
                                                     conflicts=[], origins=o, checkable=True))


def test_same_facts_become_twins_and_updates_mark_the_old_line(store):
    old_toll = canon(store, 1, "Five people died")
    old_shot = canon(store, 1, "Jhota was shot in Mansa")
    new_toll = canon(store, 2, "Twelve people died")
    new_shot = canon(store, 2, "Parvinder Singh Jhota was shot dead in Mansa")
    n = threads.save_links(store, 1, {new_shot: {"same_as": old_shot, "updates": None},
                                      new_toll: {"same_as": None, "updates": old_toll}})
    rel = {r["id"]: r["rel"] or {} for r in store.rows(select(canonical.c.id, canonical.c.rel))}
    assert n == 2 and rel[new_shot]["twins"] == [old_shot] and rel[old_shot]["twins"] == [new_shot]
    assert rel[old_toll]["superseded_by"] == [new_toll] and rel[new_toll]["updates"] == old_toll
    threads.save_links(store, 1, {new_shot: {"same_as": None, "updates": None}, new_toll: {}})   # judged again: gone
    rel = {r["id"]: r["rel"] or {} for r in store.rows(select(canonical.c.id, canonical.c.rel))}
    assert not rel[old_shot].get("twins") and not rel[old_toll].get("superseded_by")


def test_twins_count_their_origins_and_outlets_once():
    own = {"origins": ["own:a", "pool"], "outlets": 1, "outlet_keys": ["owner:a"]}
    twin = {"origins": ["own:b", "gov:punjab"], "outlets": 2, "outlet_keys": ["owner:b", "owner:a"]}
    got = threads.pooled_origins(own, [{"origins": twin}])
    assert got["n_origins"] == 3 and got["outlets"] == 2
    got = threads.pooled_origins({"origins": ["own:a"], "outlets": 1}, [{"origins": {"origins": ["own:b"], "outlets": 4}}])
    assert got["outlets"] == 4                                         # no keys on an older row: the largest count


def test_an_update_is_listed_only_once_the_old_line_is_struck(store):
    old = canon(store, 1, "Five people died", outlets=2)
    keep = canon(store, 1, "The bridge collapsed")
    new = canon(store, 2, "Twelve people died", outlets=1)
    threads.save_links(store, 1, {new: {"same_as": None, "updates": old}})
    nar = {"paragraphs": [[{"text": "Five people died.", "ids": [old], "class": "single"},
                           {"text": "The bridge fell and five died.", "ids": [keep, old], "class": "single"}]]}
    store.exec(insert(published).values(story_id=1, version=1, updated_at=dt.datetime(2026, 10, 16), headline_en="h",
                                        headline_hi="h", payload_en={"narrative": nar}, payload_hi={"narrative": nar}))
    assert not editions.attach_updates(store, None, 1)       # one outlet against two: not struck, so not listed yet
    p = store.one(select(published.c.payload_en).where(published.c.story_id == 1))["payload_en"]
    assert not p.get("updates")
    assert not any(s.get("struck") for s in p["narrative"]["paragraphs"][0])
    store.exec(canonical.update().where(canonical.c.id == new).values(
        origins={"origins": ["own:b"], "n_origins": 1, "outlets": 3}))
    assert editions.attach_updates(store, None, 1)
    p = store.one(select(published.c.payload_en).where(published.c.story_id == 1))["payload_en"]
    u = p["updates"][0]                                         # only struck lines are listed, with what replaced them
    assert u["struck"] is True and u["text"] == "Twelve people died" and u["was"] == "Five people died"
    first, second = p["narrative"]["paragraphs"][0]
    assert first.get("struck") is True and not second.get("struck")             # a sentence with another fact stays

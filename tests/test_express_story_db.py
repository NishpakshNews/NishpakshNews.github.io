"""Express lane, part 3, through the database: which stories are express, the reading cap, one-source reading,
and the express qualification (named origin). The logic alone is in test_express_story.py."""
import datetime as dt

import pytest

from nishpaksh import express
from nishpaksh.db import Store, articles, claims, feeds, select, stories

from .fixtures import NOW

HT_BUSINESS = "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml"


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 't.db'}")
    s.init()
    express.reload()
    express.STATS.clear()
    return s


def _feed(store):
    return store.insert_returning_id(feeds, dict(name="Hindustan Times", url=HT_BUSINESS, lang="en", role="news",
                                                 fail_count=0, disabled=False))


def _story(store, feed, title="Tata Motors opens plant in Sanand", verdict="yes", read=False, minutes_ago=60,
           outlet="Hindustan Times"):
    sid = store.insert_returning_id(stories, dict(signature=title, dirty=True, qualifies=False, analysis={}))
    ex = {"express": {"v": 1, "verdict": verdict, "lane": "companies", "sig": "india", "at": "x"}} if verdict else None
    aid = store.insert_returning_id(articles, dict(
        url=f"https://x/{sid}", feed_id=feed, outlet=outlet, lang="en", role="news", title=title, story_id=sid,
        published_at=NOW - dt.timedelta(minutes=minutes_ago), fetched_at=NOW, text=(title + ". More of the report. ") * 20,
        text_source="full", minhash=[1], extract_failures=0, extraction=ex,
        extracted_at=NOW if read else None))
    return sid, aid


def _claim(store, sid, aid, att, kind="event", stance="asserts"):
    store.insert_returning_id(claims, dict(story_id=sid, article_id=aid, local_id="c", kind=kind, text="Plant opens",
                                           stance=stance, attributed_to=att))


def test_candidates_are_stories_with_a_lane_verdict(store):
    f = _feed(store)
    a, _ = _story(store, f)
    _story(store, f, verdict=None)
    c = express.candidates(store, NOW)
    assert set(c) == {a} and c[a]["lane"] == "companies" and c[a]["groups"] == 1 and c[a]["read"] is False


def test_an_excluded_member_is_not_a_candidate(store):
    f = _feed(store)
    _story(store, f, verdict="excluded")
    assert express.candidates(store, NOW) == {}


def test_reading_cap_takes_the_newest_new_stories_and_always_finishes_begun_ones(store):
    f = _feed(store)
    new = [_story(store, f, title=f"Infosys opens plant {i}", minutes_ago=10 + i)[0] for i in range(5)]
    begun, _ = _story(store, f, title="Wipro opens plant", read=True, minutes_ago=500)
    got = express.focus(store, NOW)
    assert got == {begun, *new[:3]}                        # reads_per_run is 3: the newest three; the begun one besides
    assert express.STATS["story_started"] == 3 and express.STATS["now"]["stories_waiting_to_read"] == 2


def test_one_independent_source_is_enough_to_read_an_express_story_only(store):
    from nishpaksh.extract import select_for_extraction
    f = _feed(store)
    sid, aid = _story(store, f)
    assert select_for_extraction(store, {sid}) == []                       # the strict rule: 3 sources
    picked = select_for_extraction(store, {sid}, express={sid})
    assert [p["id"] for p in picked] == [aid]


def test_a_named_origin_qualifies_and_an_unnamed_one_does_not(store):
    f = _feed(store)
    sid, aid = _story(store, f, read=True)
    _claim(store, sid, aid, "Tata Motors")
    assert express.assess(store, sid) is True
    sid2, aid2 = _story(store, f, title="Infosys opens plant in Mysuru", read=True)
    _claim(store, sid2, aid2, "unnamed sources")
    assert express.assess(store, sid2) is False
    assert express.STATS["story_out"]["anonymous_source"] == 1 and express.STATS["story_qualified"] == 1


def test_an_unread_story_does_not_qualify(store):
    f = _feed(store)
    sid, aid = _story(store, f, read=False)
    _claim(store, sid, aid, "Tata Motors")
    assert express.assess(store, sid) is False
    assert express.STATS["story_out"]["not_read_yet"] == 1


def test_a_second_outlet_not_yet_read_holds_the_story(store):
    f = _feed(store)
    sid, aid = _story(store, f, read=True)
    _claim(store, sid, aid, "Tata Motors")
    store.insert_returning_id(articles, dict(
        # an INDEPENDENT second outlet: Mint is HT Media like Hindustan Times (config/ownership.yaml), one outlet
        url="https://y/1", feed_id=None, outlet="The Hindu", lang="en", role="news", title="Tata Motors plant opens", story_id=sid,
        published_at=NOW, fetched_at=NOW, text="Tata Motors plant. " * 30, text_source="full", minhash=[1],
        extract_failures=0, extracted_at=None))
    assert express.assess(store, sid) is False
    assert express.STATS["story_out"]["second_outlet_unread"] == 1


def test_the_beat_seats_follow_the_strict_order(store):
    from nishpaksh.desk import _beat_order
    def mk(analysis):
        return store.insert_returning_id(stories, dict(signature="s", dirty=False, qualifies=True, analysis=analysis))
    ent = mk({"qualified_by": "express", "express_lane": "entertainment", "express_sig": "india"})
    sport = mk({"beat": {"desk": "sport"}})
    dom = mk({"beat": {"desk": "domains"}})
    tech = mk({"qualified_by": "express", "express_lane": "tech", "express_sig": "world"})
    esport_world = mk({"qualified_by": "express", "express_lane": "sport", "express_sig": "world"})
    esport_india = mk({"qualified_by": "express", "express_lane": "sport", "express_sig": "india"})
    plain = mk({})                                                     # not a beat story: keeps its place
    queue = [ent, sport, plain, dom, tech, esport_world, esport_india]
    beats = set(queue) - {plain}
    got = _beat_order(store, queue, beats)
    assert got[2] == plain
    assert [s for s in got if s != plain] == [tech, dom, sport, esport_india, esport_world, ent]

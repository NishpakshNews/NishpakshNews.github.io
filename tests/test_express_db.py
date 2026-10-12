"""Express lane, part 2, through the database: the gate inside grouping, the verdict kept with the article, the
embedding slice booked in quota_usage. (The logic alone, without a database, is in test_express_gate.py.)"""
import datetime as dt

import pytest

from nishpaksh import express
from nishpaksh.db import Store, articles, feeds, quota_usage, select, update

from .fixtures import NOW, FakeBackend

HT_BUSINESS = "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml"
HT_SPORTS = "https://www.hindustantimes.com/feeds/rss/sports/rssfeed.xml"
HT_INDIA = "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 't.db'}")
    s.init()
    return s


class Counting(FakeBackend):
    def lane_prompts(self):
        return sum(1 for _, p in self.calls if p.startswith("Below are news headlines"))


def _router(store, backend):
    from nishpaksh.config import load_yaml
    from nishpaksh.router import Router
    r = Router(load_yaml("models.yaml")["tiers"], backend, store)
    r.resolve()
    return r


def _feed(store, url, name="Hindustan Times"):
    return store.insert_returning_id(feeds, dict(name=name, url=url, lang="en", role="news", fail_count=0, disabled=False))


def _put(store, feed_id, title, hours_ago=1.0, source="full"):
    return store.insert_returning_id(articles, dict(
        url=f"https://x/{title}", feed_id=feed_id, outlet="Hindustan Times", lang="en", role="news", title=title,
        published_at=NOW - dt.timedelta(hours=hours_ago), fetched_at=NOW, text=(title + ". More text of the report. ") * 20,
        text_source=source, minhash=[1], extract_failures=0))


def _row(store, aid):
    return store.one(select(articles.c.embedding, articles.c.extraction, articles.c.story_id).where(articles.c.id == aid))


def test_only_a_headline_that_passed_its_lane_is_embedded_and_it_is_asked_once(store):
    from nishpaksh.stories import group_stories
    express.reload()
    biz, sports = _feed(store, HT_BUSINESS), _feed(store, HT_SPORTS)
    win = _put(store, sports, "India win by six wickets in Pune")
    tata = _put(store, biz, "Tata Motors opens plant in Sanand")
    rain = _put(store, biz, "Weather office forecasts light showers")
    arrested = _put(store, biz, "Founder arrested over fund diversion")
    short = _put(store, biz, "Infosys opens plant in Mysuru", source="summary")
    backend = Counting()
    group_stories(store, _router(store, backend))
    assert _row(store, win)["embedding"] and _row(store, tata)["embedding"]
    for aid in (rain, arrested, short):
        assert not _row(store, aid)["embedding"], aid
    ex = {aid: _row(store, aid)["extraction"]["express"] for aid in (win, tata, rain, arrested, short)}
    assert ex[win]["verdict"] == "yes" and ex[win]["lane"] == "sport"
    assert ex[tata]["lane"] == "companies"
    assert ex[rain]["why"] == "not_lane"
    assert ex[arrested]["verdict"] == "excluded" and ex[arrested]["why"].startswith("harm:")
    assert ex[short]["why"] == "unreadable"
    used = store.one(select(quota_usage.c.requests).where(quota_usage.c.model == express.EMBED_KEY))
    assert used["requests"] == 2                                  # the slice counted what express used
    asked = backend.lane_prompts()
    assert asked == 2         # one question for the three headlines it could ask, one (reversed) for the two with a lane
    group_stories(store, _router(store, backend))                 # next run: every headline already judged
    assert backend.lane_prompts() == asked


def test_a_feed_without_a_lane_is_never_gated(store):
    from nishpaksh.stories import group_stories
    express.reload()
    plain = _feed(store, HT_INDIA)
    aid = _put(store, plain, "Weather office forecasts light showers")
    backend = Counting()
    group_stories(store, _router(store, backend))
    assert _row(store, aid)["embedding"] and backend.lane_prompts() == 0     # politics intake keeps its rule


def test_nothing_is_embedded_while_the_pacing_curve_has_given_the_slice_out(store):
    """The slice follows the day's pacing curve (like the other quotas): when today's express use is already past what
    the curve has opened, a passed headline is judged (verdict kept) but waits for room, and the model is still asked."""
    from nishpaksh.router import PACIFIC, pace_fraction, quota_day
    from nishpaksh.stories import group_stories
    express.reload()
    opened = int(express.cfg()["embed_daily_cap"] * pace_fraction(dt.datetime.now(PACIFIC)))
    store.quota_add(express.EMBED_KEY, quota_day(), opened + 5, 0)       # more than the curve has opened (and < the cap)
    sports = _feed(store, HT_SPORTS)
    a = _put(store, sports, "India win by six wickets in Pune", hours_ago=1)
    b = _put(store, sports, "India win by two wickets in Delhi", hours_ago=2)
    group_stories(store, _router(store, Counting()))
    assert not _row(store, a)["embedding"] and not _row(store, b)["embedding"]
    assert _row(store, a)["extraction"]["express"]["verdict"] == "yes"       # judged all the same, waits for room
    assert express.STATS["now"]["passed_waiting"] == 2


def test_nothing_is_asked_once_the_whole_days_slice_is_used(store):
    from nishpaksh.router import quota_day
    from nishpaksh.stories import group_stories
    express.reload()
    store.quota_add(express.EMBED_KEY, quota_day(), express.cfg()["embed_daily_cap"], 0)
    sports = _feed(store, HT_SPORTS)
    a = _put(store, sports, "India win by six wickets in Pune")
    backend = Counting()
    group_stories(store, _router(store, backend))
    assert backend.lane_prompts() == 0 and not _row(store, a)["embedding"] and _row(store, a)["extraction"] is None


def test_the_express_verdict_survives_reading(store):
    from nishpaksh import extract
    from .fixtures import ARTICLES
    express.reload()
    title = ARTICLES[0]["title"]
    sports = _feed(store, HT_SPORTS)
    aid = _put(store, sports, title)
    store.exec(update(articles).where(articles.c.id == aid).values(
        extraction={"express": {"v": 1, "verdict": "yes", "lane": "sport"}}))
    a = dict(id=aid, outlet="Hindustan Times", published_at=NOW, title=title, text=ARTICLES[0]["text"], story_id=None,
             extract_failures=0)
    assert extract._extract_one(store, _router(store, FakeBackend()), a) == "done"
    ex = _row(store, aid)["extraction"]
    assert ex["express"]["lane"] == "sport" and "model" in ex

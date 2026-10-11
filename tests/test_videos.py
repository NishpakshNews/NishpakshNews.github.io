"""YouTube search words and relevance (owner, Oct 12 2026: videos often failed to be found; take the numbers
out of the search and work on what is searched). videoquery.py has no database; _due and _run are tested with
a fake store and a fake `get`."""
import datetime as dt

from nishpaksh import videoquery as vq

FRAMES = [
    {"who": "Defence Ministry", "action": "signs", "what": "Rs 661.50 crore deal for BrahMos launchers", "where": "New Delhi"},
    {"who": "Ministry of Defence", "action": "signed", "what": "contract for BrahMos launchers", "where": ""},
    {"who": "Defence Ministry", "action": "signed", "what": "deal with Bharat Dynamics", "where": ""},
    {"who": "Police", "action": "said", "what": "", "where": "Delhi"},
]
HEAD_EN = "Defence Ministry signs Rs 661.50 crore deal for BrahMos launchers"
HEAD_HI = "रक्षा मंत्रालय ने ब्रह्मोस लॉन्चर के लिए 661.50 करोड़ रुपये का सौदा किया"


def test_numbers_money_and_ordinals_are_taken_out():
    out = vq.strip_numbers("Rs 661.50 crore deal, 40 dead, 3rd time, ₹5 lakh, 12 percent")
    assert not any(ch.isdigit() for ch in out)
    assert "crore" not in out and "lakh" not in out and "deal" in out and "dead" in out
    assert not any(ch.isdigit() for ch in vq.strip_numbers("२६ लोग, 5 करोड़ रुपये"))
    assert "T20" in vq.strip_numbers("T20 World Cup 2026")          # a name that contains a figure stays


def test_queries_hold_names_not_figures_and_hindi_is_searched_in_hindi():
    qs = dict((lang, q) for q, lang in vq.queries(FRAMES, HEAD_EN, HEAD_HI))
    assert "BrahMos" in qs["en"] and "Defence Ministry" in qs["en"]
    assert "Ministry of Defence" not in qs["en"]                    # the same words in another order
    assert "Delhi" not in qs["en"] and "Police" not in qs["en"]     # too general to find one story
    assert not any(ch.isdigit() for q in qs.values() for ch in q)
    assert any("\u0900" <= ch <= "\u097f" for ch in qs["hi"]) and "ब्रह्मोस" in qs["hi"]
    assert all(len(q.split()) <= vq.MAX_QUERY_WORDS for q in qs.values())


def test_short_query_is_shorter_and_a_story_without_frames_uses_its_headline():
    long_q = dict((l, q) for q, l in vq.queries(FRAMES, HEAD_EN, HEAD_HI))
    short_q = dict((l, q) for q, l in vq.queries(FRAMES, HEAD_EN, HEAD_HI, short=True))
    assert len(short_q["en"].split()) < len(long_q["en"].split())
    assert len(short_q["hi"].split()) < len(long_q["hi"].split())
    bare = dict((l, q) for q, l in vq.queries([], "Kotdwar gym trainer who defended shopkeeper faces court", ""))
    assert "Kotdwar" in bare["en"] and "hi" not in bare       # no Hindi headline: no Hindi search


def test_relevance_uses_names_and_both_headlines_not_the_headline_alone():
    kw = vq.keywords(FRAMES, "Rs 661.50 crore for launchers: the deal that arms the Navy", HEAD_HI)
    assert vq.relevant("BrahMos launchers: Defence Ministry signs contract", kw)    # names, not in this headline
    assert vq.relevant("रक्षा मंत्रालय ब्रह्मोस सौदा लाइव", kw)                      # a Hindi title
    assert not vq.relevant("Medicare ad compilation 2026", kw)                       # October 10 junk stays out
    assert not vq.relevant("Hindi audiobook chapter 5", kw)
    assert not vq.relevant("Live news today breaking update", kw)                    # no story word in it


def test_one_shared_word_is_not_enough():
    kw = vq.keywords(FRAMES, HEAD_EN, HEAD_HI)
    assert not vq.relevant("BrahMos cricket highlights", kw)


def test_due_retries_an_empty_row_once_and_never_a_filled_one():
    from nishpaksh.videos import _due
    now = dt.datetime(2026, 10, 12, 12, 0)
    pub = now - dt.timedelta(hours=4)
    assert _due(pub, None, now)                                                          # never tried
    assert not _due(pub, {"items": [{"id": "x"}], "fetched_at": pub}, now)               # has videos
    assert not _due(pub, {"items": [], "fetched_at": now - dt.timedelta(hours=1)}, now)  # too soon
    assert _due(pub, {"items": [], "fetched_at": pub + dt.timedelta(hours=1)}, now)      # the one second try
    old_story = now - dt.timedelta(hours=8)
    assert not _due(old_story, {"items": [], "fetched_at": now - dt.timedelta(hours=3)}, now)  # that WAS the second try


class _Store:
    def __init__(self):
        self.units = 0

    def quota_add(self, model, day, requests, tokens):
        self.units += requests


def _response(items):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"items": items}
    return R()


def _video(vid, title, channel="Some Channel"):
    return {"id": {"videoId": vid}, "snippet": {"title": title, "channelTitle": channel, "channelId": channel,
                                                 "publishedAt": "2026-10-12T05:00:00Z", "thumbnails": {}}}


def test_run_keeps_only_relevant_videos_and_counts_each_search():
    from nishpaksh.videos import _run
    seen = []

    def get(url, params, timeout):
        seen.append(params)
        return _response([_video("a", "BrahMos launchers deal signed by Defence Ministry", "The Hindu"),
                          _video("b", "Chinese drama episode 12")])
    store = _Store()
    kw = vq.keywords(FRAMES, HEAD_EN, HEAD_HI)
    lists = _run(store, "KEY", vq.queries(FRAMES, HEAD_EN, HEAD_HI), dt.datetime(2026, 10, 12), kw, get)
    assert [[v["id"] for v in l] for l in lists] == [["a"], ["a"]]
    assert store.units == 200 and [p["relevanceLanguage"] for p in seen] == ["en", "hi"]
    assert not any(ch.isdigit() for p in seen for ch in p["q"])


def test_run_returns_none_when_a_search_fails():
    from nishpaksh.videos import _run

    def get(url, params, timeout):
        raise RuntimeError("quota")
    assert _run(_Store(), "KEY", [("x y", "en")], dt.datetime(2026, 10, 12), set(), get) is None

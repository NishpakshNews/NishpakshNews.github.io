"""The falling bar, the drafting parts and resting writer models (owner, Oct 16 2026)."""
import time
from types import SimpleNamespace as NS

from nishpaksh import narrative as N
from nishpaksh import router as R


def test_the_bar_falls_with_each_try_and_stops_at_the_floor():
    assert [round(N.publish_bar(n), 2) for n in range(4)] == [0.8, 0.75, 0.7, 0.65]
    assert N.publish_bar(50) == N.PUBLISH_FLOOR


def test_a_draft_short_of_one_bar_passes_the_next(monkeypatch):
    monkeypatch.setattr(N, "ordered_items", lambda p: [{"id": i} for i in range(100)])
    nar = {"model": "m", "paragraphs": [[{"text": "x"}]], "covers": list(range(68))}
    assert not N.essay_ok(nar, {}, N.publish_bar(2))          # 68% at the 70% bar
    assert N.essay_ok(nar, {}, N.publish_bar(3))              # passes at 65%, with no new work
    assert N.essay_shortfall(nar, {}, 0.7)["need"] == 70


def test_parts_pack_whole_paragraphs_of_about_ten_statements():
    plan = [NS(ids=list(range(n)), section="happened") for n in (4, 5, 3, 12, 2)]
    parts = N.parts_of(plan)
    assert [sum(len(p.ids) for p in part) for part in parts] == [9, 3, 12, 2]


def test_an_overloaded_writer_model_rests_and_comes_back():
    r = R.Router.__new__(R.Router)
    import threading
    r._lock = threading.Lock()
    slot = R.ModelSlot(id="gemini-x-flash", rpm=10, tpm=10**6, rpd=100)
    lite = R.ModelSlot(id="gemini-y-flash", rpm=10, tpm=10**6, rpd=100)
    r.tiers = {"writer": [slot], "bulk": [lite]}
    r.model_streak, r.dropped, r.rested, r.rest_count, r.bad_keys = {}, set(), set(), {}, set()
    for _ in range(R.OVERLOAD_STREAK):
        r._handle_error(slot, Exception("503 UNAVAILABLE"))
    assert not slot.disabled and "gemini-x-flash" in r.rested
    assert slot.cooldown_until > time.time() + R.REST_STEP - 5
    for _ in range(R.OVERLOAD_STREAK):
        r._handle_error(lite, Exception("503 UNAVAILABLE"))
    assert lite.disabled                                       # other tiers still drop it for the run


def test_a_story_is_never_given_up_and_waits_only_at_the_floor(tmp_path):
    import datetime as dt
    from sqlalchemy import insert, select
    from nishpaksh import compose
    from nishpaksh.db import Store, stories, utcnow
    s = Store(f"sqlite:///{tmp_path / 'n.db'}")
    s.init()
    s.exec(insert(stories).values(id=1, analysis={}))
    for n in range(6):                                   # failed tries: still allowed, the bar falls 80% ... 55%
        assert compose._writer_attempt_allowed(s, 1, "h")
        compose._note_writer_failure(s, 1, "h" if n % 2 else "g", {"model": "m", "covers": []})
    assert compose._writer_tries(s, 1) == 6             # tries add up across statement sets; the bar is now 50%
    assert not compose._writer_attempt_allowed(s, 1, "h")          # at the floor, the same statements rest a while
    assert compose._writer_attempt_allowed(s, 1, "new")             # new statements are tried at once
    a = s.one(select(stories.c.analysis).where(stories.c.id == 1))["analysis"]
    a["writer_failures"]["at"] = (utcnow() - dt.timedelta(hours=4)).isoformat(timespec="minutes")
    s.exec(stories.update().where(stories.c.id == 1).values(analysis=a))
    assert compose._writer_attempt_allowed(s, 1, "h")

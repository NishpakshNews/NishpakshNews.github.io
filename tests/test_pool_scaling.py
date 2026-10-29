"""The pool sets the pace (owner, Oct 29 2026): the fewer stories ready, the fewer the desk writes and the more a light run
reads; at or above the upper limit every banked seat may be used."""
import datetime as dt

import pytest

from nishpaksh.config import SETTINGS


def _utc(hour, day=11):
    return dt.datetime(2026, 10, day, hour, 30)


def test_write_allowance_table():
    from nishpaksh.desk import write_allowance
    normal = SETTINGS.desk_per_hour + SETTINGS.desk_beat_seat
    assert write_allowance(0) == 0
    assert [write_allowance(n) for n in range(1, 12)] == [1, 1, 1, 1, 1, 2, 3, 4, 4, 4, 4]
    assert write_allowance(8) == normal == write_allowance(SETTINGS.desk_write_all_from - 1)   # near the upper limit: the normal hour
    assert write_allowance(SETTINGS.desk_write_all_from) is None and write_allowance(40) is None   # above it: every banked seat
    seq = [write_allowance(n) for n in range(0, SETTINGS.desk_write_all_from)]
    assert seq == sorted(seq)                                   # more ready, never fewer written


def test_the_pool_keeps_its_cushion_after_the_writing():
    from nishpaksh.desk import write_allowance
    for n in range(SETTINGS.light_ready_min + 1, SETTINGS.desk_write_all_from):
        assert n - write_allowance(n) >= SETTINGS.light_ready_min      # a normal hour stays a light run


def test_a_light_run_reads_more_when_the_pool_is_low():
    pytest.importorskip("sqlalchemy")
    from nishpaksh.run import read_allowance
    assert read_allowance(None) == SETTINGS.light_read_allowance
    assert [read_allowance(n) for n in (4, 5, 7, 8, 12, 30)] == [6, 4, 4, 2, 2, 2]
    seq = [read_allowance(n) for n in range(4, 20)]
    assert seq == sorted(seq, reverse=True)                      # the fuller the pool, the less is read


def _desk_with(monkeypatch, n_ready):
    from nishpaksh import compose, desk, verify
    import nishpaksh.consolidate as K
    queue = list(range(1, n_ready + 1))
    monkeypatch.setattr(desk, "ready", lambda store, now=None: queue)
    monkeypatch.setattr(desk, "_beats", lambda store, ids: set())
    monkeypatch.setattr(verify, "base_verdicts", lambda *a, **k: None)
    monkeypatch.setattr(K, "consolidate_story", lambda *a, **k: None)
    monkeypatch.setattr(compose, "publish_story", lambda store, router, sid: compose._outcome(sid, "published"))
    return desk


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 't.db'}")
    s.init()
    return s


@pytest.mark.carry
@pytest.mark.parametrize("n_ready,expected", [(1, 1), (3, 1), (6, 2), (7, 3), (10, 4), (12, 6)])
def test_the_desk_writes_what_the_pool_allows(store, monkeypatch, n_ready, expected):
    desk = _desk_with(monkeypatch, n_ready)
    stats = desk.work(store, router=None, now=_utc(3))           # 4 hours banked: the seats alone would allow 6
    assert stats["seats"]["general"] == 6
    assert len(stats["published"]) == expected and stats["write_allowance"] == desk.write_allowance(n_ready)


# ---------------------------------------------------------------- the ledger records the pool and the rhythm

NOW_L = dt.datetime(2026, 10, 29, 12, 20)


def test_rhythm_counts_hours_gaps_and_the_first_article_of_a_job():
    from nishpaksh import ledger
    ev = [(NOW_L - dt.timedelta(hours=h, minutes=m), n) for h, m, n in ((0, 5, 2), (1, 10, 1), (2, 40, 3), (5, 0, 1), (30, 0, 4))]
    r = ledger.rhythm_from(ev, NOW_L - dt.timedelta(minutes=80), NOW_L)
    assert r["this_hour"] == 2 and sum(r["hours_24h"]) == 5 and len(r["hours_24h"]) == 24     # the 30-hour-old event is outside
    assert r["hours_24h"][-1] == 1 and r["hours_with_article"] == 3 and r["empty_hours"] == 21
    assert r["since_last_min"] == 5 and r["longest_gap_min"] == 140                              # 5 h ago -> 2 h 40 min ago is the widest
    assert r["first_in_job_min"] == 10                                                           # the job began 80 min ago; its first article 70 min ago
    empty = ledger.rhythm_from([], None, NOW_L)
    assert empty["longest_gap_min"] == 1440 and empty["since_last_min"] is None and empty["first_in_job_min"] is None


def test_the_entry_carries_the_pool_and_the_job_adds_its_desk_runs():
    from nishpaksh import ledger
    run = {"id": 7, "started_at": NOW_L, "trigger": "supabase-cron", "stats": {
        "seconds": 1100, "light": {"ready": 6, "min": 4, "on": True, "prime": False, "read": [1, 2, 3, 4]}}}
    first = {"published": [1, 2], "ready": 8, "write_allowance": 4, "seconds": 600}
    second = {"published": [9], "ready": 3, "write_allowance": 1, "seconds": 300}
    desk = ledger.merge_desk_reports([first, second])
    assert desk["runs"] == 2 and desk["seconds"] == 900
    e = ledger.build_entry(run, desk, None, None, None, 5)
    assert e["pool"] == {"mode": "light", "at_desk_start": 8, "after_first_desk": 6, "end": 5, "write_allowance": 4, "read": 4,
                         "desk_runs": 2, "desk_seconds": 900}
    full = ledger.build_entry({**run, "stats": {"light": {"ready": 2, "on": False}, "refill": {"queue": 12}}}, None, None, None, None)
    assert full["pool"]["mode"] == "full" and full["pool"]["read"] == 12
    e["rhythm"] = ledger.rhythm_from([(NOW_L, 2)], NOW_L - dt.timedelta(minutes=30), NOW_L)
    md = ledger.render([e], NOW_L.replace(tzinfo=dt.timezone.utc))
    assert "## The pool and the rhythm" in md and "longest gap" in md

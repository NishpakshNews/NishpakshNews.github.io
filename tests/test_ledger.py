"""The ledger (ledger.py): a per-run record in the repository. The pure functions only: no database, no model."""
import datetime as dt
import json

from nishpaksh import ledger

T0 = dt.datetime(2026, 10, 12, 16, 5, 0)       # a naive datetime is UTC, as the database returns them


def run_row(i=1, started=T0, **stats):
    base = {"ingested": 120, "seconds": 900, "grouped": 80, "queue": 16, "qualifying": 3, "settled": 1,
            "quota_left": {"embed": 1800, "light": 400}, "quota_now": {"embed": 150},
            "tier_calls": {"embed": {"ok": 40}},
            "embedding": {"budget": 150, "embedded": 140, "waiting_before": 300, "waiting_after": 160,
                          "waiting_new": 280, "waiting_old": 20, "held_world": 12, "left_today": 1800,
                          "by_outlet": {"Aaj Tak": 30, "The Hindu": 20}, "yields": {"Aaj Tak": 0.3, "The Hindu": 0.23}},
            "health": {"problems": []}}
    base.update(stats)
    return {"id": i, "started_at": started, "finished_at": started + dt.timedelta(minutes=30), "trigger": "schedule",
            "stats": base}


def entry(i=1, started=T0, **kw):
    return ledger.build_entry(run_row(i, started, **kw), {"published": [11, 12], "seats": {"general": 0, "beat": 1},
                                                           "ready": 4, "tried": 2},
                              {"Aaj Tak": [300, 280, 90], "The Hindu": [120, 120, 28]},
                              {"by_outlet": {"Aaj Tak": 30, "The Hindu": 11}}, 1200)


def test_entry_has_the_numbers_the_owner_asked_for():
    e = entry()
    assert e["at"] == "2026-10-12T16:05:00Z" and e["ist"] == "2026-10-12 21:35"
    assert e["pt_day"] == "2026-10-12"
    assert e["embed"]["used_today"] == 1200 and e["embed"]["left_today"] == 1800
    assert e["embed"]["this_run"]["embedded"] == 140 and e["embed"]["this_run"]["by_outlet"]["Aaj Tak"] == 30
    assert "yields" not in e["embed"]["this_run"] and e["yield_at_start"]["Aaj Tak"] == 0.3
    assert e["outlets"]["Aaj Tak"] == [300, 280, 90]
    assert e["pipeline"]["queue"] == 16 and e["desk"]["published"] == [11, 12]
    assert "express" not in e                     # not recorded until the lane runs
    json.dumps(e)                                 # plain data


def test_express_funnel_is_carried_when_present():
    e = ledger.build_entry(run_row(express={"seen": 40, "embedded": 12, "excluded": {"harm": 9}}), None, None, None, None)
    assert e["express"]["embedded"] == 12 and "desk" not in e


def test_a_run_with_no_embedding_record_still_builds():
    r = run_row()
    del r["stats"]["embedding"]
    e = ledger.build_entry(r, None, None, None, None)
    assert e["embed"]["this_run"] == {} and e["intake"]["by_outlet"] == {}


def test_pacific_quota_day():
    assert ledger.pt_day(dt.datetime(2026, 10, 12, 3, 0)) == "2026-10-11"     # 03:00 UTC is the evening before in Pacific
    assert ledger.pt_day(dt.datetime(2026, 10, 12, 16, 0)) == "2026-10-12"


def test_append_replaces_the_same_run(tmp_path):
    ledger.append(tmp_path, entry(1))
    ledger.append(tmp_path, entry(2, T0 + dt.timedelta(hours=1)))
    ledger.append(tmp_path, entry(2, T0 + dt.timedelta(hours=1), ingested=999))      # the workflow was run again
    lines = (tmp_path / "runs-2026-10.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["intake"]["new"] == 999


def test_entries_go_to_their_month_and_old_months_are_pruned(tmp_path):
    ledger.append(tmp_path, entry(1, dt.datetime(2026, 5, 3, 10, 0)))
    ledger.append(tmp_path, entry(2, dt.datetime(2026, 10, 3, 10, 0)))
    assert sorted(p.name for p in tmp_path.glob("runs-*")) == ["runs-2026-05.jsonl", "runs-2026-10.jsonl"]
    removed = ledger.prune(tmp_path, dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc))
    assert removed == ["runs-2026-05.jsonl"]                                          # May ended > 120 days before
    assert (tmp_path / "runs-2026-10.jsonl").exists()


def test_read_entries_window_and_order(tmp_path):
    now = dt.datetime(2026, 10, 12, 18, 0, tzinfo=dt.timezone.utc)
    ledger.append(tmp_path, entry(1, T0 - dt.timedelta(days=20)))
    ledger.append(tmp_path, entry(3, T0))
    ledger.append(tmp_path, entry(2, T0 - dt.timedelta(days=2)))
    got = ledger.read_entries(tmp_path, days=8, now=now)
    assert [e["run"] for e in got] == [2, 3]


def test_render_has_every_section_and_the_figures():
    es = [entry(i, T0 + dt.timedelta(hours=i)) for i in range(1, 4)]
    md = ledger.render(es, dt.datetime(2026, 10, 12, 20, 0, tzinfo=dt.timezone.utc))
    for heading in ("# Nishpaksh ledger", "## Embedding quota, by quota day", "## Last 24 runs", "## Outlets", "## Express lane"):
        assert heading in md
    assert "| 2026-10-12 | 3 | 420 |" in md              # 3 runs x 140 embedded
    assert "| Aaj Tak |" in md and "32%" in md      # 90 of 280 embedded are in 3+ outlet stories
    assert "Nothing recorded yet" in md                  # no express funnel yet


def test_render_express_funnel_and_problems():
    es = [entry(1), entry(2, T0 + dt.timedelta(hours=1), express={"seen": 40, "embedded": 12, "excluded": {"harm": 9, "gossip": 2}})]
    es[1]["problems"] = ["daily quota used up for: embed"]
    md = ledger.render(es, dt.datetime(2026, 10, 12, 20, 0, tzinfo=dt.timezone.utc))
    assert "| seen | 40 |" in md and "| harm | 9 |" in md
    assert "daily quota used up for: embed" in md


def test_render_with_nothing_does_not_fail():
    assert "No runs recorded yet" in ledger.render([])


def test_write_all_makes_the_three_files(tmp_path):
    ledger.write_all(tmp_path, entry(1), dt.datetime(2026, 10, 12, 20, 0, tzinfo=dt.timezone.utc))
    assert {p.name for p in tmp_path.iterdir()} == {"README.md", "LEDGER.md", "runs-2026-10.jsonl"}
    assert "schema version" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_embedding_use_per_key():
    e = ledger.build_entry(run_row(), None, None, None, {"total": 2100, "by_key": {"k1": 800, "k2": 700, "k3": 600}})
    assert e["embed"]["used_today"] == 2100 and e["embed"]["used_by_key"]["k2"] == 700

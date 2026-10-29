"""The hourly job's order (owner, Oct 29 2026): the desk writes first, a full run is a refill sized by what the pool lacks,
a light run reads a few express stories, an almost empty pool is primed, and the ledger adds the job's two desk reports."""
import datetime as dt
import pathlib

import pytest
import yaml

from nishpaksh import express, ledger
from nishpaksh.config import SETTINGS

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_threshold_is_four_and_light_runs_read_express():
    assert SETTINGS.light_ready_min == 4
    assert SETTINGS.light_express_allowance >= 1


def test_refill_reads_only_what_the_pool_lacks():
    pytest.importorskip("sqlalchemy")
    from nishpaksh.run import refill_size
    t, y, whole = SETTINGS.refill_target, SETTINGS.refill_yield, SETTINGS.prep_queue
    assert refill_size(None) == whole                       # the count failed: the whole queue, as before
    assert refill_size(0) == min(whole, int(-(-t // y)))    # an empty pool needs the most
    assert refill_size(3) < refill_size(0) or refill_size(0) == whole
    assert refill_size(t) == SETTINGS.light_read_allowance  # nothing lacking: no more than a light run reads
    assert refill_size(t + 5) == SETTINGS.light_read_allowance
    assert all(1 <= refill_size(n) <= whole for n in range(0, 30))
    sizes = [refill_size(n) for n in range(0, 12)]
    assert sizes == sorted(sizes, reverse=True)             # the fuller the pool, the less is read


def _cands():
    now = dt.datetime(2026, 10, 29, 10, 0)
    return {i: {"read": i == 1, "lane": "sport", "sig": "india", "newest": now - dt.timedelta(minutes=i)} for i in range(1, 7)}


def test_express_focus_limit_replaces_the_reads_per_run(monkeypatch):
    monkeypatch.setattr(express, "candidates", lambda store, now=None: _cands())
    express.reset()
    assert express.focus(None, limit=0) == {1}              # only the story already begun is finished
    express.reset()
    assert len(express.focus(None, limit=1)) == 2           # begun + one new
    express.reset()
    assert len(express.focus(None)) == 1 + int(express.setting("reads_per_run", 3))   # a full run: its own cap


def test_ledger_adds_the_two_desk_reports_of_a_job():
    first = {"published": [1, 2], "seats": {"general": 2, "beat": 2}, "ready": 7, "tried": 2, "skipped": {"x": 1},
             "express": [2], "already_this_hour": 0}
    second = {"published": [9], "seats": {"general": 0, "beat": 1}, "ready": 3, "tried": 1, "skipped": {"x": 2, "y": 1},
              "express": [9]}
    m = ledger.merge_desk_reports([first, second])
    assert m["published"] == [1, 2, 9] and m["express"] == [2, 9] and m["tried"] == 3
    assert m["seats"] == first["seats"] and m["ready"] == 7           # the state at the start of the job
    assert m["skipped"] == {"x": 3, "y": 1}
    assert first["published"] == [1, 2]                               # the inputs are not changed
    assert ledger.merge_desk_reports([]) is None and ledger.merge_desk_reports([None, first])["tried"] == 2


def _steps():
    wf = yaml.safe_load((ROOT / ".github/workflows/hourly.yml").read_text())
    job = wf["jobs"]["run"]
    return job, job["steps"]


def test_workflow_writes_first_and_publishes_before_the_pipeline():
    job, steps = _steps()
    names = [s.get("name") or s.get("uses") for s in steps]
    prime, first, save_first, feed_first = (names.index(n) for n in (
        "Prime an almost empty pool", "Write and publish first (the desk)", "Save the newsroom (first desk run)",
        "Publish the feed (first desk run)"))
    pipe, again, save = (names.index(n) for n in ("Run pipeline", "Write and publish again (the desk)", "Save the newsroom"))
    assert names.index("Load the newsroom") < prime < first < save_first < feed_first < pipe < again < save
    by = {s.get("name"): s for s in steps}
    # a failed first desk run or prime must not skip the pipeline, and the pipeline runs whatever they did
    assert by["Write and publish first (the desk)"]["continue-on-error"] is True
    assert by["Prime an almost empty pool"]["continue-on-error"] is True
    assert "!cancelled()" in by["Run pipeline"]["if"] and "restore" in by["Run pipeline"]["if"]
    # saved and published early only when something was published; the cache key differs from the final one
    assert "published != '0'" in by["Save the newsroom (first desk run)"]["if"]
    keys = [s["with"]["key"] for s in steps if (s.get("uses") or "").startswith("actions/cache/save")]
    assert len(keys) == 2 and keys[0] != keys[1]
    assert job["timeout-minutes"] >= 150
    # the second desk run is for a full run only: skipped when the pipeline reports a light run
    assert "steps.pipeline.outputs.light != 'true'" in by["Write and publish again (the desk)"]["if"]
    assert "GITHUB_OUTPUT" in (ROOT / "nishpaksh/run.py").read_text() and "light=" in (ROOT / "nishpaksh/run.py").read_text()


def test_the_job_start_is_noted_for_the_gate():
    _, steps = _steps()
    note = next(s for s in steps if s.get("name") == "Note when this job started")
    assert "RUN_STARTED_AT" in note["run"] and "GITHUB_ENV" in note["run"]
    assert "RUN_STARTED_AT" in (ROOT / "nishpaksh/run.py").read_text()

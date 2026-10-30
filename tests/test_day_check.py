"""nishpaksh/tools/day_check.py: the daily read of the shadow samples against the owner's labels."""
import datetime as dt

from nishpaksh.tools import day_check

LABELS = {"folds": [{"dropped": "लेकिन अब तक का अनुभव", "label": "wrong"}],
          "inserted": [{"text": "A flash flood on the Nepal-China border in August", "label": "suspect"}]}


def run(shadow, at="2026-10-30T13:05:37Z"):
    return {"at": at, "shadow": shadow}


def test_a_labelled_wrong_fold_or_suspect_insertion_keeps_the_system_off_and_unread_samples_are_listed():
    runs = [run({"stories": 2, "lines": 40, "folded": 1, "would_fold": 2, "unverified": 1, "reader": True, "seconds": 3.5, "outcomes": {"covered": 1},
                 "sample_folds": [{"story": "1", "kept": "x", "dropped": "लेकिन अब तक का अनुभव बताता है", "reader": True}],
                 "sample_inserted": [{"story": "2", "text": "A flash flood on the Nepal-China border in August left 5,000 missing."},
                                     {"story": "2", "text": "Another line nobody has read."}]}),
            {"at": "2026-10-30T12:05:35Z"}, run({"error": "boom"}, "2026-10-30T11:05:00Z")]
    out = day_check.check(runs, LABELS)
    assert out["with_shadow"] == 1 and out["without_shadow"] == ["2026-10-30T12:05:35Z"] and out["errors"][0][1] == "boom"
    assert out["totals"]["would_fold"] == 2 and out["totals"]["seconds"] == 3.5
    assert out["verdict"]["tidy"].startswith("OFF") and out["verdict"]["also"].startswith("OFF")
    assert len(out["to_read"]["inserted"]) == 1 and out["to_read"]["folds"] == []


def test_runs_are_taken_from_the_window_only(tmp_path):
    (tmp_path / "runs-2026-10.jsonl").write_text('{"at":"2026-10-29T10:00:00Z"}\n{"at":"2026-10-30T10:00:00Z"}\n')
    got = day_check.runs_in_window(tmp_path, dt.datetime(2026, 10, 30, 0, 0, tzinfo=dt.timezone.utc))
    assert [r["at"] for r in got] == ["2026-10-30T10:00:00Z"]

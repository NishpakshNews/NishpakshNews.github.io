"""The daily read of the shadow systems, as a tool (owner, Oct 30 2026: "do the fixes and measurements").

    python -m nishpaksh.tools.day_check                      # the last 24 hours of ledger/runs-*.jsonl
    python -m nishpaksh.tools.day_check --hours 48 --ledger ledger --labels tests/labels/shadow_labels.json

Sums the `shadow` field of the runs in the window (stories, lines, pairs, outcomes, folds, reader verdicts, Also lines, would-insert,
why-not, seconds), lists runs with no shadow data or an error, matches every sampled fold and insertion against the labels file
(a sample already labelled `wrong` or `suspect` is shown first), and lists the UNLABELLED samples with their story context for a human
to read and label. Verdict by the owner's rule: any wrong sample keeps the system off; an unread sample is not a pass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import pathlib
from collections import Counter

SUMS = ("stories", "lines", "pairs", "folded", "would_fold", "unverified", "reader_refused", "inspector_repeats", "stories_with_fold",
        "stories_with_overlap", "to_one_sentence", "weekday_errors", "also_lines", "also_would_insert", "seconds")


def runs_in_window(ledger_dir: pathlib.Path, since: dt.datetime) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(ledger_dir / "runs-*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if r.get("at", "") >= since.strftime("%Y-%m-%dT%H:%M:%SZ"):
                    out.append(r)
    return out


def _label(labels: list[dict], key: str, text: str) -> dict | None:
    return next((x for x in labels if text and text.startswith((x.get(key) or "\0")[:60])), None)


def check(runs: list[dict], labels: dict) -> dict:
    have = [r for r in runs if isinstance(r.get("shadow"), dict) and "error" not in r["shadow"]]
    tot, outcomes, why = Counter(), Counter(), Counter()
    for r in have:
        s = r["shadow"]
        for k in SUMS:
            tot[k] += s.get(k, 0) or 0
        outcomes.update(s.get("outcomes") or {})
        why.update(s.get("also_why_not") or {})
    folds, inserted = [], []
    for r in have:
        for f in (r["shadow"].get("sample_folds") or []):
            folds.append({"at": r["at"], **{k: f.get(k) for k in ("story", "headline", "kept", "dropped", "reader")}, "a": f.get("a"), "b": f.get("b")})
        for x in (r["shadow"].get("sample_inserted") or []):
            inserted.append({"at": r["at"], **x})
    wrong_f = [f for f in folds if (_label(labels.get("folds", []), "dropped", f.get("dropped") or f.get("b") or "") or {}).get("label") == "wrong"]
    bad_i = [x for x in inserted if (_label(labels.get("inserted", []), "text", x.get("text")) or {}).get("label") in ("wrong", "suspect")]
    unlabelled_f = [f for f in folds if not _label(labels.get("folds", []), "dropped", f.get("dropped") or f.get("b") or "")]
    unlabelled_i = [x for x in inserted if not _label(labels.get("inserted", []), "text", x.get("text"))]
    return {"runs": len(runs), "with_shadow": len(have), "without_shadow": [r["at"] for r in runs if "shadow" not in r],
            "errors": [(r["at"], r["shadow"]["error"]) for r in runs if isinstance(r.get("shadow"), dict) and "error" in r["shadow"]],
            "readers": Counter(bool(r["shadow"].get("reader")) for r in have if "reader" in r["shadow"]),
            "totals": dict(tot), "outcomes": dict(outcomes), "also_why_not": dict(why),
            "known_wrong_folds": wrong_f, "known_wrong_or_suspect_inserts": bad_i,
            "to_read": {"folds": unlabelled_f, "inserted": unlabelled_i},
            "verdict": {"tidy": "OFF: a known wrong fold was sampled" if wrong_f else ("unproven: read the unlabelled folds" if unlabelled_f else "no wrong fold in this window"),
                        "also": "OFF: a wrong or suspect insertion was sampled" if bad_i else ("unproven: read the unlabelled insertions" if unlabelled_i else "no wrong insertion in this window")}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="ledger")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--labels", default="tests/labels/shadow_labels.json")
    ap.add_argument("--now")
    a = ap.parse_args()
    now = dt.datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else dt.datetime.now(dt.timezone.utc)
    labels = json.load(open(a.labels, encoding="utf-8")) if pathlib.Path(a.labels).exists() else {}
    print(json.dumps(check(runs_in_window(pathlib.Path(a.ledger), now - dt.timedelta(hours=a.hours)), labels), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()

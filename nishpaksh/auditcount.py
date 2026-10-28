"""Counters for the audit of the technical systems that replaced hand-written lists (owner, Oct 28 2026).

Each system (capword, speech, language, places) answers first and the old list answers when the system cannot; every time
both answered and they differ is counted here, in each direction, so the audit reads which of the two was wrong before any
list is deleted. `snapshot()` is saved with the run (`runs.stats["systems"]`) and printed by `tools/evaluate.py`.
"""
from __future__ import annotations

from collections import Counter

COUNTS: dict[str, Counter] = {}


def counter(section: str) -> Counter:
    return COUNTS.setdefault(section, Counter())


def reset() -> None:
    for c in COUNTS.values():
        c.clear()


def snapshot() -> dict[str, dict[str, int]]:
    return {k: dict(v) for k, v in COUNTS.items() if v}

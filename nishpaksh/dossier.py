"""The story dossier (B11): a code-readable trace of what each stage decided for one story.

NOT for the writer and never published: one JSON record per story in the newsroom table `dossiers`, one key per stage
(`reading`, `statements`, `bodies`, `writer`, ...), each stage replacing only its own key. It is how the single audit
pass tests a hypothesis without re-running the pipeline. Small by design: counts, ids, verdicts and reasons, never article
text. Written with `record()` (never raises, a failure to record never stops a stage); forgotten after RETAIN_DAYS.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

log = logging.getLogger("nishpaksh.dossier")

RETAIN_DAYS = 14
MAX_BYTES = 60_000


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _clip(x, depth: int = 0):
    """Plain JSON, lists cut at 60 items and strings at 200 characters (a trace, not a copy of the story)."""
    if isinstance(x, dict):
        return {str(k): _clip(v, depth + 1) for k, v in list(x.items())[:60]}
    if isinstance(x, (list, tuple, set)):
        return [_clip(v, depth + 1) for v in list(x)[:60]]
    if isinstance(x, str):
        return x[:200]
    if isinstance(x, (int, float, bool)) or x is None:
        return x
    return str(x)[:200]


def record(store, story_id: int, stage: str, data: dict) -> bool:
    """Replace the `stage` key of the story's dossier with `data`."""
    try:
        from sqlalchemy import delete, insert, select
        from .db import dossiers
        row = store.one(select(dossiers.c.data).where(dossiers.c.story_id == story_id))
        cur = dict((row or {}).get("data") or {})
        cur[stage] = {"at": _now().isoformat(timespec="seconds"), **_clip(data)}
        if len(json.dumps(cur)) > MAX_BYTES:
            cur = {stage: cur[stage]}
        with store.route(insert(dossiers)).engine.begin() as c:
            c.execute(delete(dossiers).where(dossiers.c.story_id == story_id))
            c.execute(insert(dossiers).values(story_id=story_id, updated_at=_now(), data=cur))
        return True
    except Exception as e:  # noqa: BLE001
        log.info("dossier not recorded (%s): %s", stage, str(e)[:100])
        return False


LOG_MAX = 200


def append(store, story_id: int, stage: str, entry: dict) -> bool:
    """E5: an append-only event log beside the per-stage records: every drop, default and decision a stage wants kept is one
    entry {stage, at, ...} in the story's `log` list (the newest LOG_MAX are kept). Never raises."""
    try:
        from sqlalchemy import delete, insert, select
        from .db import dossiers
        row = store.one(select(dossiers.c.data).where(dossiers.c.story_id == story_id))
        cur = dict((row or {}).get("data") or {})
        lines = list(cur.get("log") or [])
        lines.append({"stage": stage, "at": _now().isoformat(timespec="seconds"), **_clip(entry)})
        cur["log"] = lines[-LOG_MAX:]
        if len(json.dumps(cur)) > MAX_BYTES:
            cur["log"] = cur["log"][-LOG_MAX // 4:]
        with store.route(insert(dossiers)).engine.begin() as c:
            c.execute(delete(dossiers).where(dossiers.c.story_id == story_id))
            c.execute(insert(dossiers).values(story_id=story_id, updated_at=_now(), data=cur))
        return True
    except Exception as e:  # noqa: BLE001
        log.info("dossier log not appended (%s): %s", stage, str(e)[:100])
        return False


def prune(store) -> int:
    try:
        from .db import delete, dossiers
        return store.exec(delete(dossiers).where(dossiers.c.updated_at < _now() - dt.timedelta(days=RETAIN_DAYS))) or 0
    except Exception as e:  # noqa: BLE001
        log.info("dossier prune skipped: %s", str(e)[:100])
        return 0


def statements_trace(items: list[dict]) -> list[dict]:
    """What the verdict stage decided, per statement: id, verdict, independent sources, origins, speaker."""
    return [{"id": i.get("id"), "verdict": i.get("verdict"), "sources": i.get("n_sources"), "articles": i.get("n_articles"),
             "origins": i.get("n_origins"), "speaker": i.get("speaker"), "minor": i.get("minor")} for i in items]

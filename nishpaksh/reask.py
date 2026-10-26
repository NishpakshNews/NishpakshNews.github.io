"""E1: a closed value the reading model got wrong is asked ONCE more, then it stays what the safe default says.

The reading model sometimes writes a stance outside the three allowed ("claims", "reports", "stated"). Until now that
became "attributes" (the cautious default, counted). Here one small closed question per article gives the statement a
second chance: ONE batched call, three fixed answers, the report's own sentence beside each statement, worked examples
including the trap (a statement that only reports what somebody said is "attributes", never "asserts"). Code accepts an
answer only if it is one of the three; anything else keeps the default. It can only change a statement to a value the
model chose from a closed set, and "asserts" is the only value that can make a line easier to support, so an answer of
"asserts" is taken only when the statement's own speaker slot is the article itself (nobody is named as saying it).
Counted, capped per run (shares the quality tier's cap with readcheck), never a reason to lose a reading."""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

MAX_CALLS_PER_RUN = 20
STATS: dict[str, int] = {}
_lock = threading.Lock()
_calls = 0
ALLOWED = ("asserts", "attributes", "denies")

PROMPT = """For each numbered statement, say how the news report presents it. Choose exactly one word:
asserts    = the report itself states it as a fact, nobody is named as saying it
attributes = the report only tells that someone said, claimed, alleged or reported it
denies     = the report says it is NOT true or did not happen
If unsure: attributes.

Examples:
"Police arrested three men." (report: "Three men were arrested, police said.") -> attributes
"The bridge collapsed on Monday." (report: "The bridge collapsed on Monday.") -> asserts
"The minister did not resign." (report: "The minister denied he had resigned.") -> denies

{items}

Answer as JSON: {{"answers": ["word", "word"]}} with exactly {n} entries, in the same order."""


def reset_run() -> None:
    global _calls
    with _lock:
        _calls = 0


def _stat(k: str, n: int = 1) -> None:
    with _lock:
        STATS[k] = STATS.get(k, 0) + n


def _take() -> bool:
    global _calls
    with _lock:
        if _calls >= MAX_CALLS_PER_RUN:
            return False
        _calls += 1
        return True


def _flagged(ex: dict) -> list[dict]:
    return [it for kind in ("events", "claims") for it in ex.get(kind) or [] if it.get("stance_invalid")]


def check(ex: dict, router) -> int:
    """Re-ask the stance of every statement whose first answer was outside the closed set. Returns how many changed."""
    from .router import CallFailed, QuotaExhausted, parse_json
    flagged = _flagged(ex)
    if not flagged or router is None:
        return 0
    _stat("invalid", len(flagged))
    try:
        if router.remaining_now("quality") <= 0:
            _stat("no_quota")
            return 0
    except Exception:  # noqa: BLE001
        return 0
    if not _take():
        _stat("over_cap")
        return 0
    flagged = flagged[:25]
    items = "\n".join(f'{k + 1}. STATEMENT: {it["text"]}\n   REPORT: {it.get("quote") or ""}' for k, it in enumerate(flagged))
    try:
        res = router.call("quality", PROMPT.format(items=items, n=len(flagged)), json_out=True,
                          max_output_tokens=60 + 12 * len(flagged))
    except (QuotaExhausted, CallFailed) as e:
        _stat("refused")
        log.info("stance re-ask skipped: %s", str(e)[:120])
        return 0
    data = res.data if getattr(res, "data", None) is not None else parse_json(res.text or "")
    got = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(got, list) or len(got) != len(flagged):
        _stat("unparsed")
        return 0
    _stat("calls")
    changed = 0
    for it, ans in zip(flagged, got):
        a = str(ans or "").strip().lower().strip(".")
        if a not in ALLOWED:
            _stat("still_invalid")
            continue
        if a == "asserts" and (it.get("attributed_to") or "article") != "article":
            _stat("refused_asserts")        # a named speaker and "asserts" disagree: keep the cautious default
            continue
        it["stance"] = a
        it["stance_defaulted"] = False
        it["stance_invalid"] = False
        changed += 1
    _stat("fixed", changed)
    return changed

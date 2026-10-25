"""A reading checked against its report (session 7 of the translation/learning plan, Oct 16 2026).

Each statement the reading model wrote from an article (English or Hindi) is compared with the sentence of the article
it came from. EVERY statement (owner, Oct 16 2026: anchors found the sentence for about one in four Hindi statements):
the reading model copies the first six words of that sentence (`quote`), code finds them word for word in the
article (fidelity.quoted_window); only when the copy is not there does it fall back to numbers, dates, names and
(fidelity.source_window). The report's sentence must entail the statement (the local NLI model, nli.py). A statement the
report does not support ("the only authorized sites" where the report said designated) or contradicts gets ONE repair:
all of an article's flagged statements in one call on the quality tier (the Translator key), each shown with its
source sentence and its problem. The repaired text is taken only when the check then passes and it keeps the
statement's numbers; otherwise the statement stays as read and is counted.

Kept, not dropped: the stored audit (four runs, Oct 16 2026) showed real catches beside cases where a statement was
matched to the wrong sentence of a long report; dropping on a flag would lose good statements. `DROP_UNREPAIRED`
switches dropping on once the counts show the flags can be trusted.

A statement whose stance is "denies" is written as the positive claim being denied (the reading prompt's rule 4), so
negation is not compared for it. No quality quota, or the per-run cap reached: nothing is repaired, nothing waits.
"""
from __future__ import annotations

import logging
import threading

from . import fidelity as F

log = logging.getLogger(__name__)

MAX_CALLS_PER_RUN = 30          # repair calls per pipeline run (quality tier, shared with names and the edit pass)
DROP_UNREPAIRED = False
STATS: dict[str, int] = {}
_lock = threading.Lock()
_calls = 0

REPAIR_PROMPT = """Each numbered line below is a statement written from a news report, the sentence of the report it
comes from, and a PROBLEM: the report sentence does not support the statement as written. Rewrite each statement so it says
exactly what the report sentence says about the same thing, no stronger and no weaker. Change nothing else: same facts, names
and numbers, in plain English. If the statement is already faithful to the report, return it unchanged.

{items}

Answer as JSON: {{"statements": ["...", "..."]}} with exactly {n} entries, in the same order."""

def reset_run() -> None:
    global _calls
    with _lock:
        _calls = 0


def _stat(k: str, n: int = 1) -> None:
    with _lock:
        STATS[k] = STATS.get(k, 0) + n


def _take_call() -> bool:
    global _calls
    with _lock:
        if _calls >= MAX_CALLS_PER_RUN:
            return False
        _calls += 1
        return True


def problems_of(item: dict, source: str, lang: str, registry=None) -> tuple[str | None, list[F.Problem]]:
    """(the source sentence, the strict problems) of one statement; a denial is only checked for contradiction-free support."""
    return F.check_reading(item.get("text") or "", source, lang, registry, strict_only=True,
                           quote=item.get("quote"), stance=item.get("stance"))


def _describe(p: F.Problem) -> str:
    return ("the report says the opposite" if p.kind == "contradicted"
            else "the report's sentence does not support the statement as written")


def check(ex: dict, source: str, lang: str, router=None, registry=None) -> dict:
    """Check every statement of a reading against its article; repair the flagged ones once. Changes `ex` in place;
    returns counts."""
    out = {"checked": 0, "sourced": 0, "by_quote": 0, "by_anchors": 0, "unsourced": 0, "flagged": 0, "repaired": 0,
           "kept": 0, "dropped": 0}
    flagged = []
    for kind in ("events", "claims", "context"):
        for it in ex.get(kind) or []:
            out["checked"] += 1
            _, how = F.find_source(it.get("text") or "", source, lang, registry, it.get("quote"))
            out["by_quote" if how == "quote" else "by_anchors" if how == "anchors" else "unsourced"] += 1
            win, probs = problems_of(it, source, lang, registry)
            if win is not None:
                out["sourced"] += 1
            if probs:
                flagged.append((kind, it, win, probs))
    out["flagged"] = len(flagged)
    if not flagged:
        return out
    fixed = _repair(router, flagged) if router is not None else {}
    drop: set[str] = set()
    for k, (kind, it, win, probs) in enumerate(flagged):
        new = fixed.get(k)
        if new and _accept(it, new, source, lang, registry):
            log.info("reading repaired (%s): %s -> %s", ", ".join(map(str, probs)), it["text"][:100], new[:100])
            it["text"] = new
            out["repaired"] += 1
        elif DROP_UNREPAIRED:
            drop.add(it.get("id"))
            out["dropped"] += 1
        else:
            log.info("reading kept with %s: %s", ", ".join(map(str, probs)), it["text"][:120])
            out["kept"] += 1
    if drop:
        for kind in ("events", "claims", "context"):
            ex[kind] = [i for i in ex.get(kind) or [] if i.get("id") not in drop]
        ex["relations"] = [r for r in ex.get("relations") or [] if r["from"] not in drop and r["to"] not in drop]
    for k, v in out.items():
        _stat(k, v)
    return out


def _accept(item: dict, new: str, source: str, lang: str, registry) -> bool:
    """A repair is taken when the check passes on it and it keeps the statement's numbers."""
    if F.numbers(new) != F.numbers(item.get("text") or ""):
        return False
    _, probs = problems_of(dict(item, text=new), source, lang, registry)
    return not probs


def _repair(router, flagged: list) -> dict[int, str]:
    from .router import CallFailed, QuotaExhausted, parse_json
    try:
        if router.remaining_now("quality") <= 0:
            _stat("no_quota")
            return {}
    except Exception:  # noqa: BLE001
        return {}
    if not _take_call():
        _stat("over_cap")
        return {}
    items = "\n".join(f'{k + 1}. STATEMENT: {it["text"]}\n   REPORT: {win}\n   PROBLEM: '
                      + "; ".join(_describe(p) for p in probs) for k, (_, it, win, probs) in enumerate(flagged))
    try:
        res = router.call("quality", REPAIR_PROMPT.format(items=items, n=len(flagged)), json_out=True,
                          max_output_tokens=100 + 80 * len(flagged))
    except (QuotaExhausted, CallFailed) as e:
        _stat("refused")
        log.info("reading repair skipped: %s", str(e)[:120])
        return {}
    data = res.data if getattr(res, "data", None) is not None else parse_json(res.text or "")
    got = data.get("statements") if isinstance(data, dict) else None
    if not isinstance(got, list) or len(got) != len(flagged):
        return {}
    _stat("calls")
    return {k: str(v).strip() for k, v in enumerate(got) if str(v or "").strip()}

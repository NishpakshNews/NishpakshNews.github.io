"""Statements across a story's reports: on arrival, a new report's statement joins one whose words are
plainly the same (relate.py) or becomes a new statement. The model questions the story review asks are
here: same fact? (same_facts), says it all? (covers_facts), can both be true? (check_conflicts). Each is
one plain question, asked in small batches; the callers ask twice and decide (relate.py, disputes.py).
"""
from __future__ import annotations

import logging
import re

from .config import SETTINGS
from .db import Store, canonical, claims, delete, select, update
from . import nli
from .relate import relate
from .router import Router

log = logging.getLogger(__name__)

def check_conflicts(router, pairs: list[tuple[str, str]]) -> list[str | None]:
    """Can both statements be true? Local NLI, contradiction read in both directions (nli.conflict). Every proposed
    contradiction passes through it, whoever proposed it. Anything but a clear "cannot both be true" is not a
    contradiction; "unsure" keeps such statements from being established. None = the pair could not be read
    (the model did not load), never "unsure": the caller must not remember it."""
    return nli.conflict(pairs) if pairs else []


def same_facts(router, pairs: list[tuple[str, str]], firsts: dict | None = None) -> list[bool | None]:
    """Are these the same fact in other words? Each sentence must entail the other (nli.same: both directions are
    always read, so the answer cannot depend on which line came first). Three-valued: None = could not be read.
    `firsts` records the forward reading for the writing layer's fact groups."""
    if not pairs:
        return []
    from . import aggregate
    res = aggregate.gate(pairs, nli.same(pairs))        # S12: the judges together, only ever more cautious
    if firsts is not None:
        firsts.update({i: ok for i, ok in enumerate(res) if ok is not None})
    return res


def covers_facts(router, pairs: list[tuple[str, str]], firsts: dict | None = None) -> list[bool | None]:
    """(detailed, short) pairs: does the detailed line entail the short one? None = could not be read."""
    if not pairs:
        return []
    res = nli.covers(pairs)
    if firsts is not None:
        firsts.update({i: ok for i, ok in enumerate(res) if ok is not None})
    return res


def _create_canonical(store: Store, story_id: int, kind: str, text: str, frame: dict | None = None,
                      time: dict | None = None) -> int:
    # a statement's frame (frames.py) is kept with it: who / action / what / value, and its time
    rel = {"frame": frame, "time": time} if frame else None
    return store.insert_returning_id(canonical, dict(story_id=story_id, kind=kind, text=text, conflicts=[],
                                                     verdict="pending", checked_members=0, rel=rel))


def frame_of(c: dict) -> tuple[dict | None, dict | None]:
    """(frame, time) of a statement (canonical row), or (None, None) if it was read before frames."""
    rel = c.get("rel") or {}
    return (rel.get("frame"), rel.get("time")) if c.get("kind") != "relation" else (None, None)


def _merge(store: Store, src: int, dst: int) -> None:
    store.exec(update(claims).where(claims.c.canonical_id == src).values(canonical_id=dst))
    src_row = store.one(select(canonical).where(canonical.c.id == src))
    dst_row = store.one(select(canonical).where(canonical.c.id == dst))
    conf = sorted(set((dst_row["conflicts"] or []) + (src_row["conflicts"] or [])) - {src, dst})
    kind = "event" if "event" in (src_row["kind"], dst_row["kind"]) else dst_row["kind"]
    store.exec(update(canonical).where(canonical.c.id == dst).values(conflicts=conf, kind=kind))
    store.exec(delete(canonical).where(canonical.c.id == src))
    for r in store.rows(select(canonical).where(canonical.c.story_id == dst_row["story_id"])):
        if src in (r["conflicts"] or []):
            new = sorted(set(c if c != src else dst for c in r["conflicts"]) - {r["id"]})
            store.exec(update(canonical).where(canonical.c.id == r["id"]).values(conflicts=new))


def _add_conflict(store: Store, a: int, b: int) -> None:
    for x, y in ((a, b), (b, a)):
        r = store.one(select(canonical).where(canonical.c.id == x))
        if r and y not in (r["conflicts"] or []):
            store.exec(update(canonical).where(canonical.c.id == x).values(conflicts=sorted((r["conflicts"] or []) + [y])))


def _remove_conflict(store: Store, a: int, b: int) -> None:
    for x, y in ((a, b), (b, a)):
        r = store.one(select(canonical).where(canonical.c.id == x))
        if r and y in (r["conflicts"] or []):
            store.exec(update(canonical).where(canonical.c.id == x).values(conflicts=[c for c in r["conflicts"] if c != y]))


def prune_orphans(store: Store, story_id: int) -> int:
    """Statements no report supports any more (their articles were retracted or moved to another
    story) are removed, along with references to them."""
    used = {r["canonical_id"] for r in store.rows(select(claims.c.canonical_id).where(
        claims.c.story_id == story_id, claims.c.canonical_id.is_not(None)))}
    canon = store.rows(select(canonical.c.id, canonical.c.conflicts, canonical.c.rel).where(canonical.c.story_id == story_id))
    dead = [c["id"] for c in canon if c["id"] not in used]
    if not dead:
        return 0
    store.exec(delete(canonical).where(canonical.c.id.in_(dead)))
    dead_set = set(dead)
    for c in canon:
        if c["id"] in dead_set:
            continue
        conf = [x for x in (c["conflicts"] or []) if x not in dead_set]
        if conf != (c["conflicts"] or []):
            store.exec(update(canonical).where(canonical.c.id == c["id"]).values(conflicts=conf))
    return len(dead)


def match_story(store: Store, router: Router | None, story_id: int) -> None:
    """A new report's statements, on arrival: each joins a statement whose words are plainly the same
    (relate.py, code only), or becomes a new statement. Everything that needs judgement (same fact in
    other words, a line covering another, disputes) is decided once, for the whole story, in the story
    review (consolidate.py), by one structure each (owner, Oct 7 2026)."""
    prune_orphans(store, story_id)
    rows = store.rows(select(claims).where(claims.c.story_id == story_id).order_by(claims.c.id))
    new = [r for r in rows if r["kind"] in ("event", "claim") and r["canonical_id"] is None]
    if new:
        from .relate import Profile
        canon = store.rows(select(canonical).where(canonical.c.story_id == story_id, canonical.c.kind != "relation"))
        known = [(c["id"], c["text"], Profile(c["text"]), frame_of(c)[1]) for c in canon]
        for r in new:
            fr = ((r["rel"] or {}).get("frame"))
            pr = Profile(r["text"])
            cid = next((cid_ for cid_, t_, p_, time_ in known
                        if relate(r["text"], t_, r["time"], time_, pr, p_) == "same"), None)
            if cid is None:
                cid = _create_canonical(store, story_id, r["kind"], r["text"], fr, r["time"])
                known.append((cid, r["text"], pr, r["time"]))
            store.exec(update(claims).where(claims.c.id == r["id"]).values(canonical_id=cid))
            if r["kind"] == "event":
                store.exec(update(canonical).where(canonical.c.id == cid).values(kind="event"))
    _match_relations(store, story_id)


def _match_relations(store: Store, story_id: int) -> None:
    rows = store.rows(select(claims).where(claims.c.story_id == story_id))
    local = {(r["article_id"], r["local_id"]): r["canonical_id"] for r in rows if r["kind"] != "relation"}
    existing = {}
    for c in store.rows(select(canonical).where(canonical.c.story_id == story_id, canonical.c.kind == "relation")):
        rel = c["rel"] or {}
        existing[(rel.get("from"), rel.get("to"), rel.get("type"))] = c["id"]
    for r in rows:
        if r["kind"] != "relation" or not r["rel"]:
            continue
        a = local.get((r["article_id"], r["rel"]["from"]))
        b = local.get((r["article_id"], r["rel"]["to"]))
        if a is None or b is None or a == b:
            continue
        key = (a, b, r["rel"]["type"])
        if key not in existing:
            existing[key] = store.insert_returning_id(canonical, dict(
                story_id=story_id, kind="relation", text="", rel={"from": a, "to": b, "type": key[2]},
                conflicts=[], verdict="pending", checked_members=0))
        if r["canonical_id"] != existing[key]:
            store.exec(update(claims).where(claims.c.id == r["id"]).values(canonical_id=existing[key]))
    # relations whose endpoints were merged away are stale; re-point them
    valid = {c["id"] for c in store.rows(select(canonical.c.id).where(canonical.c.story_id == story_id))}
    for key, cid in existing.items():
        if key[0] not in valid or key[1] not in valid:
            store.exec(update(claims).where(claims.c.canonical_id == cid).values(canonical_id=None))
            store.exec(delete(canonical).where(canonical.c.id == cid))

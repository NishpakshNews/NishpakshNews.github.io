"""Threads: a later story that is a development of an earlier one (an arrest after a crime, a court
step in a case, a reaction to a decision) is linked to it: parent -> daughter. A story may have
several parents (two probes merging) and several daughters.

How a link is found, once per story (cached until its headline changes), with no model call (B34): the published
stories that came before it are ranked by the meaning of their headlines and openings (the multilingual bi-encoder,
embed.py; TF-IDF cosine when it is not available). An earlier story is the parent when it is close enough (LINK) AND the
two share a specific name (person, place, organisation or case: a capitalised word the corpus does not use everywhere,
idf.py) AND the NLI cross-encoder does not find the two reports contradicting each other as one event. A wrong link would
put one story's context into another, so all three must hold; unsure = no link.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

from sqlalchemy import func

from .db import Store, published, select, stories, story_links, update, utcnow, insert, delete
from .router import Router

log = logging.getLogger(__name__)

LINK = {"bi-encoder": 0.6, "tfidf": 0.3}      # similarity an earlier story needs to be a parent (untuned: read in the audit)


def existing_parents(store: Store, story_id: int) -> set[int]:
    return {r["parent_id"] for r in store.rows(select(story_links.c.parent_id).where(story_links.c.child_id == story_id))}


def _shared_names(a: str, b: str, weights) -> set[str]:
    """Capitalised words (names, acronyms) both texts have that are not everywhere in the corpus: the specific case,
    not "Delhi" or "India" alone (idf weight at least HALF of a word seen once)."""
    return {w for w in _names(a) & _names(b) if weights.w(w) >= 0.25}


def _words(s: str) -> set[str]:
    from .idf import tokens
    return tokens(s)


def _names(s: str) -> set[str]:
    """Capitalised words and acronyms: the specific names a real link must share."""
    from .idf import ENGLISH_STOP_WORDS
    return {w.lower() for w in re.findall(r"\b(?:[A-Z][a-z]{2,}|[A-Z]{2,})\b", s or "") if w.lower() not in ENGLISH_STOP_WORDS}


def _summary(row: dict) -> str:
    p = row["payload_en"] or {}
    first = ""
    paras = (p.get("narrative") or {}).get("paragraphs") or []
    if paras and paras[0]:
        first = " ".join(x["text"] for x in paras[0][:2])
    return f'{p.get("headline") or row.get("headline_en") or ""}. {first}'[:500]


def _slim(headline, s0, s1) -> dict:
    """The part of a page `_summary` reads: its headline and the first two sentences of its lead."""
    first = [{"text": t} for t in (s0, s1) if t]
    return {"headline": headline, "narrative": {"paragraphs": [first] if first else []}}


def find_parents(store: Store, router: Router | None, story_id: int, headline: str, summary: str,
                 max_candidates: int = 6, window_days: int = 60) -> list[int]:
    story = store.one(select(stories.c.analysis, stories.c.created_at).where(stories.c.id == story_id))
    if not story:
        return [r["parent_id"] for r in store.rows(select(story_links.c.parent_id).where(story_links.c.child_id == story_id))]
    analysis = dict(story["analysis"] or {})
    # checked once per headline, and again whenever an article was published since (Oct 7 2026: two
    # stories of the same Supreme Court order were published a minute apart; the second had been
    # checked before the first went live)
    newest = store.one(select(func.max(published.c.updated_at).label("t")).where(published.c.story_id != story_id))
    newest = newest["t"].isoformat() if newest and newest["t"] else ""
    if analysis.get("thread_checked") == headline and str(analysis.get("thread_checked_at") or "") >= newest:
        return [r["parent_id"] for r in store.rows(select(story_links.c.parent_id).where(story_links.c.child_id == story_id))]
    since = utcnow() - dt.timedelta(days=window_days)
    # only the headline and the first two sentences of each page are needed (`_summary`): a whole page is
    # ~70 KB, and reading every live page for every story checked was the largest egress (Oct 10 2026)
    pe = published.c.payload_en
    rows = [{"story_id": r["story_id"], "headline_en": r["headline_en"], "updated_at": r["updated_at"],
             "payload_en": _slim(r["h"], r["s0"], r["s1"])}
            for r in store.rows(select(published.c.story_id, published.c.headline_en, published.c.updated_at,
                                       pe[("headline",)].as_string().label("h"),
                                       pe[("narrative", "paragraphs", 0, 0, "text")].as_string().label("s0"),
                                       pe[("narrative", "paragraphs", 0, 1, "text")].as_string().label("s1"))
                                .where(published.c.story_id != story_id, published.c.updated_at >= since))]
    created = {r["id"]: r["created_at"] for r in store.rows(select(stories.c.id, stories.c.created_at)
                                                             .where(stories.c.id.in_([r["story_id"] for r in rows] or [-1])))}
    # parents that already moved to the archive branch (pagearchive.py) are candidates too
    from . import pagearchive
    have = {r["story_id"] for r in rows}
    # strict: an archive that cannot be asked raises Unreachable BEFORE the check is marked done below, so the story
    # is checked again against the archived articles next run (it used to be marked checked with none of them seen)
    for x in pagearchive.recent_index(window_days, strict=True):
        if x.get("story_id") not in have and x.get("story_id") != story_id:
            rows.append({"story_id": x["story_id"], "headline_en": x.get("headline_en"),
                         "payload_en": {"headline": x.get("headline_en"),
                                        "narrative": {"paragraphs": [[{"text": x.get("summary") or ""}]]}},
                         "updated_at": None})
            created.setdefault(x["story_id"], _when(x.get("written_at")))
    daughters = {r["child_id"] for r in store.rows(select(story_links.c.child_id).where(story_links.c.parent_id == story_id))}
    # candidate retrieval and decision (B34): meaning similarity, a shared specific name, and no contradiction
    from . import embed, idf, nli
    pool = [r for r in rows if r["story_id"] not in daughters]     # only a daughter of this story cannot be its parent
    texts = [_summary(r) for r in pool]
    new_text = f"{headline}. {summary}"[:600]
    found: list[int] = []
    cands: list[tuple] = []
    if texts:
        vecs, how = embed.vectors([new_text] + texts)
        sims = vecs[1:] @ vecs[0]
        order = sorted(range(len(texts)), key=lambda i: -sims[i])[:max_candidates]
        need = LINK[how]
        close = [i for i in order if float(sims[i]) >= need]
        weights = idf.Weights([new_text] + texts)
        for i in close:
            shared = _shared_names(new_text, texts[i], weights)
            if shared:
                cands.append((round(float(sims[i]) * 100), pool[i]["story_id"], texts[i], shared))
        if cands:
            res = nli.predict([(c[2], new_text) for c in cands])
            if any(r is None for r in res):
                return sorted(existing_parents(store, story_id))          # could not ask: no new link, checked again next run
            for c, r in zip(cands, res):
                if r[2] < nli.UNSURE:
                    found.append(c[1])
    existing = {r["parent_id"] for r in store.rows(select(story_links.c.parent_id).where(story_links.c.child_id == story_id))}
    for pid in found:
        if pid not in existing:
            store.exec(insert(story_links).values(parent_id=pid, child_id=story_id, created_at=utcnow(),
                                                  reason=json.dumps(sorted(next(c[3] for c in cands if c[1] == pid)))))
            # the parent is a closed article (editions.py): it is not touched
    analysis["thread_checked"] = headline
    analysis["thread_checked_at"] = newest
    store.exec(update(stories).where(stories.c.id == story_id).values(analysis=analysis))
    if found:
        log.info("threads: story %s develops %s", story_id, found)
    return sorted(existing | set(found))


def _when(ts) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(ts)) if ts else None
    except ValueError:
        return None


def relatives(store: Store, story_id: int) -> tuple[list[int], list[int]]:
    parents = [r["parent_id"] for r in store.rows(select(story_links.c.parent_id).where(story_links.c.child_id == story_id))]
    children = [r["child_id"] for r in store.rows(select(story_links.c.child_id).where(story_links.c.parent_id == story_id))]
    return parents, children


def root_of(store: Store, story_id: int, depth: int = 20) -> int:
    """The earliest ancestor (the thread's first story); with several parents, the oldest line."""
    seen = {story_id}
    cur = story_id
    for _ in range(depth):
        ps = sorted(r["parent_id"] for r in store.rows(select(story_links.c.parent_id).where(story_links.c.child_id == cur)))
        ps = [p for p in ps if p not in seen]
        if not ps:
            return cur
        cur = ps[0]
        seen.add(cur)
    return cur


def drop_links_of(store: Store, story_id: int) -> None:
    store.exec(delete(story_links).where((story_links.c.parent_id == story_id) | (story_links.c.child_id == story_id)))


# ---------------------------------------------------------------------------- facts shared along a thread
# (owner, Oct 16 2026: a fact green on the earlier page was purple on its follow-up, and the earlier page never saw
# the reports that came later.) The follow-up check (editions._classify) says, for each statement of a candidate
# follow-up, which earlier statement says the SAME fact and which one it UPDATES with newer information. Saved here
# in `canonical.rel` both ways:
#   twins          the same fact on another page of the thread: verify.base_verdicts counts the twins' origins
#                  and outlets with its own, so the fact has ONE colour on every page and an earlier page's line
#                  matures as later reports come in
#   superseded_by  (on the earlier statement) the later statements that replace it: the earlier page strikes the
#                  line and lists the newer one under "Updates since published" (editions.attach_updates)
#   updates        (on the later statement) the earlier one it replaces

def save_links(store: Store, parent_id: int, judged: dict) -> int:
    """Save the twins and updates the follow-up check found between a candidate's statements and its parent's.
    `judged`: {later canonical id: {"same_as": earlier id | None, "updates": earlier id | None, ...}}."""
    from .db import canonical
    later = {int(k): v for k, v in judged.items()}
    earlier_ids = {v.get(x) for v in later.values() for x in ("same_as", "updates")} - {None}
    rows = {r["id"]: r for r in store.rows(select(canonical.c.id, canonical.c.story_id, canonical.c.rel)
                                           .where(canonical.c.id.in_(sorted(set(later) | earlier_ids) or [-1])))}
    changed: dict[int, dict] = {}

    def rel(cid):
        if cid not in changed:
            changed[cid] = dict((rows.get(cid) or {}).get("rel") or {})
        return changed[cid]
    # the parent's statements: what this candidate said before is replaced by what it says now
    for r in store.rows(select(canonical.c.id, canonical.c.rel).where(canonical.c.story_id == parent_id)):
        rows.setdefault(r["id"], dict(r, story_id=parent_id))
        old = r["rel"] or {}
        if set(old.get("twins") or []) & set(later) or set(old.get("superseded_by") or []) & set(later):
            x = rel(r["id"])
            x["twins"] = [t for t in x.get("twins") or [] if t not in later]
            x["superseded_by"] = [t for t in x.get("superseded_by") or [] if t not in later]
    n = 0
    for cid, v in later.items():
        if cid not in rows:
            continue
        x = rel(cid)
        x.pop("twins", None)
        x.pop("updates", None)
        same, upd = v.get("same_as"), v.get("updates")
        if same in rows and rows[same]["story_id"] != rows[cid]["story_id"]:
            x["twins"] = [same]
            y = rel(same)
            y["twins"] = sorted(set(y.get("twins") or []) | {cid})
            n += 1
        if upd in rows and upd != same and rows[upd]["story_id"] != rows[cid]["story_id"]:
            x["updates"] = upd
            y = rel(upd)
            y["superseded_by"] = sorted(set(y.get("superseded_by") or []) | {cid})
            n += 1
    for cid, x in changed.items():
        x = {k: v for k, v in x.items() if v not in ([], None)}
        store.exec(update(canonical).where(canonical.c.id == cid).values(rel=x or None))
    return n


def twin_rows(store: Store, canon: dict[int, dict]) -> dict[int, dict]:
    """{canonical id: row} of the twins (on other pages of the thread) of these statements."""
    from .db import canonical
    ids = sorted({t for c in canon.values() for t in ((c.get("rel") or {}).get("twins") or []) if t not in canon})
    if not ids:
        return {}
    return {r["id"]: r for r in store.rows(select(canonical.c.id, canonical.c.story_id, canonical.c.verdict,
                                                  canonical.c.origins, canonical.c.checkable)
                                           .where(canonical.c.id.in_(ids)))}


def pooled_origins(own: dict | None, twins: list[dict]) -> dict | None:
    """A statement's origins counted with its twins': origins and outlets as one set (origins.py keys are the same
    on every page; outlets by their source keys where known, else the largest count)."""
    if not twins:
        return own
    from .origins import POOL
    infos = [own or {}] + [t.get("origins") or {} for t in twins]
    origins = sorted(set().union(*[set(i.get("origins") or []) for i in infos]))
    if all(i.get("outlet_keys") is not None for i in infos):
        outlets = len(set().union(*[set(i.get("outlet_keys") or []) for i in infos]))
    else:
        outlets = max(int(i.get("outlets") or 0) for i in infos)
    out = dict(own or {})
    out.update(origins=origins, n_origins=len([o for o in origins if o != POOL]), outlets=outlets)
    return out

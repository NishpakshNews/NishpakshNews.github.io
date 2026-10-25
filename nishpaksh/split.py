"""One fact per statement: compound statements split into their single facts (owner, Oct 8 2026).

Story 13970 (RBI raises the repo rate): "the repo rate is the rate at which the RBI lends to banks" was
written three times, the rate decision four times, the EMI effect six or seven. Outlets write compound
sentences: A = "Repo rate is the rate at which the RBI lends to banks, and an increase raises borrowing
costs", B = "Repo rate is the rate at which the RBI provides loans to banks, which banks use as a basis for
lending". A and B share one fact and each adds another, so neither covers the other: they stayed two
statements and the shared part was written twice. The unit of the article is the single fact.

So, after reading and before matching, a fact row whose text is compound is split into its single facts
(at most 3, 4 allowed; more and it stays whole). The clauses come from a dependency parse (nlp.clauses: coordinated
verbs, a reported clause keeping its speaker, a relative clause), then code checks every piece (`_pieces_ok`): its numbers and names come from
the original, nearly all its words do, the pieces together carry every number and name of the original, a
speaker's statement keeps its speaker in every piece ("X said A and B" -> "X said A", "X said B"), a "not"
is never lost or added. Anything that fails keeps the row whole. The pieces replace the row (same article,
stance, speaker, evidence, time, context role) and go through matching like any fact, so the shared part
becomes one statement with every outlet that reported it, with its colour decided by the usual rules.

A row is asked about once (`rel.split`: "whole" or "piece"). Analysis tier ("light"): on the reading tier the
night's refusals left most rows unasked (Oct 9 2026).
"""
from __future__ import annotations

import logging
import re

from .db import Store, claims, delete, insert, select, update
from .router import Router

log = logging.getLogger(__name__)

MAX_PIECES = 4      # owner: up to three is good, four at most
BATCH = 10
MIN_WORDS = 14      # a short sentence is one fact
LIST_OVERLAP = 0.6  # two pieces sharing this share of their root words: a list split apart, not two facts


def _names(text: str) -> set[str]:
    """Capitalised words, not at a sentence start (a piece starts sentences the original did not)."""
    out = set()
    for m in re.finditer(r"\b[A-Z][\w'.-]*", text):
        before = text[:m.start()].rstrip()
        if before and before[-1] not in ".!?:\"“":
            out.add(m.group(0).lower().rstrip(".'"))
    return out


def _caps(text: str) -> set[str]:
    return {w.lower().rstrip(".'") for w in re.findall(r"\b[A-Z][\w'.-]*", text)}


NEG = re.compile(r"(?i)\b(not|no|never|neither|nor|without|n't)\b")
SPEECH = re.compile(r"(?i)\b(said|says|stated|told|claimed|claims|alleged|alleges|accused|denied|added|noted|"
                    r"announced|according to|warned|asserted|maintained)\b")


def why_not(original: str, pieces: list[str]) -> str | None:
    """None when the pieces are a faithful split, else the rule that refused it (stored, E17)."""
    from .frames import numbers, words as roots
    if not (2 <= len(pieces) <= MAX_PIECES):
        return "count"
    nums = {round(x, 4) for x in numbers(original)}
    caps = _caps(original)
    orig_roots = set(roots(original))
    got_nums, got_names = set(), set()
    for p in pieces:
        if len(p.split()) < 3:
            return "short"
        pn = {round(x, 4) for x in numbers(p)}
        if not pn <= nums:
            return "number_added"                               # a number the original does not have
        if not _names(p) <= caps:
            return "name_added"                               # a name the original does not have
        pr = set(roots(p))
        if pr and len(pr - orig_roots) > max(1, len(pr) // 6):
            return "words_added"                               # words the original does not have
        if NEG.search(p) and not NEG.search(original):
            return "negation_added"                               # a "not" added
        if SPEECH.search(original) and not SPEECH.search(p):
            return "speech_lost"                               # a said thing turned into a fact
        got_nums |= pn
        got_names |= _names(p) | _caps(p)
    if got_nums != nums:
        return "number_lost"                                   # a number lost
    # a figure the original says ONCE may not be handed to two pieces: "about $700 million in its R&D centre,
    # expansion of production capacity and a dedicated entity" says $700 million of the first item only. Split
    # into "$700 million for R&D" / "$700 million for expansion", the same amount became two amounts
    # (Oct 13 2026, Hyundai story). Both pieces carrying it is a list pulled apart: the row stays whole.
    from collections import Counter
    orig_count = Counter(round(x, 4) for x in numbers(original))
    piece_count = Counter()
    for p in pieces:
        piece_count.update({round(x, 4) for x in numbers(p)})
    if any(piece_count[v] > orig_count[v] for v in piece_count):
        return "number_shared"
    # a list split into near-identical sentences ("higher EMIs for home loans" / "... for car loans" / "... for
    # personal loans", story 13970) is one fact with a list, not separate facts: pieces of a real compound say
    # different things, so two pieces sharing most of their words means the split is wrong
    rs = [set(roots(p)) for p in pieces]
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            if rs[i] and rs[j] and len(rs[i] & rs[j]) / len(rs[i] | rs[j]) >= LIST_OVERLAP:
                return "list"
    if not _names(original) <= got_names:
        return "name_lost"                                   # a name lost
    if NEG.search(original) and not any(NEG.search(p) for p in pieces):
        return "negation_lost"                                   # a "not" lost
    missing = _uncovered(original, pieces)
    if missing:
        return "words_lost"                              # E16: a content word of the original in no piece
    return None


def _pieces_ok(original: str, pieces: list[str]) -> bool:
    return why_not(original, pieces) is None


JOIN = {"and", "but", "which", "who", "whom", "whose", "that", "while", "also", "as", "with", "after", "before", "when", "where",
        "then", "however", "although", "though", "whereas", "because", "since", "so", "yet", "while"}


def _uncovered(original: str, pieces: list[str]) -> set[str]:
    """E16: root words of the original that are neither join words, stop words nor in any piece. The pieces' roots are the
    evidence; a piece that dropped a content word of its source has lost part of the fact."""
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    from .frames import words as roots
    have = set()
    for p in pieces:
        have |= set(roots(p))
    out = set()
    for tok in re.findall(r"[A-Za-z][A-Za-z'-]+", original):
        t = tok.lower()
        if t in JOIN or t in ENGLISH_STOP_WORDS or len(t) < 3:
            continue
        for r in roots(tok):
            if r not in have:
                out.add(r)
    return out


def split_story(store: Store, router: Router | None, story_id: int) -> dict:
    """Compound fact rows of the story not yet looked at are split; {asked, split, pieces}.
    The clauses come from a dependency parse (nlp.clauses), not a model call; code checks every piece (_pieces_ok) and the
    NLI model confirms the original entails each one (nli.covers). A row that could not be analysed is left unmarked and
    looked at again on a later run."""
    from . import nli, nlp
    stats = {"asked": 0, "split": 0, "pieces": 0}
    outcomes: dict[str, int] = {}                      # E17: why rows stayed whole, counted per story
    rows = store.rows(select(claims).where(claims.c.story_id == story_id, claims.c.kind.in_(("event", "claim"))))
    todo = [r for r in rows if not (r["rel"] or {}).get("split")]
    if not todo:
        return stats
    long_ = [r for r in todo if len((r["text"] or "").split()) >= MIN_WORDS]
    for r in todo:
        if r not in long_:
            _mark(store, r, "whole:single")
            outcomes["whole:single"] = outcomes.get("whole:single", 0) + 1
    if not long_ or not nlp.available():
        _dossier(store, story_id, outcomes)
        return stats
    for r in long_:
        stats["asked"] += 1
        facts = nlp.clauses(r["text"])
        why = "no_clauses" if not facts else why_not(r["text"], facts)
        if why:
            _mark(store, r, "whole:" + why)
            outcomes["whole:" + why] = outcomes.get("whole:" + why, 0) + 1
            continue
        sure = nli.covers([(r["text"], f) for f in facts])
        if any(x is None for x in sure):
            continue                                   # the NLI model could not be read: look again later
        if all(sure):
            _replace(store, r, facts)
            stats["split"] += 1
            stats["pieces"] += len(facts)
        else:
            _mark(store, r, "whole:not_entailed")
            outcomes["whole:not_entailed"] = outcomes.get("whole:not_entailed", 0) + 1
    if stats["split"]:
        outcomes["piece"] = stats["split"]
    _dossier(store, story_id, outcomes)
    if stats["split"]:
        log.info("story %s: %d compound statements split into %d facts", story_id, stats["split"], stats["pieces"])
    return stats


def _dossier(store: Store, story_id: int, outcomes: dict) -> None:
    """E17: the story's split outcomes in its dossier (never raises)."""
    if not outcomes:
        return
    try:
        from . import dossier
        dossier.append(store, story_id, "split", dict(outcomes))
    except Exception as e:                              # noqa: BLE001
        log.debug("split dossier: %s", e)


def _mark(store: Store, r: dict, how: str) -> None:
    store.exec(update(claims).where(claims.c.id == r["id"]).values(rel={**(r["rel"] or {}), "split": how}))


def _replace(store: Store, r: dict, facts: list[str]) -> None:
    """The row's pieces take its place: same article, stance, speaker, evidence, time and context role (its
    loaded words, often Hindi, stay with the first piece, counted once); no frame (frames only propose, and the original's frame describes the whole). A relation that named the
    row now names its first piece (the main fact)."""
    rel = {k: v for k, v in (r["rel"] or {}).items() if k not in ("frame", "split")}
    rows = [dict(story_id=r["story_id"], article_id=r["article_id"], local_id=f"{r['local_id']}.{k + 1}"[:20],
                 kind=r["kind"], text=f[:500], stance=r["stance"], attributed_to=r["attributed_to"],
                 evidence=r["evidence"], loaded_words=list(r["loaded_words"] or []) if k == 0 else [],
                 time=r["time"], rel={**rel, "split": "piece", "inherited": ["stance", "attributed_to", "evidence", "time"],
                                      "piece_of": r["local_id"]}) for k, f in enumerate(facts)]
    with store.engine.begin() as c:                      # E18: the row, its pieces and the relation remap together
        c.execute(delete(claims).where(claims.c.id == r["id"]))
        c.execute(insert(claims), rows)
        for x in c.execute(select(claims).where(claims.c.article_id == r["article_id"],
                                                claims.c.kind == "relation")).mappings().all():
            xr = dict(x["rel"] or {})
            changed = False
            for end in ("from", "to"):
                if xr.get(end) == r["local_id"]:
                    xr[end] = rows[0]["local_id"]
                    changed = True
            if changed:
                c.execute(update(claims).where(claims.c.id == x["id"]).values(rel=xr))

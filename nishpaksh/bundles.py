"""Facts two outlets share inside bundled sentences (owner, Oct 26 2026: "what is best for a coherently written article").

The first two live articles had almost no line with two outlets behind it, although eight outlets told the same event: each
outlet's sentence bundles different details (the date, the place, the wind speed), so no whole statement was ever told twice.
The unit of SUPPORT has to be one fact; the unit of WRITING stays the sentence (a writer composing sentences from loose facts
would write choppy prose). So:

  1. `decompose` reads a bundled statement by its dependency parse: the CORE (subject, verb, objects, the speaker of a
     reported clause) and its DETAILS (each adverbial phrase of the verb: "on the Andhra coast", "on Tuesday morning",
     "with winds of 100 km/h"). A statement with fewer than two details is one fact and is left alone.
  2. `split_bundles` (before matching, per story): for two statements of different reports that are close in meaning and that
     code does not already call the same, a detail of one counts as SHARED when the local NLI model says the OTHER statement
     entails core + that detail. Both statements are then cut in two, the shared part and the rest (each keeps the core, so
     each is a full sentence): the shared parts are the same fact in two outlets' words and meet in the normal matching, the
     rest stays as the single-outlet details it is. A split is made only when the two shared parts say each other (NLI both
     ways) and the original entails every piece.
  3. The writer writes the pieces of one bundle back into ONE sentence, each piece its own coloured part (`sentences.bundle_groups`:
     pieces that come from the same report sentence, directly or through a chain of shared facts, are one group). The colours
     are the matching's: nothing here makes a line more certain than the usual gates allow.

No word list: the parse says which phrase is a detail, the NLI model says whether another report says it. A pair or a piece the
model could not read changes nothing; every answer is kept in `stories.analysis.bundle_pairs`, so a pair is read once.
"""
from __future__ import annotations

import collections
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from . import dossier, embed, nli, nlp
from .db import Store, claims, delete, insert, select, stories, update

log = logging.getLogger(__name__)

STATS = collections.Counter()   # a run's counts: stories_read, pairs, unread, split, rows (runs.stats.bundles)
MIN_WORDS = 12          # a shorter sentence is one fact
MIN_PARTNER_WORDS = 5   # the statement it is compared with may be short
MAX_DETAILS = 5         # a sentence with more details than this is not cut (too many pieces to follow)
SIMILARITY = 0.55       # embedding cosine for two statements to be read together (the shared part can be small)
MAX_PAIRS = 40          # pairs read per story and run, closest first
MAX_REMEMBERED = 300    # answers kept in the story's analysis

CORE_DEPS = {"nsubj", "nsubjpass", "csubj", "csubjpass", "dobj", "obj", "dative", "iobj", "attr", "oprd", "acomp", "ccomp",
             "xcomp", "aux", "auxpass", "neg", "prt", "expl", "agent", "pcomp", "cop"}
DETAIL_DEPS = {"prep", "npadvmod", "advcl", "tmod", "advmod"}
SKIP_DEPS = {"punct", "cc"}


# ------------------------------------------------------------------ decomposing one sentence
@dataclass
class Decomp:
    text: str
    toks: list
    core: set[int]
    details: list[set[int]] = field(default_factory=list)

    def build(self, chosen) -> str:
        """The core with only the chosen details (indexes into `details`), as a sentence."""
        keep = set(self.core)
        for k in chosen:
            keep |= self.details[k]
        return _render(self.text, self.toks, keep)


def _render(text: str, toks: list, keep: set[int]) -> str:
    out, prev = [], None
    for t in sorted((toks[i] for i in keep), key=lambda t: t.i):
        if t.dep in SKIP_DEPS and (prev is None or prev.i + 1 != t.i):
            continue                                    # punctuation that lost its left neighbour
        word = text[t.start:t.end]
        out.append(word if prev is not None and t.start == prev.end else (" " + word if prev is not None else word))
        prev = t
    s = "".join(out).strip().strip(",;:").strip()
    s = re.sub(r"\s+([,.;:!?)])", r"\1", s)
    return (s[:1].upper() + s[1:]).rstrip(".") + "." if s else ""


def _subtree(kids: dict, i: int) -> set[int]:
    out, todo = {i}, [i]
    while todo:
        for c in kids.get(todo.pop(), ()):
            if c not in out:
                out.add(c)
                todo.append(c)
    return out


def decompose(text: str) -> Decomp | None:
    """The core and details of ONE sentence from its dependency parse, or None when it is one fact: fewer than two details,
    a coordinated verb (split.py's clauses), an unclear parse, or too many details."""
    if not text or len(text.split()) < MIN_WORDS:
        return None
    toks = nlp.parse(text)
    if not toks:
        return None
    roots = [t for t in toks if t.dep == "ROOT"]
    if len(roots) != 1:
        return None
    kids: dict[int, list[int]] = {}
    for t in toks:
        if t.head != t.i:
            kids.setdefault(t.head, []).append(t.i)
    root = roots[0]
    verb, prefix = root, set()
    if root.lemma in nlp.SPEECH_LEMMA:                   # "Police said that X ..." : the fact is the reported clause
        rep = next((toks[c] for c in kids.get(root.i, []) if toks[c].dep in ("ccomp", "xcomp")), None)
        if rep is not None:
            verb = rep
            prefix = _subtree(kids, root.i) - _subtree(kids, rep.i)
    if any(toks[c].dep == "conj" and toks[c].pos in ("VERB", "AUX") for c in kids.get(verb.i, [])):
        return None                                      # coordinated verbs: clauses, not details
    core = set(prefix) | {verb.i}
    details: list[set[int]] = []
    for c in kids.get(verb.i, []):
        t = toks[c]
        sub = _subtree(kids, c)
        if t.dep in SKIP_DEPS:
            continue
        if t.dep == "mark" and t.text.lower() == "that":
            continue
        if t.dep == "prep" and t.text.lower() == "according":
            core |= sub                                   # an attribution is part of the core
        elif t.dep in CORE_DEPS:
            core |= sub
        elif t.dep in DETAIL_DEPS:
            if len(sub) == 1 and t.dep == "advmod":
                core |= sub                               # "also", "reportedly": a word, not a detail
            else:
                details.append(sub)
        elif len(sub) == 1:
            core.add(c)
        else:
            return None                                   # a label the reading does not know, with words under it
    if not (2 <= len(details) <= MAX_DETAILS) or not core:
        return None
    return Decomp(text, toks, core, details)


# ------------------------------------------------------------------ what two statements share
def shared_details(dec: Decomp, other: str) -> list[int] | None:
    """Indexes of the details of `dec` that the OTHER statement entails together with the core; None when the model could not
    be read (nothing is decided on a failed read)."""
    pieces = [dec.build([k]) for k in range(len(dec.details))]
    got = nli.covers([(other, p) for p in pieces])
    if any(x is None for x in got):
        return None
    return [k for k, ok in enumerate(got) if ok]


def faithful(original: str, dec: Decomp | None, parts: list[str]) -> str | None:
    """None when the pieces carry the original (every number and name, no figure given to two details, no negation or
    speaker added or lost); else the rule that refused them."""
    from .frames import numbers
    from .split import NEG, _caps, _names
    nums = {round(x, 4) for x in numbers(original)}
    caps = _caps(original)
    core_nums = {round(x, 4) for x in numbers(dec.build([]))} if dec else set()
    got_nums, got_names, counts = set(), set(), {}
    for p in parts:
        pn = {round(x, 4) for x in numbers(p)}
        if not pn <= nums:
            return "number_added"
        if not _names(p) <= caps:
            return "name_added"
        if NEG.search(p) and not NEG.search(original):
            return "negation_added"
        got_nums |= pn
        got_names |= _names(p) | _caps(p)
        for v in pn - core_nums:
            counts[v] = counts.get(v, 0) + 1
    if got_nums != nums:
        return "number_lost"
    if any(c > 1 for c in counts.values()):
        return "number_shared"                            # a detail's figure handed to two pieces
    if not _names(original) <= got_names:
        return "name_lost"
    if NEG.search(original) and not any(NEG.search(p) for p in parts):
        return "negation_lost"
    return None


def _key(a: str, b: str) -> str:
    return hashlib.sha256(json.dumps([a, b]).encode()).hexdigest()[:16]


def examine(a: str, b: str, da: Decomp | None, db: Decomp | None) -> dict | None:
    """What the statements `a` and `b` share: {"a": [shared detail indexes of a], "b": [... of b], "pa": the shared piece of a,
    "ra": its rest, "pb", "rb"} (a side that cannot be cut has None pieces), or {} when there is nothing to cut, None when the
    NLI model could not be read."""
    sa = shared_details(da, b) if da else []
    sb = shared_details(db, a) if db else []
    if sa is None or sb is None:
        return None
    res: dict = {"a": sa, "b": sb}
    # one side whole: its text is the shared fact; the other is cut. Both cut: the shared pieces must say each other.
    if da and not db:
        if not sa or len(sa) == len(da.details):
            return {}
        pa, ra = da.build(sa), da.build([k for k in range(len(da.details)) if k not in sa])
        pb = None
        mine, theirs = pa, b
    elif db and not da:
        if not sb or len(sb) == len(db.details):
            return {}
        pb, rb = db.build(sb), db.build([k for k in range(len(db.details)) if k not in sb])
        pa = None
        mine, theirs = a, pb
    else:
        if not sa or not sb or len(sa) == len(da.details) or len(sb) == len(db.details):
            return {}
        pa, ra = da.build(sa), da.build([k for k in range(len(da.details)) if k not in sa])
        pb, rb = db.build(sb), db.build([k for k in range(len(db.details)) if k not in sb])
        mine, theirs = pa, pb
    same = nli.same([(mine, theirs)])[0]
    if same is None:
        return None
    if not same:
        return {}
    if da and pa:
        why = faithful(a, da, [pa, ra])
        ok = nli.covers([(a, pa), (a, ra)])
        if why or any(x is not True for x in ok):
            return {}
        res.update(pa=pa, ra=ra)
    if db and pb:
        why = faithful(b, db, [pb, rb])
        ok = nli.covers([(b, pb), (b, rb)])
        if why or any(x is not True for x in ok):
            return {}
        res.update(pb=pb, rb=rb)
    return res


# ------------------------------------------------------------------ the pass over a story
def _stamp(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted((r["id"], r["text"]) for r in rows)).encode()).hexdigest()[:16]


def _replace(store: Store, r: dict, shared: str, rest: str) -> None:
    """The row's two pieces take its place (same article, stance, speaker, evidence, time); a relation naming the row now names
    the shared piece. `bundle.root` ties every piece of one report sentence together, through any later cut."""
    rel = {k: v for k, v in (r["rel"] or {}).items() if k not in ("frame", "split")}
    root = (rel.get("bundle") or {}).get("root") or f"{r['article_id']}:{r['local_id']}"
    rows = [dict(story_id=r["story_id"], article_id=r["article_id"], local_id=f"{r['local_id']}.{k + 1}"[:20],
                 kind=r["kind"], text=t[:500], stance=r["stance"], attributed_to=r["attributed_to"],
                 evidence=r["evidence"], loaded_words=list(r["loaded_words"] or []) if k == 0 else [], time=r["time"],
                 rel={**rel, "split": "piece", "piece_of": r["local_id"], "bundle": {"root": root, "role": role},
                      "inherited": ["stance", "attributed_to", "evidence", "time"]})
            for k, (t, role) in enumerate(((shared, "shared"), (rest, "rest")))]
    with store.engine.begin() as c:
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


def split_bundles(store: Store, story_id: int) -> dict:
    """Cut the bundled statements of the story that share a detail with another report's statement (see the module text).
    {pairs, split, pieces}; a story whose statements did not change since the last look is not read again."""
    from .relate import relate
    stats = {"pairs": 0, "split": 0, "rows": 0}
    if not (nlp.available() and nli.available()):
        STATS["no_models"] += 1
        return stats
    rows = [r for r in store.rows(select(claims).where(claims.c.story_id == story_id)) if r["kind"] in ("event", "claim")
            and (r["text"] or "").strip()]
    by_text: dict[str, list[dict]] = {}
    for r in rows:
        by_text.setdefault(r["text"], []).append(r)
    texts = sorted(by_text)
    story = store.one(select(stories.c.analysis).where(stories.c.id == story_id))
    analysis = dict((story or {}).get("analysis") or {})
    stamp = _stamp(rows)
    if len(texts) < 2 or analysis.get("bundle_stamp") == stamp:
        return stats
    try:
        sim, _ = embed.similarity(texts)
    except Exception as e:  # noqa: BLE001
        log.debug("bundles: no similarity: %s", e)
        return stats
    seen = dict(analysis.get("bundle_pairs") or {})
    arts = {t: {r["article_id"] for r in by_text[t]} for t in texts}
    words = {t: len(t.split()) for t in texts}
    cand = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if sim[i, j] < SIMILARITY or min(words[a], words[b]) < MIN_PARTNER_WORDS or max(words[a], words[b]) < MIN_WORDS:
                continue
            if arts[a] == arts[b] and len(arts[a]) == 1:
                continue                                     # both from one report: not two outlets
            cand.append((float(sim[i, j]), a, b))
    cand.sort(reverse=True)
    claimed: set[str] = set()
    unread = 0
    plan: list[tuple[str, str | None, str | None, str, str | None, str | None]] = []
    for _s, a, b in cand[:MAX_PAIRS * 3]:
        if len(plan) >= MAX_PAIRS or a in claimed or b in claimed:
            continue
        if relate(a, b) in ("same", "a_covers_b", "b_covers_a"):
            continue                                         # the usual matching folds or merges these
        k = _key(a, b)
        stats["pairs"] += 1
        if k not in seen:
            res = examine(a, b, decompose(a), decompose(b))
            if res is None:
                unread += 1                                  # could not be read: ask again next run
                continue
            seen[k] = {x: v for x, v in res.items() if x in ("pa", "ra", "pb", "rb")}
        res = seen[k]
        if res.get("pa") or res.get("pb"):
            plan.append((a, res.get("pa"), res.get("ra"), b, res.get("pb"), res.get("rb")))
            claimed |= {a, b}
    for a, pa, ra, b, pb, rb in plan:
        for text, shared, rest in ((a, pa, ra), (b, pb, rb)):
            if not shared or not rest:
                continue
            for r in by_text[text]:
                _replace(store, r, shared, rest)
                stats["rows"] += 1
            stats["split"] += 1
    STATS.update(stories_read=1, pairs=stats["pairs"], unread=unread, split=stats["split"], rows=stats["rows"])
    keep = dict(list(seen.items())[-MAX_REMEMBERED:])
    fresh = store.one(select(stories.c.analysis).where(stories.c.id == story_id))
    whole = dict((fresh or {}).get("analysis") or {})
    whole.update(bundle_pairs=keep, bundle_stamp=stamp if not stats["split"] and not unread else None)
    store.exec(update(stories).where(stories.c.id == story_id).values(analysis=whole))
    try:
        dossier.append(store, story_id, "bundles", dict(stats))
    except Exception as e:  # noqa: BLE001
        log.debug("bundles dossier: %s", e)
    if stats["split"]:
        log.info("story %s: %d bundled statements cut at what other reports share (%d rows)", story_id, stats["split"], stats["rows"])
    return stats

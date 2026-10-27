"""Tidy a story's statements before verdicts and writing: one cheap model call per story, only
when its statements changed.

  same       statements that state the same fact (paraphrases, Hindi/English, spelling variants)
             are merged, so the essay says each fact once
  conflicts  statements that cannot both be true (40 vs 50 people questioned) are marked as
             contradicting, so they show as "sources disagree"
  names      one spelling per name (Doolla / Dulla / Dula)
  speaker    who makes each allegation, claim, demand or denial, so the essay pins it on them

Guards, because a wrong merge hides a disagreement: two statements whose numbers differ are never
merged (they are marked as conflicting instead), and nothing is merged with a statement it
conflicts with.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

from .db import Store, articles, canonical, claims, select, stories, update
from . import heavy
from .match import _add_conflict, _merge
from .router import QuotaExhausted, Router

log = logging.getLogger(__name__)

PROMPT = """Below are statements extracted from several news reports about ONE story. Each line:
id | statement | who the reports attribute it to (as they wrote it; "article" = the outlet itself).

{lines}

Do seven things:
1. "same": groups of ids that state the same fact, even if worded differently, in another language,
   with names spelled differently, or told from the other side ("X filed a complaint" / "police received
   a complaint from X"). Do NOT group statements that differ in any number, date, place
   or person, or where one adds an important new fact.
2. "conflicts": pairs of ids that cannot both be true AS FACTS (for example different numbers, times or
   places for the same thing, or one says something happened and the other says it did not), each with
   the two incompatible values: [id, id, "40 people vs 50 people"]. If you cannot name two values that
   cannot both be true, it is not a conflict. A named party's answer to an allegation or finding is NOT
   a conflict (see 5). Statements that agree are never a conflict, however differently worded.
3. "names": SPELLING variants of the same name mapped to ONE spelling (use the most common one),
   e.g. {{"Dulla": "Doolla", "Dula": "Doolla"}}. Only different spellings or transliterations of the SAME
   name. Never map an alias, a nickname, a title or a different name of the same person to another
   (e.g. "Deepak Kumar" and "Mohammad Deepak" are two names, not two spellings: leave them).
4. "speaker": for each statement that is an allegation, accusation, claim, demand, denial or
   opinion made by a person or body, who makes it, in plain English ("Sahil's parents", "Professor
   Doolla", "Mumbai Police"). Leave out statements that are simply reported events.
5. "responses": pairs [first, second] where the second is a named person's or body's answer, rebuttal
   or denial of the first (e.g. "an analyst declared the sample unsafe" / "the company says the product
   is safe"). Both can be true as reports: one records a finding, the other a party's position.
6. "role": for each statement that is NOT about the story's main event, what it is: "background"
   (an earlier event that led to this one), "related" (a separate event the reports connect to this
   one), "explanation" (what a rule, term or finding means) or "next" (what happens next). Leave out
   statements about the main event. Also "related_event": for each "related" statement, a short
   name of that separate event with its date if known.
7. "name_conflicts": groups of ids where the reports name a DIFFERENT person or organisation for the
   same role in the same fact (e.g. one says company A's licence was suspended, another company B's),
   with the names: {{"ids": [5, 9], "names": ["Company A", "Company B"]}}. Not spelling variants.

Reply with JSON only:
{{"same": [[1, 4]], "conflicts": [[2, 7, "40 people vs 50 people"]], "names": {{"Dulla": "Doolla"}}, "speaker": {{"3": "Sahil's parents"}},
 "responses": [[8, 9]], "role": {{"11": "related"}}, "related_event": {{"11": "FSSAI finding on Nestle whitener, 4 October"}},
 "name_conflicts": [{{"ids": [5, 9], "names": ["Company A", "Company B"]}}]}}"""

ROLES = {"background", "related", "explanation", "reaction", "next"}
SOFT_SIMILARITY = 0.70    # sentence-embedding cosine for a "different by words only" pair to be read by the model
SOFT_MAX = 150            # such pairs a consolidation reads (closest first); the local reader costs no quota
SAME_ASK_MAX = 400        # questions per consolidation (the local reader costs no quota), likeliest first; pairs left over count as unanswered
CONSOLIDATE_VERSION = 11  # part of the cache key: stories are consolidated again when the task changes
                          # (9, Oct 8 2026: paraphrases proposed by topic, dupes.py)
                          # (10, Oct 9 2026: the review's results had been wiped by perspectives.py; every
                          # story is reviewed again so covered lines, updates and doubtful disputes exist)
                          # (11, Oct 9 2026: fact groups need the first answers recorded)



def _hash(rows: list[dict]) -> str:
    key = [CONSOLIDATE_VERSION, sorted((r["id"], r["text"]) for r in rows)]
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]


def is_spelling_variant(a: str, b: str) -> bool:
    """Doolla / Dulla / Dula, Shireesh / Shirish: yes. Deepak Kumar / Mohammad Deepak (an alias), or
    Kumar / Mohammad Deepak: no. Replacing an alias with another name rewrote "X, also known as Y" into
    "Y, also known as Y" on a real page, so only near-identical strings with the same number of words
    are accepted."""
    from difflib import SequenceMatcher
    a, b = a.strip().lower(), b.strip().lower()
    if a == b or len(a.split()) != len(b.split()):
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.6 and a[0] == b[0]


ALIAS = re.compile(r"(?i)\b(?:alias|urf|also known as|a\.?k\.?a\.?|also called|known as|or)\b|[(/]|उर्फ")


def named_together(names: list[str], texts: list[str | None]) -> bool:
    from .nameconflict import named_together as nt
    return nt(names, texts)


def _apply_names(text: str, names: dict[str, str]) -> str:
    for variant, canon in names.items():
        if len(variant) >= 3 and variant != canon:
            text = re.sub(rf"(?<!\w){re.escape(variant)}(?!\w)", canon, text)
    return text


def _repair_aliases(store: Store, story_id: int, analysis: dict) -> None:
    """Undo name mappings an earlier version accepted that were aliases, not spellings: restore each
    statement's text from the words of the report it came from, and consolidate again."""
    bad = {k: v for k, v in (analysis.get("names") or {}).items() if not is_spelling_variant(k, v)}
    if not bad:
        return
    for c in store.rows(select(canonical.c.id, canonical.c.text).where(canonical.c.story_id == story_id)):
        if not c["text"] or not any(v in c["text"] for v in bad.values()):
            continue
        first = store.one(select(claims.c.text).where(claims.c.canonical_id == c["id"]).order_by(claims.c.id))
        if first and first["text"] and first["text"] != c["text"]:
            store.exec(update(canonical).where(canonical.c.id == c["id"]).values(text=first["text"]))
    analysis["names"] = {k: v for k, v in (analysis.get("names") or {}).items() if k not in bad}
    analysis.pop("consolidated", None)
    log.info("consolidate story %s: undid %d alias mappings", story_id, len(bad))


def _soft_pairs(texts, times, prof, code_same_set, ask_pairs, ask_cover):
    """Add the embedding-close pairs that only names or words kept apart to the same-fact and covers questions."""
    from . import embed
    from .relate import relate, soft_candidate
    ids = sorted(texts)
    if len(ids) < 2:
        return ask_pairs, ask_cover
    try:
        sim, _thr = embed.similarity([texts[i] for i in ids])
    except Exception:  # noqa: BLE001
        return ask_pairs, ask_cover
    known = {tuple(sorted(p)) for p in ask_pairs} | {tuple(sorted(p)) for p in ask_cover} | set(code_same_set)
    cand = sorted(((float(sim[x, y]), ids[x], ids[y]) for x in range(len(ids)) for y in range(x + 1, len(ids))
                   if sim[x, y] >= SOFT_SIMILARITY), reverse=True)
    added = 0
    for _s, a, b in cand:
        if added >= SOFT_MAX:
            break
        if (a, b) in known or relate(texts[a], texts[b], times.get(a), times.get(b), prof[a], prof[b]) != "different":
            continue
        if not soft_candidate(texts[a], texts[b], times.get(a), times.get(b), prof[a], prof[b]):
            continue
        ask_pairs = list(ask_pairs) + [(a, b)]
        ask_cover = list(ask_cover) + [(a, b), (b, a)]
        added += 1
    return ask_pairs, ask_cover

def is_current(store: Store, story_id: int) -> bool:
    """True when the review of this story needs no work now (a call to consolidate_story would return at once)."""
    story = store.one(select(stories.c.analysis).where(stories.c.id == story_id))
    if not story:
        return True
    rows = [r for r in store.rows(select(canonical.c.id, canonical.c.text, canonical.c.kind)
                                  .where(canonical.c.story_id == story_id)) if r["kind"] != "relation" and r["text"]]
    return len(rows) < 2 or (story["analysis"] or {}).get("consolidated") == _hash(rows)


def _ask_in_batches(fn, router, todo, texts, until, size=50):
    """Ask `fn` (same_facts / covers_facts) in batches; after `until` (a clock time) the rest is left unasked (None =
    could not ask, never an answer), so it counts as unanswered and is asked again next time."""
    import time
    out: list = []
    firsts: dict[int, bool] = {}
    for i in range(0, len(todo), size):
        if until and time.time() > until:
            out += [None] * (len(todo) - i)
            break
        part, f = todo[i:i + size], {}
        out += list(fn(router, [(texts[a], texts[b]) for a, b in part], f))
        firsts.update({i + k: v for k, v in f.items()})
    return out, firsts


def consolidate_story(store: Store, router: Router | None, story_id: int, max_statements: int = 90,
                      until: float | None = None) -> dict:
    story = store.one(select(stories.c.id, stories.c.analysis).where(stories.c.id == story_id))
    if not story or router is None:
        return {}
    analysis = dict(story["analysis"] or {})
    _repair_aliases(store, story_id, analysis)
    rows = [r for r in store.rows(select(canonical.c.id, canonical.c.text, canonical.c.kind, canonical.c.conflicts,
                                         canonical.c.rel)
                                  .where(canonical.c.story_id == story_id)) if r["kind"] != "relation" and r["text"]]
    if len(rows) < 2 or analysis.get("consolidated") == _hash(rows):
        return {}
    attrib: dict[int, set[str]] = {}
    support: dict[int, int] = {}
    for c in store.rows(select(claims.c.canonical_id, claims.c.attributed_to, claims.c.article_id)
                        .where(claims.c.story_id == story_id, claims.c.canonical_id.is_not(None))):
        attrib.setdefault(c["canonical_id"], set()).add(c["attributed_to"] or "article")
        support[c["canonical_id"]] = support.get(c["canonical_id"], 0) + 1
    rows.sort(key=lambda r: -support.get(r["id"], 0))
    # S7: the model reads the best-supported `max_statements` lines (its prompt has a size); the pair finding below (code
    # with blocking, then the NLI questions) covers EVERY statement of the story, not only those
    by_id = {r["id"]: r for r in rows}
    prompt_ids = {r["id"] for r in rows[:max_statements]}
    lines = "\n".join(f'{r["id"]} | {r["text"]} | {", ".join(sorted(attrib.get(r["id"], {"article"})))[:120]}'
                      for r in rows[:max_statements])
    try:
        res = router.call("light", PROMPT.format(lines=lines), json_out=True, max_output_tokens=3000)
        data = res.data if isinstance(res.data, dict) else {}
    except QuotaExhausted:
        return {}
    except Exception as e:  # noqa: BLE001
        log.warning("consolidate story %s failed: %s", story_id, str(e)[:200])
        return {}

    def ids(xs):
        out = []
        for x in xs or []:
            try:
                x = int(x)
            except (TypeError, ValueError):
                continue
            if x in prompt_ids:
                out.append(x)
        return out

    from .match import _remove_conflict
    responses = [tuple(p) for p in (ids(p) for p in data.get("responses") or []) if len(p) == 2 and p[0] != p[1]]
    response_pairs = {tuple(sorted(p)) for p in responses}
    # Possible disputes, from every source, are only PROPOSALS: the consolidation model's "conflicts",
    # disputes marked earlier, and the frames. One gate decides them all (disputes.py, owner Oct 7 2026).
    proposed: set[tuple[int, int]] = set()
    for c in data.get("conflicts") or []:
        if isinstance(c, list) and len(c) >= 2:
            pair = ids(c[:2])
            if len(pair) == 2 and pair[0] != pair[1]:
                proposed.add(tuple(sorted(pair)))
    earlier = {tuple(sorted((r["id"], o))) for r in rows for o in r["conflicts"] or [] if o in by_id}
    proposed |= earlier
    same_groups = [[x for x in dict.fromkeys(ids(g))] for g in data.get("same") or []]
    # the frames only propose (same facts and disputes); they decide nothing
    from .frames import compare as frame_compare
    from .match import frame_of
    fr = {r["id"]: frame_of(r) for r in rows}
    with_frames = [r["id"] for r in rows if fr[r["id"]][0]]
    by_frame: dict[tuple[int, int], str] = {}
    for i, a in enumerate(with_frames):
        for b in with_frames[i + 1:]:
            by_frame[(a, b) if a < b else (b, a)] = frame_compare(fr[a][0], fr[b][0], fr[a][1], fr[b][1])
    proposed |= {p for p, v in by_frame.items() if v == "conflict"}
    # ONE structure decides the same fact (relate.py, owner Oct 7 2026): the words first, by code; a
    # model asked twice only about the middle cases; the consolidation model's "same" groups and the
    # frames' "same" are proposals, checked the same way. The frames no longer veto anything here.
    from .match import covers_facts, same_facts
    from .relate import Profile, group, nums_within, numbers_close, relate, resolve_covered
    key = lambda p: hashlib.sha256(json.dumps([by_id[p[0]]["text"], by_id[p[1]]["text"]]).encode()).hexdigest()[:16]  # noqa: E731
    texts = {i: by_id[i]["text"] for i in by_id}
    times = {i: fr[i][1] for i in by_id}
    prof = {i: Profile(t) for i, t in texts.items()}
    code_same, covered, ask_pairs, ask_cover = group(texts, times)
    proposals = {tuple(sorted((x, y))) for g in same_groups for i, x in enumerate(g) for y in g[i + 1:] if x != y}
    proposals |= {p for p, v in by_frame.items() if v == "same"}
    # the same fact in other words, found topic by topic (dupes.py, Oct 8 2026, story 13970): proposals only,
    # decided below like every other proposal; a "covers" proposal must keep the short line's numbers before
    # the twice-asked question
    from .dupes import propose
    dupe_checks = dict(analysis.get("dupe_checks") or {})
    d_same, d_cover = propose(router, texts, dupe_checks)
    proposals |= d_same
    for big, small in d_cover:
        if nums_within(prof[small], prof[big]):
            ask_cover.append((big, small))
    ask_cover = list(dict.fromkeys(ask_cover))
    code_same_set = {tuple(sorted(p)) for p in code_same}
    for a, b in sorted(proposals - code_same_set):
        r = relate(texts[a], texts[b], times[a], times[b], prof[a], prof[b])
        # a model or the frames said "same": checked by the twice-asked question, unless the words plainly
        # differ (one negated, or numbers that do not agree even after rounding). A pair the topic step
        # proposed is asked even with a "no" on one side (owner, Oct 8 2026: "rate cuts were off the table" /
        # "there is no option for rate cuts" mean the same); the twice-asked question decides, its examples
        # holding the trap ("arrested him" / "did not arrest him" -> different). Numbers must still agree.
        neg_ok = prof[a].neg == prof[b].neg or (a, b) in d_same
        if r in ("same", "ask") or (neg_ok and numbers_close(prof[a], prof[b])):
            ask_pairs.append((a, b))
    # pairs the word rules called "different" only through names or words, but the sentence embedding puts side by side:
    # the local reader decides (relate.soft_candidate keeps every veto about a fact: not, figures, dates, clock times)
    ask_pairs, ask_cover = _soft_pairs(texts, times, prof, code_same_set, ask_pairs, ask_cover)
    from . import redundancy
    ask_pairs += redundancy.number_pairs(prof)        # one card per subject and measure: offered to the question, decides nothing
    ask_pairs = list(dict.fromkeys(tuple(sorted(p)) for p in ask_pairs if tuple(sorted(p)) not in code_same_set))
    same_checks = dict(analysis.get("same_checks") or {})
    from . import dupescore
    pending = dupescore.order([p for p in ask_pairs if key(p) not in same_checks], prof, texts, times)
    todo = pending[:SAME_ASK_MAX]
    firsts: dict[int, bool] = {}
    unanswered = len(pending) - len(todo)        # offered but not asked (over the cap) is unanswered too, never silent
    labelled: list[tuple[str, str, bool]] = []
    answers, firsts = _ask_in_batches(same_facts, router, todo, texts, until)
    for n, (p, ok) in enumerate(zip(todo, answers)):
        if ok is None:                    # not answered (quota, error): remember nothing, ask again next time (F123)
            unanswered += 1
            continue
        labelled.append((texts[p[0]], texts[p[1]], bool(ok)))
        same_checks[key(p)] = ok
        same_checks["f" + key(p)] = bool(firsts.get(n))
    dupescore.record(store, labelled)
    ckey = lambda p: "c" + key(p)  # noqa: E731
    pending = dupescore.order([p for p in ask_cover if ckey(p) not in same_checks], prof, texts, times)
    todo = pending[:SAME_ASK_MAX]
    unanswered += len(pending) - len(todo)
    firsts = {}
    answers, firsts = _ask_in_batches(covers_facts, router, todo, texts, until)
    for n, (p, ok) in enumerate(zip(todo, answers)):
        if ok is None:
            unanswered += 1
            continue
        same_checks[ckey(p)] = ok
        same_checks["f" + ckey(p)] = bool(firsts.get(n))
    if unanswered:
        log.warning("consolidate story %s: %d same/cover questions not answered (asked again next time)",
                    story_id, unanswered)
    for big, small in ask_cover:
        if same_checks.get(ckey((big, small))):
            covered.setdefault(small, big)
    # FACT GROUPS, the writing layer (owner, Oct 9 2026: "it's fine if we leave out lines from outlets if they
    # have already been covered from other outlets and just give their number"): a line whose fact another
    # line already tells is not written again; its outlets' numbers go on that line's sentence, which keeps
    # its own colour (compose.fold_covered), so the article counts facts, not statements. Colours never
    # change here, so ONE model "yes" is enough, checked by code: every number and name of the left-out line
    # is in the line that tells it. (Merging, which does change colours, still needs two.)
    def tells(lead: int, member: int) -> bool:
        pl, pm = prof[lead], prof[member]
        nums_ok = nums_within(pm, pl)
        from .relate import core_names
        return nums_ok and core_names(pm) <= (core_names(pl) | pl.roots | pl.names)
    for big, small in ask_cover:
        if small not in covered and same_checks.get("f" + ckey((big, small))) and tells(big, small):
            covered[small] = big
    for a, b in ask_pairs:
        if same_checks.get(key((a, b))) or not same_checks.get("f" + key((a, b))):
            continue                          # merged for support already, or the model said different
        lead, member = sorted((a, b), key=lambda x: (-support.get(x, 0), -len(texts[x]), x))
        if member not in covered and tells(lead, member):
            covered[member] = lead
    same_groups = [list(p) for p in code_same_set] + [list(p) for p in ask_pairs if same_checks.get(key(p))]
    # disputes: one gate (code finds the same question with a different answer; figures that changed
    # over time are updates; the model asked "can both be true?" twice decides the rest)
    from .disputes import judge
    rtimes: dict[int, list] = {}
    for r in store.rows(select(claims.c.canonical_id, articles.c.published_at, articles.c.fetched_at)
                        .select_from(claims.join(articles, articles.c.id == claims.c.article_id))
                        .where(claims.c.story_id == story_id, claims.c.canonical_id.is_not(None))):
        t = r["published_at"] or r["fetched_at"]
        if t is not None:
            rtimes.setdefault(r["canonical_id"], []).append(t)
    checks = dict(analysis.get("conflict_checks") or {})     # answers kept per (ordered) pair of texts
    if analysis.get("conflict_checks_v") != 2:
        # before Oct 2026 a failed call was stored as "unsure" (F94): forget those once, real ones come back
        checks = {k: v for k, v in checks.items() if v != "unsure"}
    conflicts, doubtful, updates = judge(router, texts, rtimes, proposed, response_pairs, checks)
    for pair in earlier - conflicts:
        _remove_conflict(store, *pair)       # not confirmed by the gate: taken back
    keep_apart = conflicts | {tuple(sorted(p)) for p in updates.items()}
    # two sides of a dispute, or an old and a new figure, are both written: neither is folded into the other
    covered = {s_: b_ for s_, b_ in covered.items() if tuple(sorted((s_, b_))) not in keep_apart}
    merged = 0
    gone: set[int] = set()
    merged_into: dict[int, int] = {}
    variants: dict[str, list[str]] = {}
    # clusters of the "same" pairs with cannot-link constraints (redundancy.py): a dispute, an updated figure or a pair the
    # question answered "different" is never put into one cluster by the pairs around it
    cannot = set(keep_apart) | {tuple(sorted(p)) for p in ask_pairs if same_checks.get(key(p)) is False}
    clusters, refused = redundancy.constrained([tuple(g) for g in same_groups], cannot)
    for g in clusters:
        dst, var = redundancy.survivor(g, support, {x: by_id[x]["text"] for x in g})
        if var:
            variants[str(dst)] = [t for v in var.values() for t in v][:4]
        for src in g:
            if src == dst:
                continue
            _merge(store, src, dst)
            merged_into[src] = dst
            gone.add(src)
            merged += 1
    try:                                      # E5: what this review decided, for the single audit
        from . import dossier
        dossier.append(store, story_id, "consolidate", {
            "statements": len(rows), "asked_same": len(ask_pairs), "asked_cover": len(ask_cover),
            "unanswered": unanswered, "merged": merged, "clusters": len(clusters), "unions_refused": refused,
            "covered": len(covered), "disputes": len(conflicts), "updates": len(updates), "variants": len(variants)})
    except Exception:  # noqa: BLE001
        pass
    added = 0
    for a, b in conflicts:
        if a in gone or b in gone:
            continue
        if b not in (by_id[a]["conflicts"] or []):
            _add_conflict(store, a, b)
            added += 1

    names = {str(k).strip(): str(v).strip() for k, v in (data.get("names") or {}).items()
             if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip() and is_spelling_variant(k, v)}
    if names:
        for r in rows:
            if r["id"] in gone:
                continue
            new = _apply_names(r["text"], names)
            if new != r["text"]:
                store.exec(update(canonical).where(canonical.c.id == r["id"]).values(text=new))
    speakers = dict(analysis.get("speakers") or {})
    for k, v in (data.get("speaker") or {}).items():
        try:
            k = int(k)
        except (TypeError, ValueError):
            continue
        if k in by_id and k not in gone and isinstance(v, str) and v.strip():
            from . import speakers as _speakers
            ok = _speakers.verify(v.strip(), attrib.get(k, ()), by_id[k]["text"])      # verified, never typed (speakers.py)
            if ok:
                speakers[str(k)] = _apply_names(ok, names)[:80]
    alive = lambda x: x not in gone   # noqa: E731
    roles = {str(k): v for k, v in (analysis.get("roles") or {}).items()}
    for k, v in (data.get("role") or {}).items():
        k = ids([k])
        if k and alive(k[0]) and v in ROLES:
            roles[str(k[0])] = v
    related = dict(analysis.get("related_event") or {})
    for k, v in (data.get("related_event") or {}).items():
        k = ids([k])
        if k and isinstance(v, str) and v.strip():
            related[str(k[0])] = v.strip()[:160]
    prev_resp = {tuple(p) for p in analysis.get("responses") or []}
    all_resp = sorted({p for p in prev_resp | set(responses) if alive(p[0]) and alive(p[1])})
    name_conf = dict(analysis.get("name_conflicts") or {})
    for g in data.get("name_conflicts") or []:
        if not isinstance(g, dict):
            continue
        names_g = [str(n).strip() for n in g.get("names") or [] if str(n).strip()]
        if len(set(n.lower() for n in names_g)) < 2:
            continue
        for x in ids(g.get("ids")):
            if alive(x):
                name_conf[str(x)] = names_g[:4]
    # checked by code, every time (earlier entries too): two names that appear together in one statement
    # or one report, not joined as aliases, are two people, not one person named two ways (Oct 7 2026,
    # story 11569: "Ritesh Kumar Singh is accused of assisting Abhishek Kumar Singh", yet the page said
    # "Ritesh Kumar Singh, named in reports as Abhishek Kumar Singh")
    if name_conf:
        texts = [r["text"] for r in store.rows(select(canonical.c.text).where(canonical.c.story_id == story_id))]
        texts += [r["text"] for r in heavy.fill(store, store.rows(select(articles.c.id, *heavy.columns(store, "text"))
                                                                   .where(articles.c.story_id == story_id)), "text")]
        from .nameconflict import classify
        name_conf = {k: v for k, v in name_conf.items() if classify(v, texts) == "disagreement"}
    after = [r for r in store.rows(select(canonical.c.id, canonical.c.text, canonical.c.kind)
                                   .where(canonical.c.story_id == story_id)) if r["kind"] != "relation" and r["text"]]
    analysis.update(consolidated=_hash(after) if not unanswered else None, unanswered_asks=unanswered, speakers=speakers,
                    names={**(analysis.get("names") or {}), **names},
                    roles=roles, related_event=related, responses=[list(p) for p in all_resp],
                    name_conflicts=name_conf, conflict_checks=dict(list(checks.items())[-400:]), conflict_checks_v=2,
                    same_checks=dict(list(same_checks.items())[-400:]),
                    dupe_checks=dict(list(dupe_checks.items())[-60:]),
                    variants=variants,
                    # a line another line says in full, with more: not written on its own (relate.py)
                    covered={str(k): v for k, v in resolve_covered(
                        {merged_into.get(k, k): merged_into.get(v, v) for k, v in covered.items()}).items()
                        if alive(k) and alive(v)},
                    # a possible contradiction the check could not settle: not shown as a dispute, but
                    # neither statement can be established while it stands (verify.base_verdicts)
                    doubtful_conflicts=sorted(x for x in doubtful if alive(x)),
                    # an older figure and the newer one that replaced it (both true when reported)
                    updates={str(merged_into.get(k, k)): merged_into.get(v, v) for k, v in updates.items()
                             if alive(merged_into.get(k, k)) and alive(merged_into.get(v, v))
                             and merged_into.get(k, k) != merged_into.get(v, v)})
    store.exec(update(stories).where(stories.c.id == story_id).values(analysis=analysis))
    log.info("consolidate story %s: %d merged, %d contradictions, %d names", story_id, merged, added, len(names))
    return {"merged": merged, "conflicts": added, "names": len(names)}

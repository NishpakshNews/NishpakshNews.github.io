"""Hypothesis tests, group A: read-only measurements over the stored newsroom (published articles, statements,
analysis, links, diagnostics). No model call, no write, no article bodies (publishers' copyright): counts, shares and
short examples of OUR OWN statements and sentences.

    python -m nishpaksh.tools.hypotheses --days 14 --out report.json --md report.md
    python -m nishpaksh.tools.hypotheses --only H22,H42            # a few tests

Every test is one function registered with @test(ids, title). It returns {"headline": [short lines], "data": {...}}.
One failing test is reported as an error and never stops the others. The numbers MEASURE; they do not decide: each test
states in its docstring what a high or low number would mean for the hypothesis (NOTES.md H-numbers).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import re
import sys
import traceback

REGISTRY: list[tuple[str, str, object]] = []
EXAMPLES = 8


def test(ids: str, title: str):
    def deco(fn):
        REGISTRY.append((ids, title, fn))
        return fn
    return deco


# ------------------------------------------------------------------------------------------------ loading

def _j(v):
    """A JSON column: Postgres hands back objects, SQLite hands back text."""
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def _ids(xs) -> str:
    return ",".join(str(int(x)) for x in sorted(set(xs))) or "-1"


def load(q, days: int = 14, readers_q=None, now: dt.datetime | None = None) -> dict:
    """Everything the tests read, as plain lists and dicts. `q(sql, **params)` -> list of dict rows."""
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cutoff = now - dt.timedelta(days=days)
    d: dict = {"now": now, "days": days, "notes": []}
    pub = q("select story_id, version, updated_at, headline_en, payload_en from published where updated_at >= :c",
            c=cutoff)
    for r in pub:
        r["payload_en"] = _j(r["payload_en"]) or {}
    d["pub"] = pub
    sids = [r["story_id"] for r in pub]
    d["sids"] = set(sids)
    d["stories"] = {r["id"]: _j(r["analysis"]) or {} for r in
                    q(f"select id, analysis from stories where id in ({_ids(sids)})")}
    d["links"] = q(f"select parent_id, child_id, reason from story_links where child_id in ({_ids(sids)})")
    parents = [r["parent_id"] for r in d["links"]]
    d["claims"] = q('select id, story_id, article_id, kind, text, stance, attributed_to, "time", canonical_id '
                    f"from claims where story_id in ({_ids(sids)})")
    d["canon"] = q("select id, story_id, kind, text, rel, conflicts, verdict, detail, origins, checkable "
                   f"from canonical where story_id in ({_ids(sids + parents)})")
    for r in d["canon"]:
        for k in ("rel", "conflicts", "detail", "origins"):
            r[k] = _j(r[k])
    for r in d["claims"]:
        r["time"] = _j(r["time"])
    d["positions"], d["runs"] = [], []
    if readers_q is not None:
        try:
            d["positions"] = readers_q("select id, created_at, report from diagnostics where kind = 'positions' "
                                       "order by id desc limit 120")
            for r in d["positions"]:
                r["report"] = _j(r["report"]) or {}
            d["runs"] = readers_q("select id, started_at, trigger, stats from runs order by id desc limit 300")
            for r in d["runs"]:
                r["stats"] = _j(r["stats"]) or {}
        except Exception as e:  # noqa: BLE001 - the readers' database may be out of reach: those tests say so
            d["notes"].append(f"readers database not read: {type(e).__name__}: {str(e)[:200]}")
    else:
        d["notes"].append("no READERS_DATABASE_URL: diagnostics/runs tests (H80, H87) have no data")
    return d


# ------------------------------------------------------------------------------------------------ helpers

def sentences(p: dict) -> list[dict]:
    nar = p.get("narrative") or {}
    paras = nar.get("paragraphs") or []
    keys = nar.get("section_keys") or []
    aligned = len(keys) == len(paras)
    out = []
    for pi, para in enumerate(paras):
        sec = keys[pi] if aligned and isinstance(keys[pi], str) else None
        for si, s in enumerate(para if isinstance(para, list) else []):
            if isinstance(s, dict) and s.get("text"):
                out.append({"p": pi, "s": si, "section": sec, "text": str(s["text"]),
                            "ids": [x for x in s.get("ids") or [] if isinstance(x, int)]})
    return out


def items(p: dict) -> dict:
    out: dict = {}
    for tier in p.get("timeline") or []:
        for i in tier or []:
            if isinstance(i, dict):
                out[i.get("id")] = i
    for k in ("undated", "established", "contested", "context", "background"):
        for i in p.get(k) or []:
            if isinstance(i, dict):
                out.setdefault(i.get("id"), i)
    return out


def articles(d: dict) -> list[dict]:
    out = []
    for r in d["pub"]:
        p = r["payload_en"]
        sents = sentences(p)
        if not sents:
            continue
        out.append({"story": r["story_id"], "headline": r["headline_en"] or p.get("headline") or "", "p": p,
                    "sents": sents, "items": items(p),
                    "text": " ".join([r["headline_en"] or ""] + [s["text"] for s in sents])})
    return out


def snip(text: str, at: int, width: int = 70) -> str:
    return text[max(0, at - width // 2): at + width // 2].replace("\n", " ")


def share(a: int, b: int) -> float:
    return round(a / b, 3) if b else 0.0


try:
    from ..frames import _stem as _snowball
    STEMMER = "snowball"
except Exception:  # noqa: BLE001 - only where the libraries are missing (a plain sandbox); Actions has them
    _snowball = None
    STEMMER = "crude suffix stripping (snowballstemmer not importable here)"

STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "by", "with", "from", "as", "is", "was",
        "were", "are", "be", "been", "has", "have", "had", "that", "this", "it", "its", "will", "would", "said", "says"}


def _stem(w: str) -> str:
    if _snowball:
        return _snowball(w)
    for suf in ("ings", "ing", "edly", "ed", "es", "ly", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def roots(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def near_pairs(texts: dict, min_share: float = 0.6, min_roots: int = 5) -> list[tuple]:
    r = {i: roots(t) for i, t in texts.items()}
    ids = sorted((i for i in r if len(r[i]) >= min_roots), key=str)
    out = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            j = len(r[a] & r[b]) / len(r[a] | r[b])
            if j >= min_share:
                out.append((a, b, round(j, 2)))
    return sorted(out, key=lambda x: -x[2])


# ------------------------------------------------------------------------------------------------ 0 overview

@test("OVERVIEW", "What the window holds")
def t_overview(d):
    arts = articles(d)
    kinds = collections.Counter(c["kind"] for c in d["canon"])
    verd = collections.Counter(c["verdict"] for c in d["canon"])
    return {"headline": [f"{len(d['pub'])} published stories in the last {d['days']} days; {len(arts)} with a written essay",
                         f"{len(d['claims'])} stored claims, {len(d['canon'])} canonical statements, "
                         f"{len(d['links'])} thread links", f"stemmer used: {STEMMER}"] + d["notes"],
            "data": {"stories": len(d["pub"]), "with_essay": len(arts), "claims": len(d["claims"]),
                     "canonical": len(d["canon"]), "canonical_kinds": dict(kinds), "verdicts": dict(verd),
                     "analysis_rows": len(d["stories"]), "links": len(d["links"]), "positions_rows": len(d["positions"]),
                     "run_rows": len(d["runs"]), "notes": d["notes"]}}


# ------------------------------------------------------------------------------------------------ text hygiene

MOJI = re.compile(r"Ã[^\x00-\x7f]|â€.|Â[ -¿]|�|[A-Za-z]\?(?:ve|s|t|re|ll|d|m)\b")


@test("H22", "Mojibake and typography mix (which layer carries it)")
def t_h22(d):
    """H22/F29: if broken characters are already in the stored CLAIMS, they come in at ingest (requests r.text); if only
    in written sentences, a later layer made them. Also: articles mixing ' and ’ or " and “ ” (T4)."""
    arts = articles(d)
    layers = {"claims": [(c["story_id"], c["text"]) for c in d["claims"]],
              "canonical": [(c["story_id"], c["text"]) for c in d["canon"]],
              "published": [(a["story"], a["text"]) for a in arts]}
    out, ex = {}, {}
    for name, rows in layers.items():
        hits = [(sid, t, m) for sid, t in rows for m in [MOJI.search(t or "")] if m]
        out[name] = {"rows": len(rows), "with_mojibake": len(hits), "stories": len({h[0] for h in hits})}
        ex[name] = [{"story": sid, "text": snip(t, m.start())} for sid, t, m in hits[:EXAMPLES]]
    mix_apos = mix_quote = 0
    mix_ex = []
    for a in arts:
        t = a["text"]
        if re.search(r"(?<=\w)'(?=\w)", t) and "’" in t:
            mix_apos += 1
            mix_ex.append(a["story"])
        if '"' in t and ("“" in t or "”" in t):
            mix_quote += 1
    return {"headline": [f"mojibake rows: claims {out['claims']['with_mojibake']}, canonical "
                         f"{out['canonical']['with_mojibake']}, published {out['published']['with_mojibake']}",
                         f"articles mixing straight and curly apostrophes: {mix_apos} of {len(arts)}; "
                         f"straight and curly double quotes: {mix_quote}"],
            "data": {"layers": out, "examples": ex, "mixed_apostrophe_articles": mix_apos,
                     "mixed_apostrophe_story_ids": mix_ex[:20], "mixed_double_quote_articles": mix_quote}}


@test("H4", "Words in the English article that no statement and no other article uses (romanized Hindi?)")
def t_h4(d):
    """H4: 'feesadi'. A REVIEW LIST, not a count of errors: tokens of 6+ letters in the written article that are in none
    of the story's statements, claims or headline and in no other published article, ranked by how unusual their
    letter triples are (mean log-probability) against the whole corpus (character 3-gram model built from the stored text; no word list)."""
    arts = articles(d)
    by_story_claims = collections.defaultdict(str)
    for c in d["claims"]:
        by_story_claims[c["story_id"]] += " " + (c["text"] or "")
    tri = collections.Counter()
    df = collections.Counter()
    corpus = [a["text"] for a in arts] + list(by_story_claims.values())
    for t in corpus:
        for w in set(re.findall(r"[a-z]{3,}", t.lower())):
            padded = f"^{w}$"
            for i in range(len(padded) - 2):
                tri[padded[i:i + 3]] += 1
    for a in arts:
        for w in set(re.findall(r"[a-z]{6,}", a["text"].lower())):
            df[w] += 1
    total = sum(tri.values()) or 1
    cand = []
    for a in arts:
        known = set(re.findall(r"[a-z]{6,}", " ".join(i.get("text") or "" for i in a["items"].values()).lower()))
        known |= set(re.findall(r"[a-z]{6,}", (by_story_claims.get(a["story"]) or "").lower()))
        known |= set(re.findall(r"[a-z]{6,}", a["headline"].lower()))
        for w in set(re.findall(r"[a-z]{6,}", a["text"].lower())):
            if w in known or df[w] != 1:
                continue
            padded = f"^{w}$"
            lp = [math.log((tri[padded[i:i + 3]] + 1) / total) for i in range(len(padded) - 2)]
            cand.append({"story": a["story"], "token": w, "oddness": round(-sum(lp) / len(lp), 2),
                         "in_claims": w in (by_story_claims.get(a["story"]) or "").lower()})
    cand.sort(key=lambda x: -x["oddness"])
    return {"headline": [f"{len(cand)} writer-introduced single-use tokens; top {min(40, len(cand))} listed for review"],
            "data": {"candidates": len(cand), "review_list": cand[:40]}}


FIG = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?:\s?(?:%|per ?cent|percent|crore|lakh|million|billion|thousand))?", re.I)


def _fig(m: str) -> str:
    m = re.sub(r"[\s,]", "", m.lower())
    return re.sub(r"per ?cent|percent", "%", m)


@test("H18", "Repeated figures across sentences and number cards")
def t_h18(d):
    """H18/F23: one card per figure-claim. Counts, per article, figures (not years, not single digits) that occur in 2+
    sentences of the 'numbers' section and in 3+ sentences anywhere."""
    arts = articles(d)
    a3, anum, rows = 0, 0, []
    secs = collections.Counter()
    for a in arts:
        per, pern = collections.Counter(), collections.Counter()
        for s in a["sents"]:
            secs[s["section"]] += 1
            seen = {f for f in (_fig(m.group()) for m in FIG.finditer(s["text"]))
                    if not re.fullmatch(r"\d", f) and not re.fullmatch(r"(19|20)\d\d", f)}
            for f in seen:
                per[f] += 1
                if s["section"] == "numbers":
                    pern[f] += 1
        rep3 = {f: n for f, n in per.items() if n >= 3}
        repn = {f: n for f, n in pern.items() if n >= 2}
        a3 += bool(rep3)
        anum += bool(repn)
        if rep3 or repn:
            rows.append({"story": a["story"], "in_3plus_sentences": rep3, "in_2plus_number_cards": repn})
    return {"headline": [f"articles with a figure in 3+ sentences: {a3} of {len(arts)} ({share(a3, len(arts))})",
                         f"articles with a figure in 2+ number-section sentences: {anum}",
                         f"sentences by section: {dict(secs)}"],
            "data": {"articles": len(arts), "figure_3plus": a3, "figure_2plus_numbers_section": anum,
                     "examples": rows[:EXAMPLES]}}


# ------------------------------------------------------------------------------------------------ repeats and merging

@test("H3/H10", "Repeated sentences inside one article (baseline for the repeat complaint)")
def t_h3(d):
    """H3/H10/H27/H28 baseline: sentence pairs in one article sharing >=60% of root words. 'shared_ids' = the same
    statement was written twice; 'cross_section' = Background vs What happened style repeats (never compared, H10)."""
    arts = articles(d)
    kinds = collections.Counter()
    affected, ex = 0, []
    for a in arts:
        texts = {n: s["text"] for n, s in enumerate(a["sents"])}
        pairs = near_pairs(texts)
        if pairs:
            affected += 1
        for x, y, j in pairs:
            sx, sy = a["sents"][x], a["sents"][y]
            k = "shared_ids" if set(sx["ids"]) & set(sy["ids"]) else (
                "same_paragraph" if sx["p"] == sy["p"] else
                "cross_section" if sx["section"] != sy["section"] else "same_section_other_paragraph")
            kinds[k] += 1
            if len(ex) < EXAMPLES * 2:
                ex.append({"story": a["story"], "kind": k, "jaccard": j, "a": sx["text"][:160], "b": sy["text"][:160],
                           "sections": [sx["section"], sy["section"]]})
    return {"headline": [f"articles with at least one repeated-sentence pair: {affected} of {len(arts)} "
                         f"({share(affected, len(arts))})", f"pair kinds: {dict(kinds)}"],
            "data": {"articles": len(arts), "affected": affected, "pair_kinds": dict(kinds), "examples": ex}}


@test("H1/H27/H28/H37", "Merge brakes: top-90 cap, topic split, first-vs-final answers, missing topics")
def t_h27(d):
    """H1: stories with more than 90 canonical statements (rows beyond 90 never reach merge checks). H27: near-duplicate
    statement pairs (in the payload) that the topic step put in DIFFERENT groups (never compared). H28: pairs whose
    FIRST asking said same but the final answer is no (recorded, never consumed). H37: stories without topic_groups."""
    per_story = collections.Counter(c["story_id"] for c in d["canon"] if c["kind"] != "relation")
    pubids = {r["story_id"] for r in d["pub"]}
    over = {s: n for s, n in per_story.items() if n > 90 and s in pubids}
    f_yes_final_no = {"same": 0, "covers": 0}
    f_total = {"same": 0, "covers": 0}
    checks_n = collections.Counter()
    no_topics = with_topics = 0
    split = same_group = unknown = 0
    both_written = 0
    ex = []
    for r in d["pub"]:
        sid, p = r["story_id"], r["payload_en"]
        an = d["stories"].get(sid) or {}
        sc = an.get("same_checks") or {}
        checks_n["same_checks"] += len(sc)
        checks_n["dupe_checks"] += len(an.get("dupe_checks") or {})
        for k, v in sc.items():
            if k.startswith("f") and k[1:] in sc:
                kind = "covers" if k[1:2] == "c" else "same"
                f_total[kind] += 1
                if v is True and sc[k[1:]] is False:
                    f_yes_final_no[kind] += 1
        its = items(p)
        texts = {i: it.get("text") for i, it in its.items() if it.get("text") and it.get("kind") != "relation"}
        groups = {k: v for k, v in (an.get("topic_groups") or {}).items()
                  if isinstance(v, list) and all(isinstance(g, list) for g in v)}
        if len(texts) >= 3:
            if groups:
                with_topics += 1
            else:
                no_topics += 1
        if not groups or not texts:
            continue
        best = max(groups.values(), key=lambda g: len({t for grp in g for t in grp} & set(texts.values())))
        idx = {t: n for n, grp in enumerate(best) for t in grp}
        written = {x for s in sentences(p) for x in s["ids"]}
        for a, b, j in near_pairs(texts):
            ga, gb = idx.get(texts[a]), idx.get(texts[b])
            if ga is None or gb is None:
                unknown += 1
            elif ga == gb:
                same_group += 1
            else:
                split += 1
                both_written += (a in written and b in written)
                if len(ex) < EXAMPLES:
                    ex.append({"story": sid, "jaccard": j, "a": texts[a][:140], "b": texts[b][:140]})
    return {"headline": [f"stories with >90 statements: {len(over)} of {len(pubids)}; statements beyond 90: "
                         f"{sum(n - 90 for n in over.values())}",
                         f"near-duplicate pairs: same topic {same_group}, DIFFERENT topics {split} "
                         f"(both written in the article: {both_written}), not in the cache {unknown}",
                         f"first answer same, final answer no: {f_yes_final_no['same']} of {f_total['same']} same-pairs, "
                         f"{f_yes_final_no['covers']} of {f_total['covers']} cover-pairs",
                         f"stories with 3+ statements and NO topic_groups: {no_topics} (with: {with_topics})"],
            "data": {"over_90": over, "pairs_same_topic": same_group, "pairs_split_topics": split,
                     "split_pairs_both_written": both_written, "pairs_unknown_topic": unknown,
                     "first_same_final_no": f_yes_final_no, "first_totals": f_total, "checks": dict(checks_n),
                     "no_topic_groups": no_topics, "with_topic_groups": with_topics, "split_examples": ex}}


# ------------------------------------------------------------------------------------------------ names and speakers

def _style():
    from .. import style
    return style


def _voice():
    from .. import voice
    return voice


@test("H42", "Full names repeated 3+ times and why they were not shortened")
def t_h42(d):
    """H42/F68/F79: for every full name (a candidate person or a statement speaker) written 3+ times in one article,
    the reason style.shorten_names could not shorten it: shared surname, surname is a first name, a word of the name
    is in the TITLES/NOT_PERSON lists (filtered out), no person evidence, or accepted-but-still-repeated."""
    style, voice = _style(), _voice()
    arts = articles(d)
    reasons = collections.Counter()
    rows, affected = [], 0
    for a in arts:
        text = a["text"]
        speakers = [i.get("speaker") for i in a["items"].values() if isinstance(i.get("speaker"), str)]
        names = set(style._candidates(text))
        for sp in speakers:
            w = sp.split()
            if 2 <= len(w) <= 4 and all(x[:1].isupper() for x in w) and not voice.is_body(sp):
                names.add(sp)
        accepted = style.people(text, speakers)
        lasts = [n.split()[-1].lower() for n in names]
        firsts = {n.split()[0].lower() for n in names}
        hit = False
        for n in names:
            c = len(re.findall(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text))
            if c < 3:
                continue
            hit = True
            last = n.split()[-1]
            bad = [w for w in n.split() if w in style.TITLES or w in style.NOT_PERSON]
            if n in accepted:
                why = "accepted_but_still_repeated"
            elif bad:
                why = "word_in_title_or_notperson_list"
            elif lasts.count(last.lower()) > 1:
                why = "shared_surname"
            elif last.lower() in firsts:
                why = "surname_is_a_first_name"
            else:
                why = "no_person_evidence"
            reasons[why] += 1
            if len(rows) < EXAMPLES * 2:
                rows.append({"story": a["story"], "name": n, "times": c, "why": why, "words_listed": bad})
        affected += hit
    return {"headline": [f"articles with a full name written 3+ times: {affected} of {len(arts)} ({share(affected, len(arts))})",
                         f"reasons it stayed full: {dict(reasons)}"],
            "data": {"articles": len(arts), "affected": affected, "reasons": dict(reasons), "examples": rows}}


@test("H43/H46", "Speaker keys: different people sharing one key; speaker names the person detector rejects")
def t_h43(d):
    """H43/F70: voice.speaker_key keys a person by the LAST word, so different people with one surname (Gandhi, Singh,
    Kumar, Khan) become one speaker. Counted per story. H46/F79: speaker strings of 2+ capitalised words that
    style._candidates would never accept as a person (a word of the name is in TITLES/NOT_PERSON)."""
    style, voice = _style(), _voice()
    per_story = collections.defaultdict(lambda: collections.defaultdict(set))
    allnames = set()
    for c in d["claims"]:
        n = (c["attributed_to"] or "").strip()
        words = re.findall(r"[A-Z][\w'-]+", n)
        if len(words) < 2 or voice.is_body(n):
            continue
        allnames.add(n)
        per_story[c["story_id"]][voice.speaker_key(n)].add(n)
    coll_stories, coll_rows = 0, []
    key_names = collections.defaultdict(set)
    for sid, keys in per_story.items():
        hit = False
        for k, ns in keys.items():
            ns = list(ns)
            firsts = {re.findall(r"[A-Z][\w'-]+", n)[0] for n in ns}
            distinct = [n for n in ns if not any(n != m and set(n.split()) < set(m.split()) for m in ns)]
            if len(distinct) >= 2 and len(firsts) >= 2:
                hit = True
                key_names[k] |= set(distinct)
                if len(coll_rows) < EXAMPLES * 2:
                    coll_rows.append({"story": sid, "key": k, "names": sorted(distinct)[:5]})
        coll_stories += hit
    rejected = collections.Counter()
    rej_names = []
    rejected_names = set()
    for n in sorted(allnames):
        cands = style._candidates(n + " said it")
        if not any(n.endswith(c) or c in n for c in cands):
            bad = [w for w in n.split() if w in style.TITLES or w in style.NOT_PERSON]
            rejected_names.add(n)
            for w in bad or ["(other)"]:
                rejected[w] += 1
            if len(rej_names) < 25:
                rej_names.append({"name": n, "words_listed": bad})
    top_keys = sorted(key_names.items(), key=lambda kv: -len(kv[1]))[:12]
    return {"headline": [f"stories where two different people share one speaker key: {coll_stories} of {len(per_story)} "
                         f"stories with named speakers",
                         f"speaker names (2+ capitalised words, not bodies): {len(allnames)}; {len(rejected_names)} contain a "
                         f"word the person detector filters out; top words {rejected.most_common(8)}"],
            "data": {"stories_with_named_speakers": len(per_story), "collision_stories": coll_stories,
                     "top_collision_keys": [{"key": k, "names": sorted(v)[:6]} for k, v in top_keys],
                     "collision_examples": coll_rows, "speaker_names": len(allnames), "rejected_names": len(rejected_names),
                     "rejected_by_word": dict(rejected.most_common(25)), "rejected_examples": rej_names}}


OPEN_PRON = {"he", "she", "they", "it", "his", "her", "their", "its", "this", "that", "these", "those", "there"}
OPEN_DET = {"the", "a", "an", "some", "several", "many", "both", "all", "one", "another", "each", "other"}


@test("H66", "How statements open (pronoun, determiner, bare one-word name)")
def t_h66(d):
    """H66/F120: a statement whose subject is a pronoun or a one-word name is compared by relate with the subject missing.
    Closed word classes only (pronouns, determiners). Capitalised first word + lower-case second word and not in
    those classes = 'bare_name_or_other'."""
    c = collections.Counter()
    ex = collections.defaultdict(list)
    n = 0
    for r in d["canon"]:
        if r["kind"] == "relation" or not r.get("text") or r["story_id"] not in d["sids"]:
            continue
        w = r["text"].split()
        if len(w) < 3:
            continue
        n += 1
        f, s = w[0].strip(",.;:").lower(), w[1]
        if f in OPEN_PRON:
            k = "pronoun"
        elif f in OPEN_DET:
            k = "determiner"
        elif w[0][:1].isupper() and s[:1].islower():
            k = "bare_name_or_other"
        else:
            k = "full_name_or_other"
        c[k] += 1
        if len(ex[k]) < 5 and k != "full_name_or_other":
            ex[k].append(r["text"][:110])
    return {"headline": [f"{n} canonical statements: " + ", ".join(f"{k} {v} ({share(v, n)})" for k, v in c.most_common())],
            "data": {"statements": n, "shapes": dict(c), "examples": dict(ex)}}


# ------------------------------------------------------------------------------------------------ places

@test("H41", "Place tags: how the state was matched in the article")
def t_h41(d):
    """H41/F76: for every tagged state, which of its names the article text contains and whether any match is
    capitalised in the middle of a sentence. A tag whose only matches are lower-case (a common word: 'mandi') or that
    rests on a single city name is a suspect; the list is for owner reading."""
    from .. import places
    arts = articles(d)
    tagged = suspect = only_alt = not_found = 0
    ex = []
    per_state = collections.Counter()
    for a in arts:
        keys = a["p"].get("places") or []
        text = a["text"]
        for k in keys if isinstance(keys, list) else []:
            if k not in places.STATES:
                continue
            tagged += 1
            per_state[k] += 1
            en, hi, alt = places.STATES[k]
            found = []
            for nm in (en, hi, *alt):
                for m in re.finditer(rf"(?<![\w-]){re.escape(nm)}(?![\w-])", text, flags=re.I):
                    found.append((nm, m.group(), m.start()))
            mid_cap = [f for f in found if f[1][:1].isupper() and f[2] > 0 and not re.search(r"[.!?]\s$", text[max(0, f[2] - 2):f[2]])]
            own = [f for f in found if f[0] in (en, hi)]
            s_flag = not mid_cap
            a_flag = bool(found) and not own
            if not found:
                not_found += 1
                if len(ex) < EXAMPLES * 2:
                    ex.append({"story": a["story"], "state": k, "tag_not_found_in_text": True})
                continue
            suspect += s_flag
            only_alt += a_flag
            if (s_flag or a_flag) and len(ex) < EXAMPLES * 2:
                ex.append({"story": a["story"], "state": k, "matched": sorted({f[1] for f in found})[:5],
                           "no_mid_sentence_capital": s_flag, "only_a_city_name": a_flag})
    return {"headline": [f"{tagged} state tags in {len(arts)} articles; no mid-sentence capitalised match: {suspect}; "
                         f"matched only through a city/alias name: {only_alt}; tag with no match in the text: {not_found}"],
            "data": {"tags": tagged, "no_capitalised_match": suspect, "tag_not_found_in_text": not_found, "only_alias_match": only_alt,
                     "by_state": dict(per_state.most_common(15)), "examples": ex}}


# ------------------------------------------------------------------------------------------------ verification and origins

@test("H70", "false / confirmed verdicts and the evidence behind them")
def t_h70(d):
    """H70/F127: verdicts false or confirmed (checked by the model, second opinion) with NO web source and no evidence
    url in any opinion. A high share means those red/green marks rest on the model's own say."""
    rows = [c for c in d["canon"] if c["verdict"] in ("false", "confirmed") and c["story_id"] in d["sids"]]
    n = len(rows)
    none = 0
    ex = []
    by = collections.Counter()
    for c in rows:
        det = c.get("detail") or {}
        ops = det.get("opinions") or []
        urls = [u for o in ops if isinstance(o, dict) for u in o.get("evidence_urls") or []]
        web = det.get("web_sources") or []
        has = bool(urls or web)
        by[(c["verdict"], has)] += 1
        if not has:
            none += 1
            if len(ex) < EXAMPLES:
                ex.append({"story": c["story_id"], "verdict": c["verdict"], "text": (c["text"] or "")[:130],
                           "reason": next((o.get("reason") for o in ops if isinstance(o, dict) and o.get("reason")), None)})
    checked = sum(1 for c in d["canon"] if c["story_id"] in d["sids"] and (c.get("detail") or {}).get("checked"))
    return {"headline": [f"{n} false/confirmed rows; {none} without any web source or evidence url "
                         f"({share(none, n)}); rows ever model-checked: {checked}"],
            "data": {"rows": n, "no_evidence": none, "split": {f"{k[0]}|evidence={k[1]}": v for k, v in by.items()},
                     "examples": ex}}


@test("H74", "One government under several keys (attribution map)")
def t_h74(d):
    """H74/F140: per story, distinct `government` values among attribution-map entries of government kinds. 2+ values
    in one story = possibly one body counted as several (owner marks which are the same)."""
    try:
        from ..origins import GOV_KINDS
    except Exception:  # noqa: BLE001
        GOV_KINDS = {"police", "government", "official", "ministry", "agency_gov"}
    multi, tot = 0, 0
    ex = []
    for sid, an in d["stories"].items():
        gov = collections.defaultdict(set)
        for raw, e in (an.get("attribution_map") or {}).items():
            if isinstance(e, dict) and e.get("kind") in GOV_KINDS and e.get("government"):
                gov[e["government"]].add(raw)
        if gov:
            tot += 1
        if len(gov) >= 2:
            multi += 1
            if len(ex) < EXAMPLES * 2:
                ex.append({"story": sid, "governments": {g: sorted(v)[:3] for g, v in gov.items()}})
    return {"headline": [f"stories with a government attribution: {tot}; with 2+ distinct government keys: {multi}"],
            "data": {"stories_with_gov": tot, "stories_multi": multi, "examples": ex}}


@test("H79", "Stories qualified by the perspectives rule: how many independent outlets")
def t_h79(d):
    """H79/F145: for stories with analysis.qualified_by == 'perspectives', the number of independent sources and outlets
    in the payload, and the verdict mix of their statements; stories under 3 independent sources are the concern."""
    hist = {"perspectives": collections.Counter(), "other": collections.Counter()}
    verd = collections.Counter()
    ex = []
    low = 0
    for r in d["pub"]:
        p = r["payload_en"]
        q = (d["stories"].get(r["story_id"]) or {}).get("qualified_by") or p.get("qualified_by")
        n = (p.get("counts") or {}).get("independent_sources")
        key = "perspectives" if q == "perspectives" else "other"
        hist[key][n] += 1
        if q == "perspectives":
            for i in items(p).values():
                verd[i.get("verdict")] += 1
            if isinstance(n, int) and n < 3:
                low += 1
                if len(ex) < EXAMPLES:
                    ex.append({"story": r["story_id"], "independent": n, "outlets": (p.get("counts") or {}).get("outlets")})
    return {"headline": [f"perspectives-qualified stories: {sum(hist['perspectives'].values())}; with under 3 independent "
                         f"sources: {low}", f"independent-source histogram: perspectives {dict(hist['perspectives'])}, "
                         f"others {dict(hist['other'])}"],
            "data": {"histogram": {k: {str(a): b for a, b in v.items()} for k, v in hist.items()},
                     "verdicts_in_perspectives_stories": {str(k): v for k, v in verd.items()}, "low_examples": ex}}


# ------------------------------------------------------------------------------------------------ threads

@test("H95/H96", "Threads: parents lost, and two-parent stories")
def t_h95(d):
    """H95/F173: stories with a story_links row as child whose published payload has no parents (or thread == own id):
    a failed re-check at composition time. H96/F174: for children with 2+ parents, how many of the child's statements
    point (twins/updates) into each parent; a parent with none while another has some suggests the pointer was
    overwritten."""
    pubs = {r["story_id"]: r["payload_en"] for r in d["pub"]}
    parents_of = collections.defaultdict(set)
    for ln in d["links"]:
        parents_of[ln["child_id"]].add(ln["parent_id"])
    lost, ex = 0, []
    for child, ps in parents_of.items():
        p = pubs.get(child)
        if p is None:
            continue
        have = {x.get("story_id") for x in p.get("parents") or [] if isinstance(x, dict)}
        if not have or p.get("thread") == child:
            lost += 1
            if len(ex) < EXAMPLES:
                ex.append({"child": child, "links": sorted(ps), "payload_parents": sorted(h for h in have if h)})
    cstory = {c["id"]: c["story_id"] for c in d["canon"]}
    two, one_sided, rows = 0, 0, []
    for child, ps in parents_of.items():
        if len(ps) < 2:
            continue
        two += 1
        pointing = collections.Counter()
        for c in d["canon"]:
            if c["story_id"] != child:
                continue
            rel = c.get("rel") or {}
            for t in list(rel.get("twins") or []) + ([rel["updates"]] if rel.get("updates") else []):
                if cstory.get(t) in ps:
                    pointing[cstory[t]] += 1
        zero = [p for p in ps if pointing[p] == 0]
        if zero and len(zero) < len(ps):
            one_sided += 1
        rows.append({"child": child, "parents": sorted(ps), "pointers_per_parent": {str(p): pointing[p] for p in ps}})
    nchild = len([c for c in parents_of if c in pubs])
    return {"headline": [f"linked children in window: {nchild}; payload lost its parents: {lost}",
                         f"children with 2+ parents: {two}; of those with pointers into only some parents: {one_sided}"],
            "data": {"linked_children": nchild, "parents_lost": lost, "lost_examples": ex, "two_parent_children": two,
                     "one_sided": one_sided, "two_parent_rows": rows[:EXAMPLES]}}


# ------------------------------------------------------------------------------------------------ diagnostics

@test("H80/H87", "Positions signal and global-cluster flips over time")
def t_h87(d):
    """H87/H80: from the `positions` diagnostics rows, the signal sequence, flips, 'why' reasons, r vs null_r; from the run
    stats, any key mentioning 'cluster' and how often its value changes between consecutive runs."""
    pos = sorted(d["positions"], key=lambda r: r["id"])
    sig = [bool((r["report"] or {}).get("signal")) for r in pos]
    flips = sum(1 for a, b in zip(sig, sig[1:]) if a != b)
    why = collections.Counter(str((r["report"] or {}).get("why")) for r in pos if (r["report"] or {}).get("why"))
    rs = [{"at": str(r["created_at"])[:16], "signal": bool((r["report"] or {}).get("signal")),
           "r": (r["report"] or {}).get("r"), "null_r": (r["report"] or {}).get("null_r"),
           "separated": (r["report"] or {}).get("separated"), "units": (r["report"] or {}).get("units")} for r in pos]
    runs = sorted(d["runs"], key=lambda r: r["id"])
    changes: dict = {}
    for k in {k for r in runs for k in (r["stats"] or {}) if "cluster" in k.lower()}:
        vals = [json.dumps((r["stats"] or {}).get(k), sort_keys=True, default=str) for r in runs]
        changes[k] = {"runs": len(vals), "changes": sum(1 for a, b in zip(vals, vals[1:]) if a != b),
                      "distinct": len(set(vals))}
    return {"headline": [f"positions rows: {len(pos)}; signal true {sum(sig)}; flips {flips}; reasons {dict(why)}",
                         f"cluster-like run stats: {changes or 'none found'}"],
            "data": {"positions_rows": len(pos), "signal_true": sum(sig), "flips": flips, "why": dict(why),
                     "series": rs[-40:], "cluster_stats": changes, "runs_read": len(runs)}}


# ------------------------------------------------------------------------------------------------ run + report

def run(d: dict, only: set[str] | None = None) -> dict:
    out = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "window_days": d["days"],
           "tests": {}}
    for ids, title, fn in REGISTRY:
        if only and not (only & {x.strip() for x in ids.split("/")} or ids in only or "OVERVIEW" == ids):
            continue
        try:
            res = fn(d)
        except Exception as e:  # noqa: BLE001
            res = {"headline": [f"ERROR {type(e).__name__}: {str(e)[:300]}"],
                   "data": {"traceback": traceback.format_exc()[-1500:]}, "error": True}
        res["title"] = title
        out["tests"][ids] = res
    return out


def markdown(rep: dict) -> str:
    lines = [f"# Hypothesis tests, group A ({rep['generated_at']}, window {rep['window_days']} days)", ""]
    for ids, r in rep["tests"].items():
        lines.append(f"## {ids}: {r['title']}")
        lines += [f"- {h}" for h in r["headline"]]
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--out", default="hypotheses.json")
    ap.add_argument("--md", default="hypotheses.md")
    ap.add_argument("--only", default="")
    ap.add_argument("--print", action="store_true", help="also print the summary (job logs of a public repo are public)")
    a = ap.parse_args(argv)
    import os
    from sqlalchemy import create_engine, text

    from ..config import database_url, normalize_db_url

    def runner(engine):
        def q(sql, **p):
            with engine.connect() as c:
                return [dict(r) for r in c.execute(text(sql), p).mappings()]
        return q
    news = runner(create_engine(database_url(), pool_pre_ping=True))
    rurl = os.environ.get("READERS_DATABASE_URL", "").strip()
    readers = runner(create_engine(normalize_db_url(rurl), pool_pre_ping=True)) if rurl else None
    d = load(news, a.days, readers)
    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    rep = run(d, only)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    md = markdown(rep)
    with open(a.md, "w", encoding="utf-8") as f:
        f.write(md)
    if a.print:
        print(md)
    else:
        print(f"{len(rep['tests'])} tests written to {a.out} and {a.md} (not printed: the repository is public)")


if __name__ == "__main__":
    main()

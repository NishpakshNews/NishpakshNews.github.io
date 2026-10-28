"""Stage 8b: assemble the article, then translate it.

Structure is decided by code, not by a model:
  timeline        corroborated/confirmed events, ordered by the partial order
  established     corroborated/confirmed statements that are not events
  contested       everything else, each with its verdict (false ones included, tagged)
  framing         the loaded words each perspective used for the same fact
  sources         every article read, with its perspective
The news (news.pick_news, code) is chosen here; the article (narrative.py) leads with it and the
headline (news.write_headline) is written from it after the article, then the Hindi translation.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import logging
import re
import time
from collections import Counter, defaultdict

from .db import Store, articles, claims, published, select, stories, update, utcnow, insert
from .router import QuotaExhausted, Router
from .timeline import build_timeline
from .verify import _story_context, relation_text, support_summary

log = logging.getLogger(__name__)
ESTABLISHED = {"corroborated", "confirmed"}

# Seconds the stages of publish_story took in this process (the desk reads and clears it each run, desk.py): the desk used to
# record only "review" and "write", so a 30-minute run could not say whether the thread check, the follow-up check, the
# writer, the headline or the translation took the time (owner, Oct 27 2026).
STAGE_SECONDS: dict[str, float] = {}


@contextlib.contextmanager
def _timed(stage: str):
    t0 = time.time()
    try:
        yield
    finally:
        STAGE_SECONDS[stage] = round(STAGE_SECONDS.get(stage, 0.0) + time.time() - t0, 1)

TRANSLATE_PROMPT = """Translate each value of this JSON object into Hindi (Devanagari script).
Translate literally and neutrally: do not add, soften or strengthen anything, and keep the small words that change
a claim (not, never, only, at least, up to, more than, directly, alleged). Keep all numbers as they are. Write names
of people and places in Devanagari, the way Hindi newspapers write them (use the NAMES list exactly when given), and
abbreviations the way Hindi newspapers do (BJP = भाजपा). Write the plain formal Hindi of Hindi newspapers, in natural
Hindi word order. Anything in brackets (...) or [...] is a name: copy it letter for letter, in the same brackets. A court, bench, tribunal, commission, committee, council, cabinet, board or the
police is several people: where the English says "they" / "their", write the plural (वे, उन्होंने, उनके) with plural verbs.
Never begin a sentence with a pronoun (यह, वह, वे, उन्होंने ...) unless the English sentence begins with one: keep the
name the English uses. Return a JSON object with exactly the same keys.
{names}{terms}
{payload}"""


_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_DIGITS_HI = str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f", "0123456789")


_HI_OPEN = re.compile(r"^(?:यह|ये|वह|वे|उन्होंने|उसने|इसने|उसे|इसे|उन्हें|इन|उन|इस|उस|उनके|उसके|इसके|इनके)(?=[\s,।])")
_EN_PRONOUN = re.compile(r"(?i)\b(?:it|its|itself|they|their|them|this|these|those|he|she|his|her|him)\b")


def translation_problem(src: str, out: str) -> str | None:
    """Why a Hindi string is unusable, or None. Ported from the owner's booktrans.py (output_problem): an empty or
    echoed string, or one with no Devanagari at all, would otherwise be cached and published as 'translated'; and a
    translation that changes a number is a wrong article (the prompt says keep numbers as they are)."""
    out_t, src_t = (out or "").strip(), (src or "").strip()
    if not out_t:
        return "empty"
    letters = re.findall(r"[A-Za-z]", src_t)
    if len(src_t) >= 20 and len(letters) >= 6:
        norm = lambda t: re.sub(r"\W+", " ", t.lower()).strip()
        if norm(out_t) == norm(src_t):
            return "echoed the source"
        if not _DEVANAGARI.search(out_t):
            return "no Devanagari"
    nums = lambda t: sorted(re.findall(r"\d+", t.translate(_DIGITS_HI).replace(",", "")))
    if nums(src_t) != nums(out_t):
        return "numbers changed"
    # the name the newsroom put in brackets (refs.py) is copied as it is: a missing or changed one is a wrong article
    for m in re.finditer(r"[\(\[]([^()\[\]]*(?:\([^()]*\))?[^()\[\]]*)[\)\]]", src_t):
        inner = m.group(1).strip()
        if re.search(r"[A-Za-z]{3,}", inner) and " ".join(inner.split()) not in " ".join(out_t.split()):
            return "bracketed name changed"
    # the translator may not turn a name into a pronoun that points at nothing (refs.py)
    if _HI_OPEN.match(out_t.lstrip("\"“‘' ")) and not _EN_PRONOUN.search(src_t):
        return "pronoun added"
    return None


def tidy(text: str) -> str:
    """'LPU (LPU)' -> 'LPU': an abbreviation the extraction repeated in brackets."""
    return re.sub(r"\b([\w.&'-]+(?: [\w.&'-]+){0,4}) \(\1\)", r"\1", text or "")


def _interval(rows: list[dict]) -> dict:
    starts = [r["time"]["start"] for r in rows if r.get("time") and r["time"].get("start")]
    ends = [r["time"]["end"] for r in rows if r.get("time") and r["time"].get("end")]
    whens = Counter(r["time"]["when_text"] for r in rows if r.get("time") and r["time"].get("when_text"))
    return {"start": min(starts) if starts else None, "end": max(ends) if ends else None,
            "when_text": whens.most_common(1)[0][0] if whens else ""}


def _item_refs(c: dict, rows: list[dict]) -> list[dict]:
    """The names the reports gave to the generic references of this statement (\"the new scheme\"), for the ones
    its text still has. One name per phrase; two different names for one phrase = none (never a guess)."""
    if c.get("kind") == "relation":
        return []
    text = (c.get("text") or "").lower()
    found: dict[str, set[str]] = {}
    for r in [c, *rows]:
        for ref in ((r.get("rel") or {}).get("refs") or []):
            if ref.get("phrase") and ref.get("gloss") and ref["phrase"].lower() in text:
                found.setdefault(ref["phrase"], set()).add(ref["gloss"])
    return [{"phrase": ph, "gloss": next(iter(g))} for ph, g in found.items() if len(g) == 1]


MAX_WRITTEN = 60       # statements the writer is given for one article (Oct 27 2026: a story of 116 gave a 114-sentence article)


def trim_to_cap(payload: dict, cap: int = MAX_WRITTEN) -> int:
    """A very large story is written from its best-supported statements; the rest go to "Also in these reports" (shown,
    coloured, numbered, but not part of the article or its completeness bar). Order of removal: background / related /
    explanation / reaction / next lines first, then core statements only one report carries; never a disputed or false
    line, a line with a partner (contradiction, response) or one the lead is chosen from. Within a class the least
    supported goes first. Returns how many were moved."""
    from .narrative import ordered_items
    items = ordered_items(payload)
    over = len(items) - cap
    if over <= 0:
        return 0
    keep_ids = set(payload.get("news") or []) | set(payload.get("lead") or [])

    from .followup import partnered

    def locked(i: dict) -> bool:
        return i["id"] in keep_ids or partnered(i)

    context = [i for i in items if (i.get("role") or "core") != "core" and not locked(i)]
    core = [i for i in items if (i.get("role") or "core") == "core" and i.get("minor") and not locked(i)]
    rank = lambda i: (i.get("n_sources", 0), i.get("n_articles", 0), -i["id"])  # noqa: E731
    cut = (sorted(context, key=rank) + sorted(core, key=rank))[:over]
    if not cut:
        return 0
    gone = {i["id"] for i in cut}
    payload["timeline"] = [[i for i in tier if i["id"] not in gone] for tier in payload.get("timeline") or []]
    for k in ("undated", "established", "contested", "context"):
        payload[k] = [i for i in payload.get(k) or [] if i["id"] not in gone]
    payload.setdefault("also", []).extend(dict(i, tag="cap") for i in cut)
    log.info("story payload trimmed: %d of %d statements moved to 'also in these reports'", len(cut), len(items))
    return len(cut)


def build_payload(store: Store, router: Router | None, story_id: int) -> dict | None:
    story, agroup, gpersp, arts, canon, members = _story_context(store, story_id)
    if not story["qualifies"]:
        return None
    full_arts = {a["id"]: a for a in store.rows(
        select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.title, articles.c.lang,
               articles.c.published_at, articles.c.role, articles.c.extracted_at, articles.c.text_source,
               articles.c.found_by).where(articles.c.story_id == story_id))}
    texts = {cid: c["text"] for cid, c in canon.items()}

    analysis_ = story["analysis"] or {}
    speakers = analysis_.get("speakers") or {}
    departures = analysis_.get("departures") or {}
    roles = analysis_.get("roles") or {}
    related_event = analysis_.get("related_event") or {}
    name_conf = analysis_.get("name_conflicts") or {}
    responds_to: dict[int, list[int]] = defaultdict(list)
    responded_by: dict[int, list[int]] = defaultdict(list)
    for a_, b_ in analysis_.get("responses") or []:
        if a_ in canon and b_ in canon:
            responded_by[a_].append(b_)
            responds_to[b_].append(a_)

    def _role(cid: int) -> tuple[str, str]:
        """'core' or a context role, and the related event's name. Consolidation's reading of the
        whole story wins; otherwise the reports' own: context only if every report gave it as context."""
        rows_ = members.get(cid, [])
        ctx = [((r.get("rel") or {}) if r["kind"] != "relation" else {}).get("context") for r in rows_]
        label = related_event.get(str(cid)) or next(
            (((r.get("rel") or {}).get("event") or "") for r in rows_ if (r.get("rel") or {}).get("event")), "")
        if str(cid) in roles:
            return roles[str(cid)], label
        if rows_ and all(ctx):
            return Counter(ctx).most_common(1)[0][0], label
        return "core", ""

    def _persp_of(aid: int) -> str:
        """An article that departs from its outlet's perspective shows its own (marked †)."""
        d = departures.get(str(aid))
        return f"{d['to']}†" if d else (gpersp.get(agroup.get(aid)) or "–")

    def _state_voice(cid: int) -> str | None:
        """A statement only foreign state media report in their own voice is that government speaking
        (owner, Oct 9 2026): written as "Chinese state media said", never as a plain fact."""
        from .ownership import owner_of, state_voice
        rows_ = [r for r in members.get(cid, []) if r["stance"] in ("asserts", "attributes")]
        voices = set()
        for r in rows_:
            a = full_arts.get(r["article_id"])
            v = state_voice(owner_of(a["outlet"], a["url"])) if a else None
            if not v or r["attributed_to"]:
                return None
            voices.add(v)
        return voices.pop() if len(voices) == 1 else None

    outlet_names = {re.sub(r"^the ", "", (a["outlet"] or "").lower()).strip() for a in full_arts.values()}

    def _reading_speaker(cid: int) -> str | None:
        """Who says it, as reading recorded it: every report gives the line as one named speaker's words
        (stance "attributes", the same attributed_to). Oct 9 2026, story 13058: "Nana Patekar was an
        extraordinary artist ...", which reading gave to Modi, opened the article as a plain fact because only
        the review's own speaker list was used. An outlet is never a speaker (no outlet names in the text)."""
        rows_ = [r for r in members.get(cid, []) if r["stance"] in ("asserts", "attributes")]
        if not rows_ or any(r["stance"] != "attributes" for r in rows_):
            return None
        who = {(r["attributed_to"] or "").strip() for r in rows_}
        if len({w.lower() for w in who}) != 1:
            return None
        w = who.pop()
        low = re.sub(r"^the ", "", w.lower())
        if not w or low in ("article", "unknown", "unnamed", "none") or low in outlet_names \
                or re.search(r"\b(media|reports?|newspaper|channel)\b", low):
            return None
        return w

    def item(cid: int) -> dict:
        c = canon[cid]
        s = support_summary(cid, members, agroup, gpersp)
        srcs, seen = [], set()
        framing = defaultdict(set)
        for r in members.get(cid, []):
            a = full_arts.get(r["article_id"])
            if not a:
                continue
            p = _persp_of(a["id"])
            for w in r["loaded_words"] or []:
                framing[p].add(w)
            if a["url"] in seen:
                continue
            seen.add(a["url"])
            srcs.append({"outlet": a["outlet"], "url": a["url"], "lang": a["lang"], "perspective": p,
                         "stance": r["stance"], "evidence": r["evidence"], "attributed_to": r["attributed_to"]})
        detail = c["detail"] or {}
        check = None
        if detail.get("checked"):
            check = {"outcome": detail.get("outcome"), "checked_at": detail.get("checked_at"),
                     "reasons": [o.get("reason") for o in detail.get("opinions", []) if o.get("reason")],
                     "evidence_urls": sorted({u for o in detail.get("opinions", []) for u in o.get("evidence_urls", [])}),
                     "web_sources": detail.get("web_sources", [])}
        return {
            "id": cid, "kind": c["kind"],
            "text": relation_text(c["rel"], texts) if c["kind"] == "relation" else tidy(c["text"]),
            "verdict": c["verdict"], "n_sources": len(s["support_groups"]), "n_articles": s["n_articles"],
            "groups": [str(g) for g in s["support_groups"]],
            "supported_by": s["support_perspectives"], "denied_by": s["deny_perspectives"],
            "conflicts_with": [x for x in (c["conflicts"] or []) if x in canon],
            "time": _interval(members.get(cid, [])) if c["kind"] == "event" else None,
            "framing": {k: sorted(v) for k, v in sorted(framing.items())},
            "sources": sorted(srcs, key=lambda x: (x["perspective"], x["outlet"])),
            "check": check, "minor": s["n_articles"] <= 1,
            "speaker": speakers.get(str(cid)) or _reading_speaker(cid) or _state_voice(cid),
            "role": _role(cid)[0], "related_event": _role(cid)[1] or None,
            "responds_to": [x for x in responds_to.get(cid, []) if members.get(x)],
            "responded_by": [x for x in responded_by.get(cid, []) if members.get(x)],
            "name_conflict": name_conf.get(str(cid)),
            "origins": (c.get("origins") or {}).get("origins", []),
            "n_origins": (c.get("origins") or {}).get("n_origins", 0),
            "n_outlets": (c.get("origins") or {}).get("outlets", 0),
            # its fields (frames.py): the writer's sections place figures by them
            "frame": (c.get("rel") or {}).get("frame") if c["kind"] != "relation" else None,
            # what a generic reference in it points to (refs.py): from the statement or any report behind it
            "refs": _item_refs(c, members.get(cid, [])),
            # a speaker's exact words, as an English report printed them (checked word for word when read)
            "words": _exact_words(members.get(cid, [])),
            # the report sentences this line is a piece of (bundles.py): pieces of one sentence are written back as one
            "bundle_roots": sorted({str(((r.get("rel") or {}).get("bundle") or {}).get("root")) for r in members.get(cid, [])
                                    if ((r.get("rel") or {}).get("bundle") or {}).get("root")}),
        }

    def _exact_words(rows: list[dict]) -> str | None:
        """The exact words most reports behind a statement print (the longest on a tie), or None."""
        from collections import Counter
        got = Counter(str((r.get("rel") or {}).get("words") or "").strip() for r in rows)
        got.pop("", None)
        if not got:
            return None
        return max(got, key=lambda w: (got[w], len(w)))

    all_items = {cid: item(cid) for cid in canon if members.get(cid)
                 and not (canon[cid]["kind"] == "relation" and not relation_text(canon[cid]["rel"] or {}, texts))}   # E13: no "?" endpoint
    # the story's own event drives the timeline, sections and headline; context (background, related
    # events, explanation, reactions, what next) is carried separately and written after it
    items = {cid: i for cid, i in all_items.items() if i["role"] == "core" or i["kind"] == "relation"}
    ROLE_ORDER = {"background": 0, "related": 1, "explanation": 2, "reaction": 3, "next": 4}
    context = sorted([i for i in all_items.values() if i["id"] not in items],
                     key=lambda i: (ROLE_ORDER.get(i["role"], 9), -i["n_articles"], i["id"]))
    est_events = [i for i in items.values() if i["kind"] == "event" and i["verdict"] in ESTABLISHED]
    est_ids = {i["id"] for i in est_events}
    rel_edges = []
    for i in items.values():
        if i["kind"] == "relation" and i["verdict"] in ESTABLISHED:
            rel = canon[i["id"]]["rel"]
            if rel["from"] in est_ids and rel["to"] in est_ids:
                rel_edges.append((rel["from"], rel["to"]))
    tl = build_timeline([{"id": i["id"], "start": i["time"]["start"], "end": i["time"]["end"],
                          "weight": i["n_sources"]} for i in est_events], rel_edges)
    established = sorted([i for i in items.values() if i["kind"] == "claim" and i["verdict"] in ESTABLISHED],
                         key=lambda i: (-i["n_sources"], i["id"]))
    shown = est_ids | {i["id"] for i in established}
    # a stated "before" that the timeline already shows from the clock adds nothing
    tier_of = {n: k for k, tier in enumerate(tl["tiers"]) for n in tier}
    for i in items.values():
        rel = canon[i["id"]]["rel"] if i["kind"] == "relation" else None
        if (rel and rel["type"] == "before" and rel["from"] in tier_of and rel["to"] in tier_of
                and tier_of[rel["from"]] < tier_of[rel["to"]]):
            shown.add(i["id"])
    contested = sorted([i for i in items.values() if i["id"] not in shown
                        and not (i["kind"] == "relation" and i["verdict"] in ESTABLISHED)],
                       key=lambda i: (-i["n_articles"], i["id"]))
    framing = [{"id": i["id"], "text": i["text"], "words": i["framing"]}
               for i in sorted(items.values(), key=lambda i: -i["n_articles"])
               if len([p for p, w in i["framing"].items() if w]) >= 2]

    banned = {w.lower() for i in items.values() for ws in i["framing"].values() for w in ws if len(w) >= 4}
    # the news, chosen once by code (news.py): the lead and the headline are written from it
    from . import importance as imp, news as news_, threads
    news_ids = news_.pick_news(list(items.values()), [a["title"] for a in full_arts.values() if a.get("lang") == "en"])
    by_support = sorted(items.values(), key=lambda i: (-i["n_sources"], -i["n_articles"], i["id"]))
    summary = [items[n]["text"] for n in news_ids[:1]] + [i["text"] for i in by_support if i["id"] not in news_ids[:1]]
    from .editions import link_candidate, parent_pages
    link_candidate(store, story_id)      # later reports of a published story develop it
    with _timed("thread_check"):
        parent_ids = threads.find_parents(store, router, story_id, story["signature"] or "", " ".join(summary[:4]))
        live = parent_pages(store, parent_ids, strict=True)   # live, or already on the archive branch; Unreachable = wait
    thread_ctx = "; ".join(live[p]["headline_en"] for p in parent_ids if p in live)

    analysis = story["analysis"] or {}
    persp = defaultdict(set)
    for g, info in (analysis.get("groups") or {}).items():
        persp[info.get("perspective") or "–"].update(info.get("outlets", []))
    for aid, d in departures.items():
        a = full_arts.get(int(aid))
        if a:
            persp[d["to"]].add(f"{a['outlet']} († this article differs from the outlet's usual perspective)")
    sources = sorted([{"outlet": a["outlet"], "title": a["title"], "url": a["url"], "lang": a["lang"],
                       "role": a["role"], "perspective": _persp_of(a["id"]),
                       # option B: an article we could not read is listed, never used for facts
                       "read": bool(a["extracted_at"]) and a["text_source"] != "summary",
                       "readable": a["text_source"] != "summary",
                       "found_by": a["found_by"] or "feed",
                       "published_at": a["published_at"].isoformat(timespec="minutes") if a["published_at"] else None}
                      for a in full_arts.values()], key=lambda s: (s["perspective"], s["outlet"]))

    # importance comes from the story's rating (priority.py, from its headlines); filler is never published
    prio = analysis.get("priority") or {}
    if prio.get("filler"):
        log.info("story %s is filler: not published", story_id)
        return None
    from .wire import independent
    n_indep = len(independent(list(analysis.get("groups") or {})))
    langs = len({a["lang"] for a in full_arts.values() if a["extracted_at"]})

    # threads: earlier stories this one develops, and later ones that develop it (published only)
    parents = [{"story_id": p, "headline": live[p]["headline_en"]} for p in parent_ids if p in live]
    children: list[dict] = []    # an article is written once, before anything develops it
    # background for the essay: the parents' established facts, with their sources (at most 4)
    background = []
    for p in parent_ids:
        if p not in live:
            continue
        pe = live[p]["payload_en"] or {}
        est = [i for tier in pe.get("timeline") or [] for i in tier] + (pe.get("established") or [])
        if not est:   # nothing established on the parent: its best-supported reports, still as reports
            est = sorted(pe.get("contested") or [], key=lambda i: -i.get("n_articles", 0))
        for i in est[:4 - len(background)]:
            if i.get("kind") != "relation":
                background.append(dict(i, id=-int(i["id"]), kind="background", parent=p))
    return {
        "story_id": story_id,
        "importance": {"score": prio.get("score")},
        "rank": imp.rank(prio.get("score") or 3, n_indep, langs),
        "thread": threads.root_of(store, story_id) if parents else story_id,
        "parents": parents,
        "children": children,
        "background": background,
        "headline": None,                     # written after the article, from the news (news.py)
        "news": news_ids[:3],                 # the first is THE news: the lead cites it
        "_thread_ctx": thread_ctx,            # for the headline; not stored
        "has_established": bool(est_events or established),
        "perspective_mode": analysis.get("mode"),
        "qualified_by": analysis.get("qualified_by"),
        "express_lane": analysis.get("express_lane"),      # express.py: the lane of an express story
        "perspectives": {k: sorted(v) for k, v in sorted(persp.items())},
        "timeline": [[items[n] for n in tier] for tier in tl["tiers"]],
        "undated": [items[n] for n in tl["undated"]],
        "established": established,
        "contested": contested,
        "framing": framing,
        "context": context,
        "sources": sources,
        "loaded_words": sorted(banned),
        "counts": {"articles": len(full_arts), "independent_sources": n_indep,
                   "outlets": len({a["outlet"] for a in full_arts.values()})},
        # a suicide story carries a helpline note (responsible-reporting guidelines)
        "suicide": any(re.search(r"(?i)suicide|took (his|her|their) own life|आत्महत्या|ख़ुदकुशी|खुदकुशी", i["text"])
                       for i in all_items.values()),
    }


def _key(text: str) -> str:
    # versioned by our binding terms (hindi.cache_version, Oct 16 2026): a changed term translates again
    from .hindi import cache_version
    return hashlib.sha256((f"hi|{cache_version()}|" + text).encode("utf-8")).hexdigest()


def _collect_strings(payload: dict) -> list[str]:
    out = [payload["headline"]]
    for sec in ("undated", "established", "contested"):
        for i in payload[sec]:
            out.append(i["text"])
            if i.get("check"):
                out += [r for r in i["check"]["reasons"] if r]
    for tier in payload["timeline"]:
        for i in tier:
            out.append(i["text"])
            if i["time"] and i["time"].get("when_text"):
                out.append(i["time"]["when_text"])
    for f in payload["framing"]:
        out.append(f["text"])
    for i in payload.get("context", []) + payload.get("also", []):
        out.append(i["text"])
        if i.get("related_event"):
            out.append(i["related_event"])
    out += [x["headline"] for x in payload.get("parents", []) + payload.get("children", []) if x.get("headline")]
    out += [b["text"] for b in payload.get("background", [])]
    for para in (payload.get("narrative") or {}).get("paragraphs", []):
        out += [x["text"] for x in para]
    out += [x["text"] for x in (payload.get("narrative") or {}).get("other_coverage", [])]
    return [s for s in dict.fromkeys(out) if s]


def _speakers_of(payload: dict) -> list[str]:
    """Every speaker name the payload's statements carry (in whichever list the payload keeps them)."""
    out = []
    for k, v in payload.items():
        if isinstance(v, list):
            out += [x["speaker"] for x in v if isinstance(x, dict) and isinstance(x.get("speaker"), str) and x["speaker"]]
    return out


def _mended(store: Store, cache: dict, strings: list[str]) -> dict:
    """Names left in Latin letters in cached Hindi, replaced by what the registry knows now (hindi.py): a name learned
    after a string was translated mends it on the next render, at no cost."""
    from . import hindi, names
    try:
        reg = names.load(store)
    except Exception:  # noqa: BLE001
        return cache
    out = dict(cache)
    for s in strings:
        k = _key(s)
        if k in out and out[k]:
            known = hindi.known_names(reg, [s])
            if known:
                out[k] = hindi.devanagari_names(out[k], known)
    return out


def translate_strings(store: Store, router: Router | None, strings: list[str]) -> dict[str, str]:
    """{English: Hindi} for the strings translated (cached or now); the rest are missing."""
    cache = _mended(store, _translate(store, router, strings), strings)
    return {s: cache[_key(s)] for s in strings if _key(s) in cache}


def _section_of(category: dict | None) -> str:
    """The story's first secondary section, else its first primary one, else ""."""
    for level in ("secondary", "primary"):
        keys = (category or {}).get(level) or []
        if keys:
            return str(keys[0])
    return ""


def translate_payload(store: Store, router: Router | None, payload: dict) -> dict:
    strings = _collect_strings(payload)
    cache = _mended(store, _translate(store, router, strings, _section_of(payload.get("category"))), strings)

    def tr(s):
        return cache.get(_key(s), s) if s else s
    return _apply(payload, strings, cache, tr)


def _translate(store: Store, router: Router | None, strings: list[str], section: str = "") -> dict:
    from . import hindi
    hindi.SECTION.set(section or "")
    cache = store.translation_get([_key(s) for s in strings])
    missing = [s for s in strings if _key(s) not in cache]
    if missing and router is not None:
        names = hindi.name_map(store, router, missing)        # registry, then one transliteration (quality tier)
        for start in range(0, len(missing), 40):
            chunk = missing[start:start + 40]
            body = json.dumps({str(i): s for i, s in enumerate(chunk)}, ensure_ascii=False)
            try:
                res = router.call("page", TRANSLATE_PROMPT.format(payload=body, names=hindi.names_block(names, chunk),
                                                                  terms=hindi.terms_block(chunk)), json_out=True,
                                  max_output_tokens=4000)
            except QuotaExhausted:
                log.info("translation: light tier exhausted; Hindi version partial")
                break
            except Exception as e:  # noqa: BLE001
                log.warning("translation failed: %s", e)
                continue
            drafts = {}
            for k, v in (res.data or {}).items() if isinstance(res.data, dict) else []:
                if k.isdigit() and int(k) < len(chunk) and isinstance(v, str) and v.strip():
                    drafts[int(k)] = v.strip()
            # names by code, the checks, and the edit pass on the quality tier (hindi.py)
            keep, why = hindi.finish(router, chunk, drafts, names)
            got = {_key(chunk[i]): h for i, h in keep.items()}
            for i, w in why.items():                  # never cached: the article stays "partly translated" and a later pass retries
                log.info("translation rejected (%s): %s", w, chunk[i][:80])
            store.translation_put(got)
            cache.update(got)
        log.info("hindi: %s", dict(hindi.STATS))
    return cache


def _apply(payload: dict, strings: list[str], cache: dict, tr) -> dict:
    hi = copy.deepcopy(payload)
    hi["headline"] = tr(hi["headline"])
    for sec in ("undated", "established", "contested"):
        for i in hi[sec]:
            i["text"] = tr(i["text"])
            if i.get("check"):
                i["check"]["reasons"] = [tr(r) for r in i["check"]["reasons"]]
    for tier in hi["timeline"]:
        for i in tier:
            i["text"] = tr(i["text"])
            if i["time"] and i["time"].get("when_text"):
                i["time"]["when_text"] = tr(i["time"]["when_text"])
    for f in hi["framing"]:
        f["text"] = tr(f["text"])
    for i in hi.get("context", []) + hi.get("also", []):
        i["text"] = tr(i["text"])
        if i.get("related_event"):
            i["related_event"] = tr(i["related_event"])
    for x in (hi.get("narrative") or {}).get("other_coverage", []):
        x["text"] = tr(x["text"])
        x.pop("parts", None)
    for x in hi.get("parents", []) + hi.get("children", []):
        x["headline"] = tr(x["headline"])
    for b in hi.get("background", []):
        b["text"] = tr(b["text"])
    for para in (hi.get("narrative") or {}).get("paragraphs", []):
        for x in para:
            x["text"] = tr(x["text"])
            # Hindi word order differs: parts cannot be translated apart, so a Hindi sentence has one
            # colour, the weakest (its "class"), as before parts existed
            x.pop("parts", None)
    hi["translation_complete"] = all(_key(s) in cache for s in strings)
    return hi


def finish_translations(store: Store, router: Router, limit: int = 3) -> list[int]:
    """Hindi pages published half-translated (Oct 8 2026, story 15429: the page models were overloaded
    mid-translation and half the Hindi article stayed English) are finished on later runs. The English
    article is unchanged (it is closed); only its translation is completed. Strings already translated
    come from the cache, so a retry costs only the missing ones."""
    done = []
    incomplete = published.c.payload_hi["translation_complete"].as_boolean().is_(False)   # in SQL: no egress
    for r in store.rows(select(published.c.story_id, published.c.payload_en, published.c.payload_hi)
                        .where(incomplete).order_by(published.c.updated_at.desc()).limit(limit)):
        if not r["payload_en"]:
            continue
        hi = translate_payload(store, router, r["payload_en"])
        hi["version"] = (r["payload_hi"] or {}).get("version", 1)
        store.exec(update(published).where(published.c.story_id == r["story_id"])
                   .values(payload_hi=hi, headline_hi=hi["headline"]))
        done.append(r["story_id"])
        if not hi["translation_complete"]:
            break                           # the page models are still refusing: next run
    return done


WRITER_LITE_OK = ("gemini-3.5-flash-lite",)   # owner, Oct 6 2026: the writer's last resort; older Lites read badly


def _keepable(nar: dict | None) -> bool:
    """An essay we may publish: written by the writer (a Flash model, or 3.5 Flash-Lite when every
    Flash model is refusing), never stitched by code, never by an older Flash-Lite."""
    m = (nar or {}).get("model") or ""
    lite_ok = any(m.startswith(x) for x in WRITER_LITE_OK)
    return bool(m) and ("lite" not in m or lite_ok) and bool((nar or {}).get("paragraphs"))


def _draft_ids(sections) -> set[int]:
    """Statement numbers a kept draft cites: sections are [key, paragraph], a paragraph a list of sentences."""
    return {x for _, para in sections or [] for sent in para or [] if isinstance(sent, dict)
            for x in (sent.get("ids") or []) if isinstance(x, int)}


def _draft_anchors(store: Store, sections) -> dict[str, int]:
    """One report (claim) behind each statement the draft cites: when consolidation later merges that
    statement into another, the report moves with it, so the draft's sentence can follow."""
    ids = sorted(_draft_ids(sections))
    out: dict[str, int] = {}
    for r in store.rows(select(claims.c.id, claims.c.canonical_id).where(claims.c.canonical_id.in_(ids or [-1]))
                        .order_by(claims.c.id)):
        out.setdefault(str(r["canonical_id"]), r["id"])
    return out


def _remap_draft(store: Store, draft: dict | None, payload: dict) -> dict | None:
    """A kept draft cites statement numbers from when it was written; statements merged since then are
    renamed to the statement they joined, so their sentences are kept instead of dropped."""
    if not draft or not draft.get("sections"):
        return draft
    from .narrative import ordered_items
    known = {i["id"] for i in ordered_items(payload) + (payload.get("background") or []) if i.get("id") is not None}
    anchors = draft.get("anchors") or {}
    gone = {x: anchors[str(x)] for x in _draft_ids(draft["sections"]) if x not in known and str(x) in anchors}
    if not gone:
        return draft
    now = {r["id"]: r["canonical_id"] for r in store.rows(
        select(claims.c.id, claims.c.canonical_id).where(claims.c.id.in_(sorted(set(gone.values())))))}
    to = {x: now.get(c) for x, c in gone.items() if now.get(c) in known}
    if not to:
        return draft
    out = copy.deepcopy(draft)
    for _, para in out["sections"]:
        for sent in para or []:
            if isinstance(sent, dict):
                sent["ids"] = list(dict.fromkeys(to.get(x, x) for x in sent.get("ids") or []))
    log.info("draft: %d merged statements renamed (%s)", len(to), to)
    return out


MEDIA_WORDS = re.compile(r"(?i)\b(newspapers?|news ?papers?|channels?|editions?|circulat\w*|readership|widely read|"
                         r"most read|publish\w*|publications?|news agency|broadcaster|daily|founded|established in)\b")


def _express_report(store, story_id: int) -> str | None:
    """The text of the report(s) an express story was read from (for the desk's copy check)."""
    try:
        from . import heavy
        rows = store.rows(select(articles.c.id, *heavy.columns(store, "text"))
                          .where(articles.c.story_id == story_id, articles.c.extracted_at.is_not(None)))
        return "\n".join(r["text"] or "" for r in heavy.fill(store, rows, "text")) or None
    except Exception as e:  # noqa: BLE001 - a check, never a reason not to write
        log.info("express report text not loaded for story %s (%s)", story_id, str(e)[:80])
        return None


def drop_outlet_self_talk(payload: dict) -> int:
    """Statements a page says about its own publisher ("Hindustan was established in 1936 ... the second
    most widely read Hindi newspaper", Oct 7 2026, story 12687) are not the story: dropped by code when a
    statement names an outlet, speaks of it as a publication, and only that outlet reports it."""
    from .narrative import _known_outlets
    names = {s.get("outlet") for s in payload.get("sources") or [] if s.get("outlet")} | set(_known_outlets())
    names = {n for n in names if n and len(n) >= 4}

    def self_talk(i: dict) -> bool:
        text = i.get("text") or ""
        if not MEDIA_WORDS.search(text):
            return False
        hit = {n for n in names if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text)}
        # "Live Hindustan" reports on "Hindustan": the reporting outlets' names share a word with it
        by = {s.get("outlet") or "" for s in i.get("sources") or []}
        return bool(hit) and all(any(set(h.lower().split()) & set(b.lower().split()) for h in hit) for b in by if b)

    dropped = 0
    for key in ("undated", "established", "contested", "context"):
        keep = [i for i in payload.get(key) or [] if not self_talk(i)]
        dropped += len(payload.get(key) or []) - len(keep)
        payload[key] = keep
    payload["timeline"] = [[i for i in tier if not self_talk(i)] for tier in payload.get("timeline") or []]
    payload["timeline"] = [t for t in payload["timeline"] if t]
    if dropped:
        log.info("dropped %d statements a page made about its own publisher", dropped)
    return dropped


def link_updates(payload: dict, updates: dict) -> int:
    """An older figure and the newer one that replaced it (disputes.py: every report of the newer one
    came clearly later): both are written, together, the newest first ("the toll rose to 50; earlier
    reports put it at 40"); neither is a dispute, each keeps its own colour (owner, Oct 7 2026)."""
    items = {i["id"]: i for i in _all_items_of(payload) + list(payload.get("context") or [])}
    n = 0
    for old, new in updates.items():
        old, new = int(old), int(new)
        if old in items and new in items:
            items[new]["update_of"] = old
            items[old]["updated_by"] = new
            n += 1
    return n


SCHEDULED = re.compile(r"(?i)\b(?:is|are)\s+(?:scheduled|set|slated|due|expected|likely)\s+to\b|\bwill\s+(?:be\s+held|"
                       r"take\s+place|meet|hold|begin|start|be\s+convened|be\s+chaired|be\s+announced)\b|\bto\s+be\s+held\b")


def drop_past_schedules(payload: dict, now: dt.datetime | None = None) -> int:
    """A line saying something IS SCHEDULED or WILL happen, on a date that has passed, is left out (owner, Oct 9
    2026, story 13792: "The 57th GST Council meeting is scheduled to take place ... on Thursday, October 8",
    written after the meeting, from a report filed before it; the meeting's decisions are the story). A
    same-day line is left out only when another line of the story reports a decisive act with the same names
    (the thing happened). A line with no date is kept: code never guesses."""
    from .when import date_of, _nearest_year as nearest_year, _date
    _valid = lambda y, m, d: _date(y, m, d) is not None   # noqa: E731
    from .news import _start, act_score
    from .relate import Profile
    now = now or utcnow()
    today = (now + dt.timedelta(hours=5, minutes=30)).date()
    items = _all_items_of(payload) + list(payload.get("context") or [])
    done = [i for i in items if not SCHEDULED.search(i.get("text") or "") and act_score(i.get("text") or "") > 0]

    def when(i) -> dt.date | None:
        d = _start(i)
        if d:
            return d.date()
        # the nearest year, never the tense's: the line itself says "will", and the point is that its day has passed
        y, m, dd = date_of(i.get("text")) or (None, None, None)
        if m and dd:
            return dt.date(y, m, dd) if y and _valid(y, m, dd) else nearest_year(m, dd, today, None)
        return None
    gone = set()
    for i in items:
        if not SCHEDULED.search(i.get("text") or ""):
            continue
        d = when(i)
        if d is None or d > today:
            continue
        if d < today or any(Profile(i["text"]).names & Profile(j["text"]).names for j in done):
            gone.add(i["id"])
    if gone:
        for key in ("undated", "established", "contested", "context"):
            payload[key] = [i for i in payload.get(key) or [] if i["id"] not in gone]
        payload["timeline"] = [t for t in ([i for i in tier if i["id"] not in gone]
                                           for tier in payload.get("timeline") or []) if t]
        log.info("left out %d lines scheduling what has already happened", len(gone))
    return len(gone)


# words that only say HOW a thing was said, never what: a long line that differs from a short one by these (and the
# speaker's name) adds nothing (owner, Oct 11 2026: "J&K is integral, reiterating that J&K is integral, Bedi said")
SPEECH_ONLY = {"said", "say", "says", "stated", "state", "states", "added", "add", "adds", "noted", "note", "notes",
               "reiterated", "reiterate", "reaffirmed", "reaffirm", "repeated", "repeat", "stressed", "stress",
               "emphasised", "emphasized", "emphasise", "emphasize", "underlined", "underline", "asserted", "assert",
               "declared", "declare", "affirmed", "affirm", "maintained", "maintain", "insisted", "insist",
               "told", "remarked", "observed", "reportedly", "according", "saying", "adding", "stating", "noting"}
MIN_EXTRA_WORDS = 1     # content words beyond the short line (after speaker and speech words) that count as a detail


def _speech_stems(*texts: str) -> set[str]:
    """The words of these lines that only say HOW something was said: the verbs that report a clause (read from the parse:
    "said", "reiterating", "lamented") and their adverbs. SPEECH_ONLY is the fallback when a line cannot be parsed, and the
    audit counts the listed words the parse did not find (auditcount "speech_only")."""
    from . import auditcount, nlp
    from .frames import _stem
    listed = {_stem(w) for w in SPEECH_ONLY}
    found: set[str] = set()
    for text in texts:
        toks = nlp.parse(text)
        if not toks or not any(t.pos for t in toks):
            return listed
        for t in toks:
            if t.tag.startswith("VB") and any(c.head == t.i and c.dep == "ccomp" for c in toks):
                found |= {_stem(t.text.lower()), _stem(t.lemma)}
                found |= {_stem(c.text.lower()) for c in toks if c.head == t.i and c.dep == "advmod"}
    c = auditcount.counter("speech_only")
    c["texts"] += 1
    c["listed_not_found"] += len(listed & {_stem(w.lower()) for t in texts for w in re.findall(r"[A-Za-z]+", t)} - found)
    return found


def adds_detail(big: dict, small: dict) -> bool:
    """Does the detailed line say anything the short line does not? True for a number, a name (the speaker's own
    name aside) or MIN_EXTRA_WORDS content words more. A speaker and a speech verb are not a detail: the two lines are
    then one fact, and the long one (which keeps its speaker) tells it (fold_covered)."""
    from .frames import _stem
    from .relate import Profile
    pb, ps = Profile(big.get("text") or ""), Profile(small.get("text") or "")
    if pb.nums - ps.nums:
        return True
    skip = _speech_stems(big.get("text") or "", small.get("text") or "")
    for src in (big, small):
        skip |= {_stem(w.lower()) for w in re.findall(r"[A-Za-z][\w'-]*", str(src.get("speaker") or ""))}
    if (pb.names - ps.names - ps.roots) - skip:     # a name capitalised only by its place in the sentence is not new
        return True
    common = pb.names & ps.names
    extra = ((pb.roots - common) - (ps.roots - common)) - skip - pb.names
    return len(extra) >= MIN_EXTRA_WORDS


def fold_covered(payload: dict, covered: dict) -> int:
    """A line another line says in full, with more (relate.py), is not written on its own: its outlets
    are listed as sources of the detailed line, which keeps its own colour (it never borrows their
    support, so its extra details cannot turn green on another outlet's report)."""
    from .narrative import RANK, shade
    items = {i["id"]: i for i in _all_items_of(payload) + list(payload.get("context") or [])}
    gone = set()
    for small, big in covered.items():
        small, big = int(small), int(big)
        if small in items and big in items and small != big and big not in gone:
            # the short line is better supported than the detailed one (four outlets vs one): both are
            # kept and written as one sentence in two parts, so its fact can take its own colour
            # (owner, Oct 7 2026); otherwise there is nothing to gain and the short line folds away
            # ...but only when the detailed line really adds a fact (adds_detail): a speaker and a speech verb are
            # not one, and "X, adding that X, Bedi said" is the same fact written twice in two colours (owner,
            # Oct 11 2026); then it folds like any covered line
            if (RANK.get(shade(items[small]), 2) < RANK.get(shade(items[big]), 2) and not items[big].get("adds_to")
                    and adds_detail(items[big], items[small])):
                items[big]["adds_to"] = small
                continue
            have = {s["url"] for s in items[big].get("sources") or []}
            items[big]["sources"] = list(items[big].get("sources") or []) + [
                s for s in items[small].get("sources") or [] if s["url"] not in have]
            items[big].setdefault("covers_ids", []).append(small)
            # the independent outlets of the folded line, kept: shade() then shows "partial", not "one outlet only"
            # (owner, Oct 11 2026), when the sentence's own superscripts name more than one independent outlet
            items[big]["folded_groups"] = sorted(set(items[big].get("folded_groups") or [])
                                                 | {str(g) for g in items[small].get("groups") or []}
                                                 | ({str(g) for g in items[big].get("groups") or []}
                                                    if items[small].get("groups") else set()))
            gone.add(small)
    if gone:
        for key in ("undated", "established", "contested", "context"):
            payload[key] = [i for i in payload.get(key) or [] if i["id"] not in gone]
        payload["timeline"] = [t for t in ([i for i in tier if i["id"] not in gone]
                                           for tier in payload.get("timeline") or []) if t]
        log.info("%d lines folded into the more detailed lines that say them", len(gone))
    return len(gone)


def _all_items_of(payload: dict) -> list[dict]:
    out, seen = [], set()
    for tier in payload.get("timeline") or []:
        out += tier
    for k in ("undated", "established", "contested"):
        out += payload.get(k) or []
    return [i for i in out if not (id(i) in seen or seen.add(id(i)))]


# why the last publish_story call ended: the desk counts a try only when the writer was asked
# (Oct 7 2026: follow-up candidates refused before writing used up all five tries, two runs in a row)
LAST_OUTCOME: dict[str, str] = {}


RECENT_HEADLINE_DAYS = 7     # published headlines a new one must not repeat (owner, Oct 13 2026)
RECENT_HEADLINE_MAX = 400


def recent_headlines(store: Store, story_id: int, days: int = RECENT_HEADLINE_DAYS) -> list[str]:
    """English headlines published in the last `days` days (not this story's own), newest first."""
    since = utcnow() - dt.timedelta(days=days)
    rows = store.rows(select(published.c.headline_en).where(published.c.story_id != story_id,
                                                           published.c.updated_at >= since)
                      .order_by(published.c.updated_at.desc()).limit(RECENT_HEADLINE_MAX))
    return [r["headline_en"] for r in rows if r.get("headline_en")]


def _outcome(story_id: int, what: str, detail: dict | None = None) -> bool:
    LAST_OUTCOME.clear()
    LAST_OUTCOME.update(story=str(story_id), outcome=what, detail=detail)
    return what == "published"


def publish_story(store: Store, router: Router | None, story_id: int) -> bool:
    """Write the article, once (editions.py, owner Oct 5 2026). Only the writer produces prose: a story
    is published with a good essay or not at all (it waits; Oct 2026: 85 of 91 live pages were
    code-stitched and read like he-said-she-said). A published article is closed: this never changes
    it again (its colours mature by code, editions.mature). A development of an earlier article is
    judged like any story, only on what is new (followup.py). Returns True when written."""
    from .editions import judge_follow_up
    from .narrative import (essay_ok, essay_shortfall, input_hash, ordered_items, publish_bar, sections_from_payload,
                            write_narrative)
    if store.one(select(published.c.story_id).where(published.c.story_id == story_id)):
        return _outcome(story_id, "already published")
    from . import pagearchive
    try:
        payload = build_payload(store, router, story_id)
    except pagearchive.Unreachable as e:
        # the story's parent is on the archive branch and the branch could not be asked: written without the thread,
        # the article would be closed with no parent and would skip the follow-up check. It waits for the next run.
        log.warning("story %s waits: its parent page could not be fetched (%s)", story_id, e)
        return _outcome(story_id, "parent unreachable")
    store.exec(update(stories).where(stories.c.id == story_id).values(dirty=False))
    if payload is None:
        log.info("story %s waits: no longer qualifies", story_id)
        return _outcome(story_id, "no payload")
    # a failed headline before writing no longer stops the story (Oct 7 2026: the headline model was
    # overloaded and four stories a run were skipped): the headline is written again from the article's
    # lead below, and if that fails too the finished article waits as a kept draft
    from .spelling import unify_article, unify_payload
    drop_outlet_self_talk(payload)
    drop_past_schedules(payload)       # "is scheduled to" for what has already happened (owner, Oct 9 2026)
    from .belong import check as context_belongs
    context_belongs(store, router, story_id, payload)   # a line that is not about this story goes to "Also in these reports" (belong.py)
    an_ = (store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}).get("analysis") or {}
    fold_covered(payload, an_.get("covered") or {})
    link_updates(payload, an_.get("updates") or {})
    # a development of a published article is judged like any story, only on what is NEW (owner, Oct 27 2026): what the
    # parent already told is left out and the parent lines the article needs are chosen (followup.py). It waits only
    # while nothing in it is new, or while the check could not be asked. Before the cap, so told lines do not use it up,
    # and before the spelling pass and the lead, which then see only what is written.
    parents = [x["story_id"] for x in payload.get("parents") or []]
    if parents:
        from . import dossier, followup
        try:
            with _timed("follow_up"):
                fu = judge_follow_up(store, router, story_id, payload, parents)
                if fu.state == "judged" and fu.ok:
                    dossier.record(store, story_id, "followup", followup.apply(payload, fu))
        except pagearchive.Unreachable as e:
            log.warning("story %s waits: a parent page could not be fetched for the follow-up check (%s)", story_id, e)
            return _outcome(story_id, "parent unreachable")
        if fu.state == "unjudged":
            return _outcome(story_id, "follow-up not judged yet")
        if fu.state == "judged" and not fu.ok:
            return _outcome(story_id, "nothing new yet")
    payload["trimmed"] = trim_to_cap(payload)         # a very large story: the best-supported statements are written
    unify_payload(payload)                  # one spelling per name, before the writer sees the statements
    from .news import pick_news
    en_titles = [x["title"] for x in payload.get("sources") or [] if x.get("lang") == "en" and x.get("title")]
    payload["news"] = pick_news(ordered_items(payload), en_titles)[:3]   # again: folding can remove a statement
    from .news import lead_news
    payload["lead"] = lead_news(ordered_items(payload), en_titles)       # the news, and the fact of the day if another
    h = input_hash(sections_from_payload(payload), payload.get("background"))
    banned = set(payload["loaded_words"])
    if router is None:
        return _outcome(story_id, "no writer")
    if not _writer_attempt_allowed(store, story_id, h):
        return _outcome(story_id, "resting at the lowest bar")
    bar = publish_bar(_writer_tries(store, story_id))
    from .belong import assign_topics
    assign_topics(store, router, story_id, payload)     # one subject per paragraph (plan.py); no topics: shared words, as before
    # an earlier try that fell short of the bar is continued, not started again (owner, Oct 7 2026)
    an = (store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}).get("analysis") or {}
    draft = _remap_draft(store, an.get("writer_draft"), payload)
    report_text = _express_report(store, story_id) if payload.get("qualified_by") == "express" else None
    from . import bodies, crosslingual, names as _names
    try:
        crosslingual.use(_names.load(store))               # a Hindi speaker is the English entity the registry pairs it with
    except Exception:  # noqa: BLE001
        crosslingual.use(None)
    body_stats = bodies.prefetch(store, _speakers_of(payload))        # Wikidata: which body each speaker is
    from . import dossier
    dossier.record(store, story_id, "statements", {"items": dossier.statements_trace(ordered_items(payload)),
                                                   "bodies": body_stats, "qualified_by": payload.get("qualified_by")})
    with _timed("writer"):
        nar = write_narrative(router, payload, banned, draft=draft if _keepable({"model": (draft or {}).get("model"),
                                                                                 "paragraphs": [1]}) else None,
                              report_text=report_text, bar=bar)
    drafted = nar.pop("drafted", None)
    essay_good = essay_ok(nar, payload, bar) and _keepable(nar)
    dossier.record(store, story_id, "writer", {"model": nar.get("model"), "essay_good": bool(essay_good), "bar": bar,
                                               "plan": nar.get("plan"), "flow": nar.get("flow"), "refs": nar.get("refs"),
                                               "plural_bodies": nar.get("plural_bodies"),
                                               "shortfall": None if essay_good else essay_shortfall(nar, payload, bar)})
    if essay_good:
        from .news import write_headline
        lead = " ".join(x["text"] for x in (nar.get("paragraphs") or [[]])[0])
        items_ = {i["id"]: i for i in ordered_items(payload)}
        news = items_.get((payload.get("news") or [None])[0])
        lead_ids = payload.get("lead") or []                     # the news, and the fact of the day if another
        latest = items_.get(lead_ids[1]) if len(lead_ids) > 1 else None
        with _timed("headline"):
            payload["headline"] = write_headline(router, news, items_, lead, banned, payload.get("_thread_ctx") or "",
                                                 latest=latest, taken=recent_headlines(store, story_id),
                                                 parents=[x["headline"] for x in payload.get("parents") or []])
    headline_missing = essay_good and not payload.get("headline")
    if not essay_good or headline_missing:
        # which check failed, with the numbers (owner, Oct 11 2026, story 16981): kept with the failure and in the log
        short = essay_shortfall(nar, payload, bar)
        if not short["why"] and not _keepable(nar):
            short["why"] = "writer model not allowed"
        if not essay_good:
            nar["shortfall"] = short
            _note_writer_failure(store, story_id, h, nar)
        if drafted and _keepable({"model": nar.get("model"), "paragraphs": [1]}):   # a writer model's draft
            an = dict((store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}).get("analysis") or {})
            covered = len(set(nar.get("covers") or []))
            an["writer_draft"] = {"sections": drafted, "model": nar.get("model"), "covers": covered,
                                  "anchors": _draft_anchors(store, drafted),
                                  "at": utcnow().isoformat(timespec="minutes")}
            store.exec(update(stories).where(stories.c.id == story_id).values(analysis=an))
        if headline_missing:
            log.info("story %s waits: written, but no headline passed; its draft is kept", story_id)
            return _outcome(story_id, "headline failed")
        log.info("story %s waits: short of the bar (%s): %d of %d statements covered, %d needed; %d sentences, %d "
                 "rejected; model %s; its draft is kept", story_id, short["why"], short["covered"], short["total"],
                 short["need"], short["sentences"], short["rejected"], short["model"])
        return _outcome(story_id, "written short", short)
    if draft:
        an = dict((store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}).get("analysis") or {})
        an.pop("writer_draft", None)
        store.exec(update(stories).where(stories.c.id == story_id).values(analysis=an))
    payload["narrative"] = nar
    payload.pop("_thread_ctx", None)
    unify_article(payload)                  # and in what the writer and the headline model wrote
    from .style import polish
    polish(payload)                         # surnames after the first mention; varied "he said" (by code)
    from .categories import for_payload
    with _timed("categories"):
        cat = for_payload(router, payload)     # the site's sections; never holds the article back
    if cat is not None:                     # not asked (quota): categories.fill_live asks on a later run
        from .categories import take_places
        payload["places"] = take_places(cat, payload)   # where it happens, checked by code (places.py)
        payload["category"] = cat
    from .people import from_payload as people_of
    payload["people"] = people_of(payload)   # who it is about, by code (people.py): readers follow them
    now = utcnow()
    payload["written_at"] = now.isoformat(timespec="seconds")
    with _timed("translate"):
        hi = translate_payload(store, router, payload)
    payload["version"] = hi["version"] = 1
    store.exec(insert(published).values(story_id=story_id, version=1, updated_at=now, headline_en=payload["headline"],
                                        headline_hi=hi["headline"], payload_en=payload, payload_hi=hi))
    if parents:      # the parents' "Latest in this story" link points at this follow-up from now on
        try:
            from .editions import attach_children
            attach_children(store, only=parents)
        except Exception as e:  # noqa: BLE001 - a link never stops an article; the next run's pass does it
            log.warning("children of %s not attached: %s", parents, str(e)[:150])
    return _outcome(story_id, "published")


FLOOR_WAIT_HOURS = 3   # at the lowest bar a story is tried again only this often (it is never given up)


def _writer_tries(store: Store, story_id: int) -> int:
    """Failed writer tries of this story, whatever statements it had then: each one lowers the bar (publish_bar)."""
    a = ((store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}).get("analysis") or {})
    return int((a.get("writer_failures") or {}).get("n", 0) or 0)


def _writer_attempt_allowed(store: Store, story_id: int, h: str) -> bool:
    """A story is never given up (owner, Oct 16 2026): the bar falls with each try instead. Once it is at the floor,
    the same statements are tried again only every FLOOR_WAIT_HOURS; new statements are tried at once."""
    from .narrative import PUBLISH_FLOOR, publish_bar
    a = ((store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}).get("analysis") or {})
    w = a.get("writer_failures") or {}
    if publish_bar(int(w.get("n", 0) or 0)) > PUBLISH_FLOOR or w.get("hash") != h or not w.get("at"):
        return True
    try:
        at = dt.datetime.fromisoformat(w["at"])
    except ValueError:
        return True
    return utcnow() - at >= dt.timedelta(hours=FLOOR_WAIT_HOURS)


def _note_writer_failure(store: Store, story_id: int, h: str, nar: dict) -> None:
    """Remembered per statement set, with why, so a story the writer cannot do is not retried every
    hour (and the reasons are readable in the database). Quota is not a failure of the story."""
    if nar.get("failure") == "quota":
        return
    row = store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}
    a = dict(row.get("analysis") or {})
    w = a.get("writer_failures") or {}
    prev_n = int(w.get("n", 0) or 0)      # tries add up across statement sets: each lowers the bar
    # an overloaded or rate-limited model is not the story's fault: recorded, but no try is used up
    n = prev_n if str(nar.get("failure") or "").startswith("error") else prev_n + 1
    a["writer_failures"] = {"hash": h, "n": n, "model": nar.get("model"), "failure": nar.get("failure"),
                            "rejected": nar.get("rejected"), "reasons": nar.get("reject_reasons"),
                            "covers": len(nar.get("covers") or []), "shortfall": nar.get("shortfall"),
                            "at": utcnow().isoformat(timespec="minutes")}
    store.exec(update(stories).where(stories.c.id == story_id).values(analysis=a))

"""English-Hindi terms learned from the outlets (session 11 of the translation/learning plan, Oct 16 2026).

The Hindi page uses our binding terms (config/glossary.yaml `terms`, hindi.py) so a term is rendered one way. This
learner grows that list from evidence OUTSIDE our own output: never from our translations (a mistranslation the model
repeats would look like strong evidence and be made binding), only from Hindi and English outlets that covered the
same story, each in its own words.

PER STORY (the newsroom's last days, stories with 2+ independent English AND 2+ independent Hindi sources): an
English word counts when 2+ independent English sources used it in lower case (a common word, not a name); a Hindi
word when 2+ independent Hindi sources used it and it is not a name the registry knows. Stop words and numbers out.
ACROSS THE WINDOW'S STORIES: a pair counts when it appears together in 2+ stories, the two nearly always appear
together (Dice >= 0.6), each is the other's single best partner, and neither appears in over a quarter of the stories
(a common word goes with everything). Such a pair adds the story to its memory (learning.py), so evidence builds up
across runs and days.

THE BAR: 2+ independent English and 2+ independent Hindi sources, 3+ stories, 3+ days, no day over half.

CONTEXT (context.py, owner Oct 16 2026): partners are found within each SECTION, and inside a section each sighting
joins a SENSE by the words of its English sentence. One candidate per English word, sense and Hindi rendering:
"bank = बैंक" in markets and "bank = किनारा" in weather are two senses, never rivals. A learned term carries its
section and context words in the file and binds a translation only where a sentence's context matches it.

THE DEVIL'S ADVOCATE, code only (no model call):
  - BLOCK: the English word is a reading's loaded word or a qualifier (fidelity glossary); the Hindi word is a dispute
    or insult cue; on `rejected:`.
  - TO THE OWNER (proposed, not learned): a COMPETING rendering IN THE SAME SENSE (another Hindi word with at least
    half the stories: binding one would pick a side's usage); UNSTABLE (without its best day and its best source it
    no longer passes the bar); the Hindi word already bound to another English word in the same section.
  - Otherwise LEARNED automatically into config/glossary_learned.yaml `terms` (words and counts only, no article
    text: the repository is public). Hand-written terms in glossary.yaml always win; learned terms bind translations
    from the next run (fidelity.terms_in) but do not change the translation cache's version (owner, Oct 14 2026: no
    re-translation bill each time one is learned).
A WRONG ENTRY: delete its line and add the English word to `rejected:`. A proposal is approved by moving its line from
`proposed:` to `terms:` (glossary_learned.yaml holds both).

    python -m nishpaksh.learn_glossary [--days 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import learning as L

log = logging.getLogger(__name__)

FILE = "glossary_learned.yaml"
KIND = "glossary3"          # one candidate per English word, sense and Hindi rendering (context.py, Oct 16 2026)
LEGACY_KINDS = ("glossary", "glossary2")   # story-level pairs; then aligned pairs with no sense: removed
BAR = L.Bar(sources=4, stories=3, days=3, max_day_share=0.5)
MIN_SIDE_SOURCES = 2        # per language
MIN_STORY_SOURCES = 2       # independent sources of one language in one story
MIN_PAIR_STORIES = 2        # stories the pair shares within the window
DICE = 0.6
MAX_SHARE = 0.25            # of the window's stories: commoner words go with everything
MAX_NEW = 5
COMPETING = 0.5            # a rival rendering in the same sense with at least half the stories
# Clean pairs are learned automatically (owner, Oct 16 2026, once senses keep "bank" in its own context). A pair
# with a rival rendering in the same context, unstable evidence, or a Hindi word bound elsewhere waits for the owner.
AUTO_LEARN = True
CLEAN_PROPOSAL = "passed the bar and the devil's advocate: waiting for the owner"

HEADER = """# English-Hindi terms learned from the outlets by nishpaksh/learn_glossary.py (Oct 16 2026). Evidence: Hindi
# and English outlets covering the same stories, never our own translations. Hand-written terms in glossary.yaml
# always win. `terms:` bind our Hindi translations (fidelity.terms_in); `proposed:` wait for the owner (a competing
# rendering, unstable evidence, or a Hindi word already bound): to APPROVE, move the line to `terms:`.
# A WRONG ENTRY: delete its line and add its English word to `rejected:`.
rejected: []
"""

EN_STOP = set("""a an the of in on at to for from by with and or as is are was were be been being has have had its
his her their this that these those it they he she him them who which what when where while also said says told
will would could should may might can not no new news report reports reported according after before about over
under more than less most other some such into upon there here then than very only just even still said say people
year years day days week month time state government minister police court""".split())

HI_STOP = set("""है हैं था थे थी हो होने होगा होगी की का के को में से ने और पर यह वह इस उस इन उन ये वे कि भी तो ही
लिए गया गई गए किया की कर करने करते करता करती रहा रही रहे एक जो अपने अपनी अपना बताया कहा साथ बाद तक अब नहीं
लेकिन या जब तब यहां वहां कोई कुछ सभी बहुत दिया दी दिए लेकर बीच दौरान वाले वाली वाला ओर द्वारा इसके उसके उनके
इसकी उसकी उनकी जा सकता सकती सकते रूप तरह हुए हुई हुआ हुईं होते होती होता गयी गये रहें दें लिया ली लिये दिन साल समय सरकार मंत्री पुलिस कोर्ट""".split())

_EN_WORD = re.compile(r"(?<![\w-])[a-z][a-z-]{3,}(?![\w-])")
_HI_WORD = re.compile(r"[ऀ-ॣ॰-ॿ‌‍]{2,}")


# -- the owner's file ----------------------------------------------------------------------------------------------

def _doc(path: Path) -> dict:
    import yaml
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def learned_terms(path: Path | None = None) -> list[dict]:
    """The learned and approved terms with their context, for translations: [{en, hi, section, context}]. A term
    with no `section` and no `context` (one the owner wrote by hand here) applies everywhere."""
    from .config import CONFIG_DIR
    out = []
    for t in _doc(path or (CONFIG_DIR / FILE)).get("terms") or []:
        if isinstance(t, dict) and isinstance(t.get("en"), str) and isinstance(t.get("hi"), str):
            out.append({"en": t["en"], "hi": t["hi"], "section": str(t.get("section") or ""),
                        "context": [str(w) for w in t.get("context") or []]})
    return out


# -- per story and across stories (pure) --------------------------------------------------------------------------

def story_words(arts: list[dict], lang: str, names=None) -> dict[str, set[str]]:
    """{word: sources that used it} in one story's articles of one language, for words 2+ independent sources used.
    English: lower-case words (a name is capitalised); Hindi: words that are not names the registry knows."""
    by: dict[str, set[str]] = defaultdict(set)
    for a in arts:
        if not a.get("source"):
            continue
        text = a.get("text") or ""
        words = set(_EN_WORD.findall(text)) - EN_STOP if lang == "en" else set(_HI_WORD.findall(text)) - HI_STOP
        if lang == "hi" and names is not None:
            words = {w for w in words if names.english(w) is None}
        for w in words:
            by[w].add(a["source"])
    return {w: s for w, s in by.items() if len(s) >= MIN_STORY_SOURCES}


MAX_SENTENCES = 300         # per language per story


def _sentence_numbers(text: str) -> set[str]:
    """The numbers a sentence reports, by value in either script; small ones (under 10) say too little to align."""
    from .fidelity import numbers
    out = set()
    for v in numbers(text):
        try:
            if abs(float(v)) >= 10:
                out.add(v)
        except ValueError:
            continue
    return out


def aligned_pairs(en_arts: list[dict], hi_arts: list[dict], en_words: set[str], hi_words: set[str]) -> dict:
    """{(English word, Hindi word): [the English sentence's context words, ...]} for word pairs that stand in an
    English and a Hindi sentence of one story sharing a number (by value, any script): the two sentences report the
    same thing, so their words may translate each other; the English sentence is the pair's context there."""
    from . import context
    from .fidelity import sentences
    def sents(arts, words, rx, stop):
        out = []
        for a in arts:
            for s in sentences(a.get("text") or "")[:MAX_SENTENCES]:
                nums = _sentence_numbers(s)
                if nums:
                    ws = (set(rx.findall(s)) - stop) & words
                    if ws:
                        out.append((nums, ws, s))
        return out[:MAX_SENTENCES]
    en_s = sents(en_arts, en_words, _EN_WORD, EN_STOP)
    hi_s = sents(hi_arts, hi_words, _HI_WORD, HI_STOP)
    out: dict = {}
    for en_nums, en_ws, en_sent in en_s:
        for hi_nums, hi_ws, _ in hi_s:
            if en_nums & hi_nums:
                for e in en_ws:
                    ctx = context.words(en_sent, "en", e)
                    for h in hi_ws:
                        lst = out.setdefault((e, h), [])
                        if len(lst) < 5:
                            lst.append(ctx)
    return out


def pairs(stories: dict, names=None, sections: dict | None = None) -> tuple[list[dict], dict]:
    """From {story id: {"en": [articles], "hi": [articles]}} (each article: source, text, when): the pairs that pass
    within this window, as [{en, hi, section, stories: {story: (en sources, hi sources, when, [contexts])}}], and
    {(section, English word): {Hindi partner: Dice}}.

    Partners are found WITHIN EACH SECTION (context.section_of; "" for stories not yet published): "bank" pairs with
    बैंक in markets stories and with किनारा in weather stories, instead of one global best partner that would hide
    the second sense. Within a section, senses are told apart later by the sentence words (record)."""
    sections = sections or {}
    per_story, aligned = {}, {}
    for sid, s in stories.items():
        en, hi = story_words(s.get("en") or [], "en"), story_words(s.get("hi") or [], "hi", names)
        if en and hi:
            when = min((a.get("when") for a in (s.get("en") or []) + (s.get("hi") or []) if a.get("when")), default=None)
            per_story[sid] = (en, hi, when)
            aligned[sid] = aligned_pairs(s.get("en") or [], s.get("hi") or [], set(en), set(hi))
    groups: dict[str, list] = defaultdict(list)
    for sid in per_story:
        groups[sections.get(sid, "")].append(sid)
    out, partners_all = [], {}
    for section, sids in groups.items():
        n = len(sids)
        en_count, hi_count, both = Counter(), Counter(), Counter()
        for sid in sids:
            en, hi, _ = per_story[sid]
            en_count.update(list(en))
            hi_count.update(list(hi))
            # a pair counts in a story only when the two words stand in a Hindi and an English sentence that report
            # the same thing (they share a number): words that merely share a story ("rolls" / "ज्ञानेश") are not
            # translations of each other
            for pair in aligned[sid]:
                both[pair] += 1
        common = lambda c, w: c[w] / n > MAX_SHARE and n >= 8          # with few stories every word looks common
        best_hi: dict[str, tuple[float, str]] = {}
        best_en: dict[str, tuple[float, str]] = {}
        partners: dict[str, Counter] = defaultdict(Counter)
        for (e, h), k in both.items():
            if k < MIN_PAIR_STORIES:
                continue
            d = 2 * k / (en_count[e] + hi_count[h])
            partners[e][h] = d
            if d > best_hi.get(e, (0, ""))[0] or (d == best_hi.get(e, (0, ""))[0] and h < best_hi[e][1]):
                best_hi[e] = (d, h)
            if d > best_en.get(h, (0, ""))[0] or (d == best_en.get(h, (0, ""))[0] and e < best_en[h][1]):
                best_en[h] = (d, e)
        for e, (d, h) in best_hi.items():
            if d < DICE or best_en.get(h, (0, ""))[1] != e or common(en_count, e) or common(hi_count, h):
                continue
            if [x for x, v in partners[e].items() if x != h and v == d]:
                continue                                 # two equally good partners teach nothing
            st = {sid: (sorted(per_story[sid][0][e]), sorted(per_story[sid][1][h]), per_story[sid][2],
                        aligned[sid][(e, h)]) for sid in sids if (e, h) in aligned[sid]}
            out.append({"en": e, "hi": h, "section": section, "stories": st})
        for e, ps in partners.items():
            partners_all[(section, e)] = dict(ps)
    return out, partners_all


# -- senses (context.py): one candidate per English word, sense and Hindi rendering ---------------------------------

SENSE_KIND = "glossary_ctx"     # per English word: its senses (section + signature), in the newsroom


def cand_key(en: str, hi: str, sense: str) -> str:
    return f"{en} = {hi} @{sense}"


def split_key(key: str) -> tuple[str, str, str]:
    left, _, sense = key.partition(" @")
    en, _, hi = left.partition(" = ")
    return en, hi, sense


def load_senses(store) -> dict:
    """{English word: L.Candidate holding facets["senses"] = {sense key: Sense dict}}."""
    return L.load(store, SENSE_KIND)


def senses_of(holder: L.Candidate) -> dict:
    from .context import Sense
    return {k: Sense.from_dict(v) for k, v in (holder.facets.get("senses") or {}).items()}


def _keep_senses(holder: L.Candidate, senses: dict) -> None:
    holder.facets["senses"] = {k: v.to_dict() for k, v in senses.items()}
    holder.status = "learned"                   # the sense store itself never expires
    holder.dirty = True


def record(cands: dict, found: list[dict], sense_store: dict | None = None) -> int:
    """Add the window's pairs to memory, each story's sighting under the SENSE its context belongs to (context.assign:
    the story's section and the English sentence's words). A sighting that shows two senses are one merges their
    candidates."""
    from . import context
    sense_store = sense_store if sense_store is not None else {}
    n = 0
    for p in found:
        e, h, section = p["en"], p["hi"], p.get("section", "")
        holder = sense_store.get(e)
        if holder is None:
            holder = sense_store[e] = L.Candidate(SENSE_KIND, e)
        senses = senses_of(holder)
        for sid, (en_src, hi_src, when, contexts) in p["stories"].items():
            ws = set().union(*contexts) if contexts else set()
            before = set(senses)
            counter = [int(holder.facets.get("next") or 0)]

            def new_key():
                counter[0] += 1
                return f"{e}#{counter[0]}"
            sense = context.assign(senses, section, ws, new_key)
            holder.facets["next"] = counter[0]
            for gone in before - set(senses):            # merged into `sense`: their candidates join it
                for key in [k for k in cands if split_key(k)[0] == e and split_key(k)[2] == gone]:
                    _merge_into(cands, key, cand_key(*split_key(key)[:2], sense))
            key = cand_key(e, h, sense)
            c = cands.get(key)
            if c is None:
                c = cands[key] = L.Candidate(KIND, key)
            new = False
            for src in en_src + hi_src:
                if c.add(f"{sid}:{src}", src, sid, L.day_of(when), when):
                    new = True
            if new:
                n += 1
                for src in en_src:
                    c.put("en_sources", src)
                for src in hi_src:
                    c.put("hi_sources", src)
                if section:
                    c.facets["section"] = section
        _keep_senses(holder, senses)
    return n


def _merge_into(cands: dict, old: str, new: str) -> None:
    a = cands.pop(old)
    b = cands.get(new)
    if b is None:
        a.key = new
        a.dirty = True
        cands[new] = a
        return
    b.sources = list(dict.fromkeys(b.sources + a.sources))[-L.KEEP:]
    b.stories = list(dict.fromkeys(b.stories + a.stories))[-L.KEEP:]
    b.articles = list(dict.fromkeys(b.articles + a.articles))[-L.KEEP:]
    for d, k in a.days.items():
        b.days[d] = b.days.get(d, 0) + k
    for f in ("en_sources", "hi_sources"):
        b.facets[f] = list(dict.fromkeys((b.facets.get(f) or []) + (a.facets.get(f) or [])))
    b.first_seen = min(filter(None, [a.first_seen, b.first_seen]), default=None)
    b.last_seen = max(filter(None, [a.last_seen, b.last_seen]), default=None)
    b.dirty = True
    a.status = "merged"
    a.dirty = True
    cands["__merged__" + old] = a           # kept until saved, so its row is deleted (learning.save)


# -- the bar and the devil's advocate (pure, code only) -----------------------------------------------------------

def extra_rules(c: L.Candidate) -> list[str]:
    out = []
    if len(c.facets.get("en_sources") or []) < MIN_SIDE_SOURCES:
        out.append("en_sources")
    if len(c.facets.get("hi_sources") or []) < MIN_SIDE_SOURCES:
        out.append("hi_sources")
    return out


def _without_best(c: L.Candidate) -> L.Candidate:
    """The candidate without its best day and its best source: does the pair still stand?"""
    d = dict(c.days)
    if d:
        d.pop(max(d, key=d.get))
    srcs = list(c.sources)
    if srcs:
        srcs.pop(0)
    return L.Candidate(c.kind, c.key, srcs, c.stories, d, facets=c.facets, first_seen=c.first_seen, last_seen=c.last_seen)


def rivals(c: L.Candidate, cands: dict) -> list[str]:
    """Other Hindi renderings of the same English word IN THE SAME SENSE with at least half this one's stories: two
    renderings in use in one context. A rendering in another sense is not a rival (बैंक in markets, किनारा in
    weather)."""
    en, hi, sense = split_key(c.key)
    out = []
    for k, o in cands.items():
        e2, h2, s2 = split_key(k)
        if o is not c and e2 == en and s2 == sense and h2 != hi and o.status != "merged" \
                and len(o.stories) >= COMPETING * max(1, len(c.stories)):
            out.append(h2)
    return sorted(set(out))


def advocate(c: L.Candidate, loaded=frozenset(), cands: dict | None = None, bound: dict | None = None,
             struck=frozenset()) -> L.Verdict:
    """Block (never learned), hold (a proposal for the owner, not binding), or clear."""
    from . import fidelity
    en, hi, sense = split_key(c.key)
    section = c.facets.get("section", "")
    if en.lower() in struck:
        return L.Verdict("block", "refused by the owner")
    if en in loaded:
        return L.Verdict("block", "a reading tagged the English word as loaded")
    if any(en in q.en or any(en == w for p in q.en for w in p.split()) for q in fidelity.glossary()["qualifiers"]):
        return L.Verdict("block", "a word that limits a claim: the fidelity glossary keeps it")
    if L.cue_pattern("dispute").search(hi):
        return L.Verdict("block", "the Hindi word is a dispute or insult cue")
    r = rivals(c, cands or {})
    if r:
        return L.Verdict("hold", f"a competing Hindi rendering in the same context: {', '.join(r[:3])}")
    other = (bound or {}).get((section, hi))
    if other and other != en:
        return L.Verdict("hold", f"the Hindi word is already bound to '{other}' in this section")
    if BAR.fails(_without_best(c)):
        return L.Verdict("hold", "unstable: without its best day and best source it no longer passes")
    return L.CLEAR


def decide(cands: dict, loaded=frozenset(), bound=None, struck=frozenset(), hand=frozenset(), now=None,
           approved=frozenset()) -> tuple[list, list]:
    """(newly learned, newly proposed to the owner), sense by sense. Holds become proposals once the bar is met.
    `approved`: (English, Hindi, section) the owner moved to `terms:`."""
    now = now or dt.datetime.utcnow()
    learned, proposed = [], []
    bound = dict(bound or {})

    def mark(c, **kw):
        for k, v in kw.items():
            setattr(c, k, v)
        c.checked_at, c.dirty = now, True

    for c in sorted([c for c in cands.values() if c.status != "merged"], key=lambda x: (-len(x.stories), x.key)):
        en, hi, sense = split_key(c.key)
        section = c.facets.get("section", "")
        if en.lower() in struck:                         # the owner's word wins, whatever the status
            if c.status != "blocked":
                mark(c, status="blocked", verdict="block", reason="refused by the owner")
            continue
        if (en, hi, section) in approved:                # the owner moved a proposal to `terms:`
            if c.status != "learned":
                mark(c, status="learned", verdict="clear", reason="approved by the owner")
            continue
        if c.status in ("blocked", "learned"):
            continue
        v = advocate(c, loaded, cands, bound, struck)
        if v.state == "block":
            mark(c, status="blocked", verdict="block", reason=v.reason)
            continue
        if en in hand or BAR.fails(c) or extra_rules(c):
            continue
        if v.state == "hold":
            if c.status != "proposed" or c.reason != v.reason:
                mark(c, status="proposed", verdict="hold", reason=v.reason)
                proposed.append(c)
            continue
        if not AUTO_LEARN:
            if c.status != "proposed":
                mark(c, status="proposed", verdict="clear", reason=CLEAN_PROPOSAL)
                proposed.append(c)
            continue
        if len(learned) >= MAX_NEW:
            continue
        mark(c, status="learned", verdict="clear", reason="passed the bar and the devil's advocate")
        bound[(section, hi)] = en
        learned.append(c)
    return learned, proposed


# -- the file ------------------------------------------------------------------------------------------------------

CONTEXT_WORDS = 12          # signature words written per learned sense


def _entry(c: L.Candidate, today: dt.date, sense_store: dict, reason: str = "") -> dict:
    from .context import Sense
    en, hi, sense = split_key(c.key)
    holder = sense_store.get(en)
    s = Sense.from_dict((holder.facets.get("senses") or {}).get(sense)) if holder else Sense()
    ctx = sorted(s.signature(), key=lambda w: (-s.counts.get(w, 0), w))[:CONTEXT_WORDS]
    e = {"en": en, "hi": hi, "section": s.section or c.facets.get("section", ""), "context": ctx,
         "learned": today.isoformat(), "stories": len(c.stories), "days": len(c.days),
         "en_sources": len(c.facets.get("en_sources") or []), "hi_sources": len(c.facets.get("hi_sources") or [])}
    if reason:
        e["why"] = reason
    return e


def _flow(e: dict) -> str:
    return "  - {" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in e.items()) + "}\n"


def write(path: Path, cands: dict, today: dt.date, sense_store: dict | None = None) -> None:
    """The file from the memory: rejected words as the owner left them, learned terms with their context, proposals.
    Lines the owner moved from `proposed:` to `terms:` are kept as terms."""
    sense_store = sense_store or {}
    doc = _doc(path) if path.exists() else {}
    struck = [str(x) for x in doc.get("rejected") or []]
    gone = {split_key(c.key)[:2] + (c.facets.get("section", ""),) for c in cands.values() if c.status == "blocked"}
    owner_terms = [t for t in doc.get("terms") or [] if isinstance(t, dict) and t.get("en") and t.get("hi")
                   and (t["en"], t["hi"], t.get("section", "")) not in gone]
    have = {(t["en"], t["hi"], t.get("section", "")) for t in owner_terms}
    body = HEADER.replace("rejected: []", "rejected: " + json.dumps(struck, ensure_ascii=False))
    live = [c for c in sorted(cands.values(), key=lambda c: c.key) if c.status != "merged"]
    terms = [_flow(t) for t in owner_terms]
    terms += [_flow(_entry(c, today, sense_store)) for c in live if c.status == "learned"
              and split_key(c.key)[:2] + (c.facets.get("section", ""),) not in have]
    props = [_flow(_entry(c, today, sense_store, c.reason)) for c in live if c.status == "proposed"
             and split_key(c.key)[:2] + (c.facets.get("section", ""),) not in have]
    body += "\n" + (("terms:\n" + "".join(terms)) if terms else "terms: []\n")
    body += "\n" + (("proposed:\n" + "".join(props)) if props else "proposed: []\n")
    path.write_text(body, encoding="utf-8")


# -- the run -------------------------------------------------------------------------------------------------------

def _drop_legacy(store) -> None:
    """Memory under earlier rules (story-level pairs; then pairs with no sense) is not evidence under the current one."""
    from sqlalchemy import delete
    from .db import learn_candidates as t
    try:
        store.exec(delete(t).where(t.c.kind.in_(LEGACY_KINDS)))
    except Exception as e:  # noqa: BLE001
        log.info("glossary: legacy rows not removed (%s)", str(e)[:80])


def run(store, days: float = 3, dry_run: bool = False, path: Path | None = None) -> dict:
    from . import context, fidelity, heavy, names as N
    from .config import CONFIG_DIR
    from .db import articles, claims, select
    path = path or (CONFIG_DIR / FILE)
    now = dt.datetime.utcnow()
    since = now - dt.timedelta(days=days)
    rows = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.wire_group,
                             articles.c.lang, articles.c.story_id, articles.c.published_at,
                             *heavy.columns(store, "text"))
                      .where(articles.c.published_at >= since, articles.c.story_id.is_not(None)))
    rows = [r for r in heavy.fill(store, rows, "text") if r.get("text")]
    stories: dict[int, dict] = defaultdict(lambda: {"en": [], "hi": []})
    for r in rows:
        lang = "hi" if r.get("lang") == "hi" else "en"
        stories[r["story_id"]][lang].append({"source": N.source_key(r), "text": r["text"], "when": r.get("published_at")})
    stories = {sid: s for sid, s in stories.items()
               if len({a["source"] for a in s["en"] if a["source"]}) >= MIN_STORY_SOURCES
               and len({a["source"] for a in s["hi"] if a["source"]}) >= MIN_STORY_SOURCES}
    loaded_tags: list[str] = []
    ids = [r["id"] for r in rows]
    for start in range(0, len(ids), 400):
        for c in store.rows(select(claims.c.loaded_words).where(claims.c.article_id.in_(ids[start:start + 400]))):
            for w in c.get("loaded_words") or []:
                loaded_tags.extend(x.lower() for x in str(w).split())
    sections = context.story_sections(store, stories)
    found, _ = pairs(stories, N.load(store), sections)
    if not dry_run:
        _drop_legacy(store)
    cands = L.load(store, KIND)
    sense_store = load_senses(store)
    new = record(cands, found, sense_store)
    doc = _doc(path) if path.exists() else {}
    struck = {str(x).lower() for x in doc.get("rejected") or []}
    hand = {en.lower() for en, _ in fidelity.glossary()["terms"]}
    bound = {(c.facets.get("section", ""), split_key(c.key)[1]): split_key(c.key)[0]
             for c in cands.values() if c.status == "learned"}
    approved = {(t["en"], t["hi"], t.get("section", "")) for t in doc.get("terms") or [] if isinstance(t, dict)}
    loaded = L.loaded_set(loaded_tags)
    learned, proposed = decide(cands, loaded, bound, struck, hand, now, approved)
    live = [c for c in cands.values() if c.status != "merged"]
    out = {"articles": len(rows), "mixed_stories": len(stories), "pairs_in_window": len(found), "new_evidence": new,
           "candidates": len(live), "senses": sum(len(h.facets.get("senses") or {}) for h in sense_store.values()),
           "funnel": L.funnel(live, BAR, extra_rules), "near": L.near(live, BAR, extra_rules),
           "learned_now": [c.key for c in learned], "proposed_now": [c.key for c in proposed]}
    if dry_run:
        return out
    out.update(L.save(store, cands, now))
    L.save(store, sense_store, now)
    write(path, cands, now.date(), sense_store)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=float, default=3)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .config import database_url
    from .db import Store
    store = Store(database_url())
    store.init()
    res = run(store, a.days, a.dry_run)
    log.info("glossary candidates: %s", res.get("funnel"))
    print(json.dumps(res, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

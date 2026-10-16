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

THE DEVIL'S ADVOCATE, code only (no model call):
  - BLOCK: the English word is a reading's loaded word or a qualifier (fidelity glossary); the Hindi word is a dispute
    or insult cue; on `rejected:`.
  - TO THE OWNER (proposed, not learned): a COMPETING rendering (another Hindi word as strongly tied to the same English word,
    Dice >= 0.6: binding one would pick a side's usage); UNSTABLE (without its best day and its best
    source it no longer passes the bar); the Hindi word already bound to another English word.
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
KIND = "glossary"
BAR = L.Bar(sources=4, stories=3, days=3, max_day_share=0.5)
MIN_SIDE_SOURCES = 2        # per language
MIN_STORY_SOURCES = 2       # independent sources of one language in one story
MIN_PAIR_STORIES = 2        # stories the pair shares within the window
DICE = 0.6
MAX_SHARE = 0.25            # of the window's stories: commoner words go with everything
MAX_NEW = 5

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
इसकी उसकी उनकी जा सकता सकती सकते रूप तरह दिन साल समय सरकार मंत्री पुलिस कोर्ट""".split())

_EN_WORD = re.compile(r"(?<![\w-])[a-z][a-z-]{3,}(?![\w-])")
_HI_WORD = re.compile(r"[ऀ-ॣ॰-ॿ‌‍]{2,}")


# -- the owner's file ----------------------------------------------------------------------------------------------

def _doc(path: Path) -> dict:
    import yaml
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def learned_terms(path: Path | None = None) -> list[tuple[str, str]]:
    """(English, Hindi) of the learned and approved terms, for translations."""
    from .config import CONFIG_DIR
    out = []
    for t in _doc(path or (CONFIG_DIR / FILE)).get("terms") or []:
        if isinstance(t, dict) and isinstance(t.get("en"), str) and isinstance(t.get("hi"), str):
            out.append((t["en"], t["hi"]))
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


def pairs(stories: dict, names=None) -> tuple[list[dict], dict]:
    """From {story id: {"en": [articles], "hi": [articles]}} (each article: source, text, when): the pairs that
    pass within this window, as [{en, hi, stories: {story: (en sources, hi sources, when)}}], and {English word:
    {Hindi partner: Dice}} (for competing renderings)."""
    per_story = {}
    for sid, s in stories.items():
        en, hi = story_words(s.get("en") or [], "en"), story_words(s.get("hi") or [], "hi", names)
        if en and hi:
            when = min((a.get("when") for a in (s.get("en") or []) + (s.get("hi") or []) if a.get("when")), default=None)
            per_story[sid] = (en, hi, when)
    n = len(per_story)
    if not n:
        return [], {}
    en_count, hi_count, both = Counter(), Counter(), Counter()
    for en, hi, _ in per_story.values():
        en_count.update(list(en))
        hi_count.update(list(hi))
        for e in en:
            for h in hi:
                both[(e, h)] += 1
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
    out = []
    for e, (d, h) in best_hi.items():
        if d < DICE or best_en.get(h, (0, ""))[1] != e or common(en_count, e) or common(hi_count, h):
            continue
        ties = [x for x, v in partners[e].items() if x != h and v == d]
        if ties:
            continue                                     # two equally good partners teach nothing
        st = {sid: (sorted(per_story[sid][0][e]), sorted(per_story[sid][1][h]), per_story[sid][2])
              for sid in per_story if e in per_story[sid][0] and h in per_story[sid][1]}
        out.append({"en": e, "hi": h, "stories": st})
    return out, partners


def record(cands: dict, found: list[dict]) -> int:
    n = 0
    for p in found:
        key = f"{p['en']} = {p['hi']}"
        c = cands.get(key)
        if c is None:
            c = cands[key] = L.Candidate(KIND, key)
        for sid, (en_src, hi_src, when) in p["stories"].items():
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
    return n


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


def advocate(c: L.Candidate, loaded=frozenset(), partners: dict | None = None, bound: dict[str, str] | None = None,
             struck=frozenset()) -> L.Verdict:
    """Block (never learned), "owner" (a proposal for the owner, not learned), or clear."""
    from . import fidelity
    en, hi = c.key.split(" = ", 1)
    if en in struck:
        return L.Verdict("block", "refused by the owner")
    if en in loaded:
        return L.Verdict("block", "a reading tagged the English word as loaded")
    if any(en in q.en or any(en == w for p in q.en for w in p.split()) for q in fidelity.glossary()["qualifiers"]):
        return L.Verdict("block", "a word that limits a claim: the fidelity glossary keeps it")
    if L.cue_pattern("dispute").search(hi):
        return L.Verdict("block", "the Hindi word is a dispute or insult cue")
    if partners and en in partners:
        # another Hindi word as strongly tied to the English one (Dice): two renderings in use
        rivals = [x for x, v in partners[en].items() if x != hi and v >= DICE]
        if rivals:
            return L.Verdict("hold", f"a competing Hindi rendering: {', '.join(sorted(rivals)[:3])}")
    if bound and bound.get(hi) and bound[hi] != en:
        return L.Verdict("hold", f"the Hindi word is already bound to '{bound[hi]}'")
    if BAR.fails(_without_best(c)):
        return L.Verdict("hold", "unstable: without its best day and best source it no longer passes")
    return L.CLEAR


def decide(cands: dict, loaded=frozenset(), partners=None, bound=None, struck=frozenset(), hand=frozenset(),
           now=None, approved=frozenset()) -> tuple[list, list]:
    """(newly learned, newly proposed to the owner). Holds become proposals once the bar is met."""
    now = now or dt.datetime.utcnow()
    learned, proposed = [], []
    bound = dict(bound or {})

    def mark(c, **kw):
        for k, v in kw.items():
            setattr(c, k, v)
        c.checked_at, c.dirty = now, True

    for c in sorted(cands.values(), key=lambda x: (-len(x.stories), x.key)):
        en, hi = c.key.split(" = ", 1)
        if en.lower() in struck:                         # the owner's word wins, whatever the status
            if c.status != "blocked":
                mark(c, status="blocked", verdict="block", reason="refused by the owner")
            continue
        if c.key in approved:                            # the owner moved a proposal to `terms:`
            if c.status != "learned":
                mark(c, status="learned", verdict="clear", reason="approved by the owner")
            continue
        if c.status in ("blocked", "learned"):
            continue
        v = advocate(c, loaded, partners, bound, struck)
        if v.state == "block":
            mark(c, status="blocked", verdict="block", reason=v.reason)
            continue
        if en in hand or BAR.fails(c) or extra_rules(c):
            continue
        if v.state == "hold":
            if c.status != "proposed":
                mark(c, status="proposed", verdict="hold", reason=v.reason)
                proposed.append(c)
            continue
        if len(learned) >= MAX_NEW:
            continue
        mark(c, status="learned", verdict="clear", reason="passed the bar and the devil's advocate")
        bound[hi] = en
        learned.append(c)
    return learned, proposed


# -- the file ------------------------------------------------------------------------------------------------------

def _line(c: L.Candidate, today: dt.date, reason: str = "") -> str:
    en, hi = c.key.split(" = ", 1)
    e = {"en": en, "hi": hi, "learned": today.isoformat(), "stories": len(c.stories), "days": len(c.days),
         "en_sources": len(c.facets.get("en_sources") or []), "hi_sources": len(c.facets.get("hi_sources") or [])}
    if reason:
        e["why"] = reason
    return "  - {" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in e.items()) + "}\n"


def write(path: Path, cands: dict, today: dt.date) -> None:
    """The file from the memory: rejected words as the owner left them, learned terms, proposals. Lines the owner
    moved from `proposed:` to `terms:` are kept as terms."""
    doc = _doc(path) if path.exists() else {}
    struck = [str(x) for x in doc.get("rejected") or []]
    gone = {c.key for c in cands.values() if c.status == "blocked"}
    owner_terms = [t for t in doc.get("terms") or [] if isinstance(t, dict) and t.get("en") and t.get("hi")
                   and f"{t['en']} = {t['hi']}" not in gone]
    have = {f"{t['en']} = {t['hi']}" for t in owner_terms}
    body = HEADER.replace("rejected: []", "rejected: " + json.dumps(struck, ensure_ascii=False))
    lines_t = ["  - {" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in t.items()) + "}\n"
               for t in owner_terms]
    lines_t += [_line(c, today) for c in sorted(cands.values(), key=lambda c: c.key)
                if c.status == "learned" and c.key not in have]
    lines_p = [_line(c, today, c.reason) for c in sorted(cands.values(), key=lambda c: c.key)
               if c.status == "proposed" and c.key not in have]
    body += "\n" + (("terms:\n" + "".join(lines_t)) if lines_t else "terms: []\n")
    body += "\n" + (("proposed:\n" + "".join(lines_p)) if lines_p else "proposed: []\n")
    path.write_text(body, encoding="utf-8")


# -- the run -------------------------------------------------------------------------------------------------------

def run(store, days: float = 3, dry_run: bool = False, path: Path | None = None) -> dict:
    from . import fidelity, heavy, names as N
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
    loaded: set[str] = set()
    ids = [r["id"] for r in rows]
    for start in range(0, len(ids), 400):
        for c in store.rows(select(claims.c.loaded_words).where(claims.c.article_id.in_(ids[start:start + 400]))):
            for w in c.get("loaded_words") or []:
                loaded.update(x.lower() for x in str(w).split())
    found, partners = pairs(stories, N.load(store))
    cands = L.load(store, KIND)
    new = record(cands, found)
    doc = _doc(path) if path.exists() else {}
    struck = {str(x).lower() for x in doc.get("rejected") or []}
    hand = {en.lower() for en, _ in fidelity.glossary()["terms"]}
    bound = {c.key.split(" = ", 1)[1]: c.key.split(" = ", 1)[0] for c in cands.values() if c.status == "learned"}
    approved = {f"{t['en']} = {t['hi']}" for t in doc.get("terms") or [] if isinstance(t, dict)}
    learned, proposed = decide(cands, loaded, partners, bound, struck, hand, now, approved)
    out = {"articles": len(rows), "mixed_stories": len(stories), "pairs_in_window": len(found), "new_evidence": new,
           "candidates": len(cands), "funnel": L.funnel(cands.values(), BAR, extra_rules),
           "learned_now": [c.key for c in learned], "proposed_now": [c.key for c in proposed]}
    if dry_run:
        return out
    out.update(L.save(store, cands, now))
    write(path, cands, now.date())
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

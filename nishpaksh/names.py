"""The name registry: each part of a name (Rahul, Sharma, Rimpochee) in English and in Hindi (owner, Oct 15 2026).

Why: a Hindi outlet's name came back from the reading model spelt its own way ("Rimpoche" beside the English outlets'
"Rimpochee"), so the same fact from a Hindi and an English outlet did not merge; and English-only stories reached
the Hindi page with names left in Latin letters ("Amrit Vats ने Djibouti में ...").

The owner's rules, all kept here:
  * EXACT ONLY. A part is looked up by exactly the spelling given; no similarity, no guessing ("Shrma" is unknown,
    not "Sharma"). The one allowance: Hindi variants that are the same letters (गांधी / गाँधी, ज़ / ज) are one
    form for counting, shown in the spelling most outlets used (`fold_hi`).
  * THE OUTLETS' OWN WORDS. Both spellings of a pair are copied from outlets that covered the same story; we learn
    words only where a story has both Hindi and English sources. In each language the spelling most independent
    sources used wins.
  * TRUST BAR. A pair is "attested" once 2+ independent English sources and 2+ independent Hindi sources used exactly
    those spellings, in 2+ different stories. Below that it is "seen": usable, low trust.
  * FALLBACK. A part no outlet pair covers is transliterated by one batched call on the quality tier (the Translator
    key), marked "translated", and replaced as soon as outlets show their own spellings. Nothing here spends the
    publication quota; with no quality quota, a part simply stays unknown.
  * MANUAL. config/names.yaml holds the owner's own pairs; they always win. The Hindi state names in places.py seed
    the registry the same way (the owner's table).

Pure code over plain values (`Registry`), with thin database wrappers (`load`, `save`, `resolve`). Who pairs the
parts of a story (session 4: before reading) and who uses the Hindi forms (the Hindi page) is not here.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import pathlib
import re
import unicodedata

import yaml

log = logging.getLogger(__name__)
MANUAL_FILE = pathlib.Path(__file__).resolve().parent.parent / "config" / "names.yaml"
MIN_EN_SOURCES = 2          # the trust bar (owner, Oct 15 2026)
MIN_HI_SOURCES = 2
MIN_STORIES = 2
KEEP = 50                   # evidence kept per pair and side: the bar needs 2, the vote a handful
MAX_PER_CALL = 40           # parts per transliteration call

RANK = {"manual": 4, "attested": 3, "seen": 2, "translated": 1}

_DEV = re.compile(r"[ऀ-ॿ]")
_HI_PART = re.compile(r"[ऀ-ॣ॰-ॿ‌‍]+(?:-[ऀ-ॣ॰-ॿ‌‍]+)*")
# a capital first ("Rimpochee", "O'Brien", "Aisam-ul-Haq", "Jr."), or a short particle in front ("al-Hammami");
# the particles of names on their own ("bin", "van", "de") are parts too
_EN_PART = re.compile(r"(?:[a-z]{1,3}-)?[A-Z][A-Za-z'’]*(?:-[A-Za-z'’]+)*\.?")
PARTICLES = {"bin", "bint", "ibn", "al", "el", "van", "von", "der", "de", "da", "di", "du", "la", "le", "ul", "ud"}
_EDGE = "\"'‘’“”.,;:!?()[]{}।॥"


# -- parts -----------------------------------------------------------------------------------------------------------

def parts(name: str) -> list[str]:
    """A full name's parts as written: "Kushok Bakula Rimpochee" -> 3 parts; "Modi's" -> "Modi"; a hyphenated
    part ("Aisam-ul-Haq") stays one part. Nothing is respelt."""
    out = []
    for w in (name or "").split():
        w = w.strip(_EDGE)
        w = re.sub(r"(?:'s|’s)$", "", w)
        if w:
            out.append(w)
    return out


def pair_parts(en_name: str, hi_name: str) -> list[tuple[str, str]]:
    """Part-by-part pairs of one name in both languages, only when both have the same number of parts (owner,
    Oct 15 2026: a lone surname is paired only with a lone surname). Otherwise nothing: never forced."""
    e, h = parts(en_name), parts(hi_name)
    if not e or len(e) != len(h):
        return []
    if not all(valid_en(x) for x in e) or not all(valid_hi(x) for x in h):
        return []
    return list(zip(e, h))


def valid_hi(part: str) -> bool:
    """One Hindi name part: Devanagari letters only (a hyphen between them allowed)."""
    return bool(part) and _HI_PART.fullmatch(part) is not None


def valid_en(part: str) -> bool:
    """One English name part: Latin letters, starting with a capital ("Rimpochee", "O'Brien", "Aisam-ul-Haq", "Jr.")."""
    return bool(part) and (_EN_PART.fullmatch(part) is not None or part in PARTICLES)


def fold_hi(part: str) -> str:
    """The key Hindi spellings of one name are counted under: chandrabindu as anusvara (गाँधी = गांधी), no nukta
    (ज़ = ज), no zero-width joiners. Only for counting; what is shown is a spelling an outlet wrote."""
    s = unicodedata.normalize("NFD", part or "")
    s = s.replace("़", "").replace("ँ", "ं").replace("‌", "").replace("‍", "")
    return unicodedata.normalize("NFC", s)


def source_key(article: dict) -> str | None:
    """One independent source, the same in every story (wire.independence_groups works within one story only):
    an agency byline is the agency, a copied wire text its wire group, otherwise the outlet's owner. State media
    is a government speaking, never an independent source (None)."""
    from .ownership import owner_of, state_government
    if state_government(article.get("outlet"), article.get("url"), article.get("agency")):
        return None
    if article.get("agency"):
        return "agency:" + str(article["agency"]).strip().lower()
    if article.get("wire_group") is not None:
        return f"wire:{article['wire_group']}"
    owner = owner_of(article.get("outlet"), article.get("url"))
    return "owner:" + str(owner or article.get("outlet") or "").strip().lower() if (owner or article.get("outlet")) else None


# -- the registry ----------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Pair:
    en: str
    hi: str
    origin: str = "outlet"                      # outlet / api / manual
    en_sources: list = dataclasses.field(default_factory=list)
    hi_sources: list = dataclasses.field(default_factory=list)
    stories: list = dataclasses.field(default_factory=list)
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None

    @property
    def status(self) -> str:
        if self.origin == "manual":
            return "manual"
        if self.origin == "api":
            return "translated"
        if (len(self.en_sources) >= MIN_EN_SOURCES and len(self.hi_sources) >= MIN_HI_SOURCES
                and len(self.stories) >= MIN_STORIES):
            return "attested"
        return "seen"


@dataclasses.dataclass(frozen=True)
class Choice:
    form: str
    status: str


def _add(lst: list, items) -> bool:
    changed = False
    for x in items:
        if x is not None and x not in lst:
            lst.append(x)
            changed = True
    del lst[:-KEEP]
    return changed


class Registry:
    def __init__(self, pairs: list[Pair] | None = None):
        self.pairs: dict[tuple[str, str], Pair] = {}
        self.dirty: set[tuple[str, str]] = set()
        for p in pairs or []:
            self.pairs[(p.en, p.hi)] = p

    # writing ---------------------------------------------------------------------------------------------------
    def add_evidence(self, en: str, hi: str, en_sources, hi_sources, story, when: dt.datetime | None = None) -> Pair | None:
        """Outlets of one story wrote this part as `en` and as `hi` (each copied exactly from an outlet). The sources
        are `source_key`s; None (state media) counts for nothing."""
        if not (valid_en(en) and valid_hi(hi)):
            return None
        en_s = [s for s in en_sources if s]
        hi_s = [s for s in hi_sources if s]
        if not en_s or not hi_s:
            return None
        p = self.pairs.get((en, hi))
        if p is None:
            p = Pair(en, hi, first_seen=when)
            self.pairs[(en, hi)] = p
        elif p.origin == "api":
            p.origin = "outlet"                   # outlets confirmed what the model had transliterated
        if p.origin == "manual":
            return p
        _add(p.en_sources, en_s)
        _add(p.hi_sources, hi_s)
        _add(p.stories, [story])
        p.last_seen = when or p.last_seen
        self.dirty.add((en, hi))
        return p

    def add_translated(self, en: str, hi: str, when: dt.datetime | None = None) -> Pair | None:
        """A transliteration the model gave for a part no outlet pair covered. Kept only while nothing better
        exists for that side."""
        if not (valid_en(en) and valid_hi(hi)) or (en, hi) in self.pairs:
            return None
        p = Pair(en, hi, origin="api", first_seen=when, last_seen=when)
        self.pairs[(en, hi)] = p
        self.dirty.add((en, hi))
        return p

    def add_manual(self, en: str, hi: str) -> None:
        if valid_en(en) and valid_hi(hi):
            self.pairs[(en, hi)] = Pair(en, hi, origin="manual")

    # reading ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _score(group: list[Pair], side: str) -> tuple:
        srcs = set()
        for p in group:
            srcs |= set(p.hi_sources if side == "hi" else p.en_sources)
        stories = set(s for p in group for s in p.stories)
        return (max(RANK[p.status] for p in group), len(srcs), len(stories))

    def hindi(self, en: str) -> Choice | None:
        """The Hindi form of an English part, by its exact spelling. Several Hindi spellings: the best-trusted
        wins, then the one most independent Hindi sources wrote (folded variants counted together)."""
        cands = [p for p in self.pairs.values() if p.en == en]
        if not cands:
            return None
        groups: dict[str, list[Pair]] = {}
        for p in cands:
            groups.setdefault(fold_hi(p.hi), []).append(p)
        best = max(groups.values(), key=lambda g: (self._score(g, "hi"), fold_hi(g[0].hi)))
        shown = max(best, key=lambda p: (RANK[p.status], len(p.hi_sources), len(p.stories), p.hi))
        return Choice(shown.hi, max((p.status for p in best), key=RANK.get))

    def english(self, hi: str) -> Choice | None:
        """The English spelling of a Hindi part (looked up by its folded form): the best-trusted, then the one
        most independent English sources wrote."""
        f = fold_hi(hi)
        cands = [p for p in self.pairs.values() if fold_hi(p.hi) == f]
        if not cands:
            return None
        groups: dict[str, list[Pair]] = {}
        for p in cands:
            groups.setdefault(p.en, []).append(p)
        en, group = max(groups.items(), key=lambda kv: (self._score(kv[1], "en"), kv[0]))
        return Choice(en, max((p.status for p in group), key=RANK.get))

    def english_spelling(self, en: str) -> str:
        """The spelling English outlets use most for this part, through the Hindi form both spellings were paired
        with by OUTLETS (never a transliteration): "Rimpoche" -> "Rimpochee" once both were seen beside
        "रिम्पोछे". Unchanged when nothing links them."""
        h = self.hindi(en)
        if h is None or h.status == "translated":
            return en
        e = self.english(h.form)
        return e.form if e and e.status != "translated" else en

    def hindi_name(self, name: str) -> tuple[str | None, list[str]]:
        """A full English name in Hindi, part by part, or (None, the parts no pair covers)."""
        out, unknown = [], []
        for w in parts(name):
            c = self.hindi(w)
            if c is None:
                unknown.append(w)
            else:
                out.append(c.form)
        return (" ".join(out) if not unknown and out else None), unknown

    def english_name(self, name: str) -> tuple[str | None, list[str]]:
        out, unknown = [], []
        for w in parts(name):
            c = self.english(w)
            if c is None:
                unknown.append(w)
            else:
                out.append(c.form)
        return (" ".join(out) if not unknown and out else None), unknown

    def conflicts(self) -> list[tuple[str, list[str]]]:
        """English parts with two attested Hindi forms that are not variants of one spelling: flagged for the
        owner, never overwritten (the vote still picks one)."""
        by: dict[str, set[str]] = {}
        for p in self.pairs.values():
            if p.status == "attested":
                by.setdefault(p.en, set()).add(fold_hi(p.hi))
        return sorted((en, sorted(hs)) for en, hs in by.items() if len(hs) > 1)

    def counts(self) -> dict[str, int]:
        c = {k: 0 for k in RANK}
        for p in self.pairs.values():
            c[p.status] += 1
        return c


# -- the owner's pairs -----------------------------------------------------------------------------------------------

def manual_pairs(path: pathlib.Path | None = None) -> list[tuple[str, str]]:
    """config/names.yaml (`pairs: [{en: Rimpochee, hi: रिम्पोछे}]`, full names allowed, split part by part) and the
    state names of places.py."""
    out: list[tuple[str, str]] = []
    try:
        data = yaml.safe_load((path or MANUAL_FILE).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    for row in data.get("pairs") or []:
        if isinstance(row, dict):
            out += pair_parts(str(row.get("en") or ""), str(row.get("hi") or ""))
    from .places import STATES
    for en, hi, _ in STATES.values():
        out += pair_parts(en, hi)
    return out


def with_manual(reg: Registry, path: pathlib.Path | None = None) -> Registry:
    for en, hi in manual_pairs(path):
        reg.add_manual(en, hi)
    return reg


# -- transliteration (the quality tier) ------------------------------------------------------------------------------

TRANSLITERATE_PROMPT = """You write names for an Indian news site, the way {paper} newspapers spell them.
Write each name part below in {script}. Transliterate it (how it sounds); never translate its meaning.
One part in, one part out: no titles, no brackets, no notes. If a part is not a name, give "".

Parts:
{items}

Answer as JSON: {{"parts": ["...", "..."]}} with exactly {n} entries, in the same order."""


def transliterate(router, words: list[str], to: str) -> dict[str, str]:
    """{part: its form in the other script} for parts no outlet pair covers, from one call per MAX_PER_CALL parts on
    the quality tier. `to` is "hi" (English parts in) or "en" (Hindi parts in). An answer that is not one valid part
    in the target script is dropped. No quota, a refusal or a broken answer: an empty result, never an error."""
    from .router import CallFailed, QuotaExhausted, parse_json
    words = list(dict.fromkeys(w for w in words if (valid_en(w) if to == "hi" else valid_hi(w))))
    if not words or router is None:
        return {}
    ok = valid_hi if to == "hi" else valid_en
    out: dict[str, str] = {}
    for i in range(0, len(words), MAX_PER_CALL):
        chunk = words[i:i + MAX_PER_CALL]
        try:
            if router.remaining_now("quality") <= 0:
                break
            res = router.call("quality", TRANSLITERATE_PROMPT.format(
                paper="Hindi" if to == "hi" else "English-language",
                script="Devanagari" if to == "hi" else "Latin letters, first letter capital",
                items="\n".join(f"{k + 1}. {w}" for k, w in enumerate(chunk)), n=len(chunk)),
                json_out=True, max_output_tokens=60 + 25 * len(chunk))
        except (QuotaExhausted, CallFailed):
            break
        data = getattr(res, "data", None)
        if data is None:
            try:
                data = parse_json(getattr(res, "text", "") or "")
            except Exception:  # noqa: BLE001
                data = None
        got = data.get("parts") if isinstance(data, dict) else None
        if not isinstance(got, list) or len(got) != len(chunk):
            continue
        for w, g in zip(chunk, got):
            g = str(g or "").strip()
            if ok(g) and g != w:
                out[w] = g
    return out


# -- the database ----------------------------------------------------------------------------------------------------

def load(store) -> Registry:
    from sqlalchemy import select
    from .db import name_pairs
    try:
        rows = store.rows(select(name_pairs))
    except Exception as e:  # noqa: BLE001 - a copy of the newsroom from before the table existed (read-only tools)
        log.info("names: no name_pairs table yet (%s)", str(e)[:80])
        rows = []
    reg = Registry([Pair(r["en"], r["hi"], r["origin"] or "outlet", list(r["en_sources"] or []),
                         list(r["hi_sources"] or []), list(r["stories"] or []), r["first_seen"], r["last_seen"])
                    for r in rows])
    return with_manual(reg)


def save(store, reg: Registry) -> int:
    """Write the pairs changed since loading (never the manual ones: they live in config)."""
    from sqlalchemy import delete, insert
    from .db import name_pairs
    keys = [k for k in reg.dirty if k in reg.pairs and reg.pairs[k].origin != "manual"]
    if not keys:
        return 0
    with store.route(insert(name_pairs)).engine.begin() as c:
        for en, hi in keys:
            p = reg.pairs[(en, hi)]
            c.execute(delete(name_pairs).where(name_pairs.c.en == en, name_pairs.c.hi == hi))
            c.execute(insert(name_pairs).values(en=en, hi=hi, origin=p.origin, en_sources=p.en_sources,
                                                hi_sources=p.hi_sources, stories=[_jsonable(s) for s in p.stories],
                                                first_seen=p.first_seen, last_seen=p.last_seen))
    reg.dirty.clear()
    return len(keys)


def _jsonable(x):
    try:
        json.dumps(x)
        return x
    except TypeError:
        return str(x)


def resolve(store, router, words: list[str], to: str, reg: Registry | None = None,
            when: dt.datetime | None = None) -> dict[str, Choice]:
    """Each part's form in the other script: from the registry by exact spelling; the rest transliterated on the
    quality tier and stored as translated, so no later story asks again. A part with neither stays out."""
    reg = reg or load(store)
    look = reg.hindi if to == "hi" else reg.english
    out = {w: c for w in words if (c := look(w)) is not None}
    missing = [w for w in words if w not in out]
    if missing:
        got = transliterate(router, missing, to)
        for w, g in got.items():
            en, hi = (w, g) if to == "hi" else (g, w)
            if reg.add_translated(en, hi, when) is not None or look(w) is not None:
                c = look(w)
                if c is not None:
                    out[w] = c
        save(store, reg)
    return out

"""Does a statement or a translation say what its source says? Pure code, no model (session 5 of the
translation/learning plan, Oct 16 2026).

The case that started it (Oct 13 2026): a Hindi report said Rahul Gandhi did not DIRECTLY (सीधे) name any party;
our English read "He did not name the BJP or any specific political party". "directly" was lost and "specific" was
added, and nothing noticed. The small words that change what a sentence claims (not, only, at least, directly,
alleged ...) are listed by hand in config/glossary.yaml, in English and Hindi; code checks that each one the source
has is kept and none it lacks is added.

    source_window(statement, source, lang)   the sentence of a report a statement came from, found by its anchors
                                             ONLY: numbers, dates, names (exact, through the name registry), and the
                                             glossary's entities (BJP / भाजपा). Ordinary words are never used: the old
                                             consonant-skeleton tie-break made सीधे match "side". No clear sentence:
                                             None, and nothing is checked (a false flag would cost a good statement).
    compare(source, target, src, tgt)        qualifiers lost and added
    check_reading(statement, source, lang)   both of the above for a statement read from a report
    latin_left(hindi, english)               Latin words left inside a Hindi string (URLs, units and the names the
                                             newsroom keeps in brackets on purpose left out)
    missing_terms(english, hindi)            our binding Hindi renderings (glossary `terms`) not used
    check_translation(english, hindi)        qualifiers, Latin words and terms for one translated string

What acts on a problem (one repair, then drop or retry) is the reading and translation work of the next sessions.
"""
from __future__ import annotations

import dataclasses
import functools
import pathlib
import re

import yaml

FILE = pathlib.Path(__file__).resolve().parent.parent / "config" / "glossary.yaml"
_DEV = "ऀ-ॿ"
NEAR_NUMBER = 2             # words between a number-bound qualifier and its number ("over Rs 40")


@dataclasses.dataclass(frozen=True)
class Qualifier:
    id: str
    strict: bool
    number: bool
    en: tuple[str, ...]
    hi: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Problem:
    kind: str                   # lost / added / latin / term
    what: str                   # the qualifier id, the Latin word, the term
    strict: bool = True

    def __str__(self) -> str:
        return f"{self.kind}:{self.what}"


@functools.lru_cache(maxsize=4)
def glossary(path: str | None = None) -> dict:
    data = yaml.safe_load(pathlib.Path(path or FILE).read_text(encoding="utf-8")) or {}
    for q in data.get("qualifiers") or []:
        bad = [x for x in (q.get("en") or []) + (q.get("hi") or []) if not isinstance(x, str)]
        if bad:      # YAML reads a bare no / yes / on as true or false: quote them
            raise ValueError(f"glossary qualifier {q.get('id')}: not text: {bad}")
    quals = tuple(Qualifier(q["id"], bool(q.get("strict")), bool(q.get("number")),
                            tuple(str(x) for x in q.get("en") or ()), tuple(str(x) for x in q.get("hi") or ()))
                  for q in data.get("qualifiers") or [])
    ents = tuple((tuple(str(x) for x in e.get("en") or ()), tuple(str(x) for x in e.get("hi") or ()))
                 for e in data.get("entities") or [])
    terms = tuple((str(t["en"]), str(t["hi"])) for t in data.get("terms") or [])
    return {"qualifiers": quals, "entities": ents, "terms": terms}


def fold(text: str) -> str:
    """Hindi spelling variants of the same letters read as one (सिर्फ़ = सिर्फ, गाँधी = गांधी); English in lower case."""
    from .names import fold_hi
    return fold_hi(text or "").lower()


def _pattern(phrase: str, lang: str) -> re.Pattern:
    """A glossary phrase as a whole-word pattern; "…" in it stands for up to 12 words ("कभी … नहीं")."""
    parts = []
    for chunk in phrase.split("…"):
        words = [re.escape(fold(w)) for w in chunk.split()]
        parts.append(r"[\s-]+".join(words))
    body = r"(?:\s+\S+){0,12}?\s+".join(p for p in parts if p)
    if lang == "hi":
        return re.compile(rf"(?<![{_DEV}\w-]){body}(?![{_DEV}\w-])")
    if phrase.startswith("n't"):
        return re.compile(rf"\w{body}\b")
    return re.compile(rf"(?<![\w-]){body}(?![\w-])")


@functools.lru_cache(maxsize=4096)
def _pat(phrase: str, lang: str) -> re.Pattern:
    return _pattern(phrase, lang)


_EN_NUMWORD = re.compile(r"(?<![\w-])(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|"
                         r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|crore|million|billion|"
                         r"dozen|half)(?![\w-])")
_HI_NUMWORD = re.compile(rf"(?<![{_DEV}])(?:एक|दो|तीन|चार|पांच|पाँच|छह|सात|आठ|नौ|दस|बीस|सौ|हजार|हज़ार|लाख|करोड़|दर्जन|आधा|आधे)(?![{_DEV}])")


def _numbers_near(text: str, start: int, end: int, lang: str) -> set[str]:
    """The number a number-bound qualifier is about: the one right after it ("about 40", "करीब 40"), or right before
    it when the qualifier follows its number ("40 से अधिक", "50 percent maximum"). A number word ("dozens",
    "करोड़") with no value counts as "#"."""
    words_after = re.split(r"\s+", text[end:].strip())
    words_before = re.split(r"\s+", text[:start].strip())
    word = _HI_NUMWORD if lang == "hi" else _EN_NUMWORD
    q = text[start:end]
    # the qualifier follows its number in Hindi "40 से अधिक" and English "50 percent maximum"; else it comes first
    follows = (lang == "hi" and q.startswith("से")) or (lang == "en" and q in ("maximum", "minimum"))
    follows = follows or q.endswith("तक_ऊपरी")
    before = " ".join(words_before[-(NEAR_NUMBER + 1):])  # with its scale word ("3 लाख टन से अधिक")
    near = " ".join(words_after[:NEAR_NUMBER])            # the number starts within two words ("about Rs 40")
    if follows:
        side = before
    elif re.search(r"[0-9\u0966-\u096F]", near) or word.search(near):
        side = " ".join(words_after[:NEAR_NUMBER + 1])    # with its scale word ("Rs 3,350 crore")
    elif lang == "hi" or q in ("maximum", "minimum"):
        side = before                                     # "50 प्रतिशत की अधिकतम सीमा"
    else:
        return set()
    for side in (side,):
        vals = numbers(side)
        if vals:
            return vals
        if (_HI_NUMWORD if lang == "hi" else _EN_NUMWORD).search(side):
            return {"#"}
    return set()


_DIGITS = str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f", "0123456789")


_HI_SCALE = [("करोड़", "crore"), ("करोड", "crore"), ("लाख", "lakh"), ("हज़ार", "thousand"), ("हजार", "thousand")]


def numbers(text: str | None) -> set[str]:
    """The numbers of a text by value, in either language: figures.py reads English and digits; Hindi scale words
    (करोड़, लाख, हज़ार) are read as their English ones first, so "3,350 करोड़" = "Rs 3,350 crore"."""
    from .figures import canon_set
    t = (text or "").translate(_DIGITS)
    for hi, en in _HI_SCALE:
        t = t.replace(hi, " " + en + " ")
    return canon_set(t)


def _prepare(text: str, lang: str) -> str:
    t = fold(text)
    if lang == "hi":
        t = re.sub(r"(?<![\u0900-\u097F\w-])या नहीं(?![\u0900-\u097F\w-])", " ", t)   # "whether or not"
        t = re.sub(r"सीधे सेट", "स्ट्रेट सेट", t)                                          # tennis: "straight sets"
        # "100% तक", "5 लाख रुपये तक": up to. Not "15 अक्टूबर तक" or "2026 तक" (until, by): a unit must stand between
        t = re.sub(r"(\d[\d,.]*\s*(?:%|प्रतिशत|करोड़|करोड|लाख|रुपये|रुपए|हजार|हज़ार|किलोमीटर|मीटर|टन))\s+तक"
                   r"(?![\u0900-\u097F])", r"\1 तक_ऊपरी", t)
    if lang == "en":
        t = re.sub(r"(?<![\w-])no\.\s*\d", " ", t)          # "No. 5" is a number, not a negation
        t = re.sub(r"(?<![\w-])not out(?![\w-])", "unbeaten", t)   # cricket: नाबाद
        t = re.sub(r"(?<![\w-])spread (?:over|across)(?![\w-])", "spread in", t)  # an area, not "more than"
        t = re.sub(r"(?<![\w-])exceed(?:ing|s|ed)? the(?![\w-])", "breaching the", t)  # "exceeding the 50% limit"
    return t


def occurrences(text: str, lang: str) -> list[tuple[str, int, int, frozenset]]:
    """(qualifier id, start, end, the numbers it is bound to) for each qualifier in a text (on its folded form).
    A number-bound qualifier with no number next to it is not one ("about the case", "over the years")."""
    t = _prepare(text, lang)
    out = []
    for q in glossary()["qualifiers"]:
        spans: list[tuple[int, int]] = []
        for phrase in sorted(q.hi if lang == "hi" else q.en, key=len, reverse=True):
            for m in _pat(phrase, lang).finditer(t):
                if any(a < m.end() and m.start() < b for a, b in spans):
                    continue                      # inside a longer phrase of the same qualifier
                spans.append((m.start(), m.end()))
        for a, b in sorted(spans):
            nums = frozenset()
            if q.number:
                nums = frozenset(_numbers_near(t, a, b, lang))
                if not nums:
                    continue
            out.append((q.id, a, b, nums))
    return out


def qualifiers(text: str, lang: str) -> set[str]:
    """The glossary qualifiers a text uses."""
    return {q for q, *_ in occurrences(text, lang)}


_STOP = {"that", "this", "with", "from", "have", "were", "been", "they", "their", "said", "will", "would", "about",
         "which", "there", "into", "than", "also", "over", "after", "before", "under"}


def _stem(w: str) -> str:
    return re.sub(r"(?:ing|ed|es|s)$", "", w) if len(w) > 5 else w


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]{4,}", text) if w not in _STOP} | set(re.findall(r"\d+", text))


# a text that attributes ("X alleged that", "claimed", "आरोप लगाया") keeps the caveat "alleged" carries
_ATTRIBUTES = {"en": re.compile(r"(?<![\w-])(?:alleg\w*|claim\w*|accus\w*)"), "hi": re.compile(r"आरोप|दावा|दावे")}


_CLAUSE = re.compile(r"[,;:\u2014\u2013]|\s(?:लेकिन|जबकि|बल्कि|मगर|while|whereas|but)\s")


def _in_scope(source_t: str, start: int, end: int, statement: str, src_lang: str, registry) -> bool:
    """Does the statement say the thing this qualifier of the source is about? A statement read from part of a
    sentence ("In Puducherry, the NDA won by 8,482 votes" from "...the BJP won by over 75,000 votes, while in
    Puducherry ...") has not lost the qualifiers of the other part. English source: the words right after the
    qualifier are in the statement. Hindi source: its clause holds one of the statement's anchors."""
    if src_lang == "en":
        scope = source_t[end:end + 60]
        return bool(_words(scope) & _words(fold(statement)))
    cuts = [0] + [m.end() for m in _CLAUSE.finditer(source_t)] + [len(source_t) + 1]
    a = max(c for c in cuts if c <= start)
    b = min(c for c in cuts if c > start)
    return anchors(statement, source_t[a:b], src_lang, registry) > 0


def compare(source: str, target: str, src_lang: str, tgt_lang: str, strict_only: bool = False,
            scoped: bool = False, registry=None) -> list[Problem]:
    """Qualifiers the source has and the target lost, and the ones the target added. A number-bound qualifier
    ("over", "से अधिक") is compared number by number, only for numbers both texts carry. `scoped` (a statement read
    from a report): a qualifier counts as lost only when the statement says what it is about (`_in_scope`)."""
    oa, ob = occurrences(source, src_lang), occurrences(target, tgt_lang)
    strict = {q.id: q.strict for q in glossary()["qualifiers"]}
    na, nb = numbers(source), numbers(target)
    plain_a = {q for q, _, _, n in oa if not n}
    plain_b = {q for q, _, _, n in ob if not n}
    bound_a = {(q, x) for q, _, _, n in oa for x in n}
    bound_b = {(q, x) for q, _, _, n in ob for x in n}
    lost, added = set(), set(plain_b - plain_a)
    if _ATTRIBUTES[src_lang].search(fold(source)):
        added.discard("alleged")
    st = _prepare(source, src_lang)
    for q, a, b, n in oa:
        if n or q in plain_b or q in lost:
            continue
        if not scoped or _in_scope(st, a, b, target, src_lang, registry):
            lost.add(q)
    if _ATTRIBUTES[tgt_lang].search(fold(target)):
        lost.discard("alleged")
    lost |= {q for q, x in bound_a - bound_b if x != "#" and x in nb}
    added |= {q for q, x in bound_b - bound_a if x != "#" and x in na}
    out = [Problem("lost", q, strict[q]) for q in sorted(lost)] + [Problem("added", q, strict[q]) for q in sorted(added)]
    return [p for p in out if p.strict or not strict_only]


# -- which sentence of the report ----------------------------------------------------------------------------------

_SENT = re.compile(r"(?<=[।॥?!.])\s+|\n+")


def sentences(text: str) -> list[str]:
    """A report's sentences (danda, full stop, question and exclamation marks, line breaks). An abbreviation's
    full stop may split one sentence in two; that only makes a window smaller."""
    return [s.strip() for s in _SENT.split(text or "") if s and s.strip()]


def _entity_hits(statement: str, sentence: str, src_lang: str) -> int:
    n = 0
    st = fold(statement)
    se = fold(sentence)
    for en, hi in glossary()["entities"]:
        if any(_pat(x, "en").search(st) for x in en):
            forms = hi if src_lang == "hi" else en
            if any(_pat(x, src_lang).search(se) for x in forms):
                n += 1
    return n


def _name_hits(statement: str, sentence: str, src_lang: str, registry) -> int:
    from .names import parts
    from .people import NAME
    words = {w for m in NAME.finditer(statement or "") for w in parts(m.group(0)) if len(w) > 2}
    n = 0
    for w in words:
        if src_lang == "hi":
            c = registry.hindi(w) if registry is not None else None
            if c is not None and _pat(c.form, "hi").search(fold(sentence)):
                n += 1
        elif re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", sentence):
            n += 1
    return n


def anchors(statement: str, sentence: str, src_lang: str, registry=None) -> int:
    """How many of a statement's anchors a source sentence holds: its numbers (by value, any script), its dates,
    its names (exact; Hindi through the registry) and its glossary entities."""
    from . import figures, when
    n = len(numbers(statement) & numbers(sentence))
    dv = set(when.date_values(statement))
    n += len(dv & set(when.date_values(sentence)))
    n += _name_hits(statement, sentence, src_lang, registry)
    n += _entity_hits(statement, sentence, src_lang)
    return n


def source_window(statement: str, source: str, src_lang: str, registry=None) -> str | None:
    """The one sentence of the report the statement came from, or None when no sentence clearly does (no anchor
    found, or two sentences tie)."""
    scored = [(anchors(statement, s, src_lang, registry), s) for s in sentences(source)]
    scored = [x for x in scored if x[0] > 0]
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def check_reading(statement: str, source: str, src_lang: str, registry=None,
                  strict_only: bool = True) -> tuple[str | None, list[Problem]]:
    """(the source sentence found, the qualifiers the statement lost or added). An English statement read from a
    Hindi or English report."""
    win = source_window(statement, source, src_lang, registry)
    if win is None:
        return None, []
    return win, compare(win, statement, src_lang, "en", strict_only, scoped=True, registry=registry)


# -- translations into Hindi ---------------------------------------------------------------------------------------

LATIN_WORD = re.compile(r"(?<![\w/.@])[A-Za-z][A-Za-z'’.-]*[A-Za-z]|(?<![\w/.@])[A-Za-z](?![\w])")
URL = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\w+")
LATIN_OK = {"km", "kg", "cm", "mm", "mw", "kv", "gw", "kwh", "ml", "mg", "gb", "mb", "rs", "am", "pm", "ist",
            "km/h", "kmph", "sq", "ft", "mt", "tmc", "cusec", "cusecs", "mph", "hz", "ghz", "mhz", "kw"}
_BRACKET = re.compile(r"[\(\[]([^()\[\]]*)[\)\]]")


def latin_left(hindi: str, english: str | None = None) -> list[str]:
    """Latin words left inside a Hindi string. Not counted: URLs and e-mail addresses, units (km, MW), and a name
    the newsroom keeps in brackets when the English has the same brackets (refs.py; translation_problem checks it)."""
    t = URL.sub(" ", hindi or "")
    kept = {m.group(1).strip() for m in _BRACKET.finditer(english or "")}
    t = _BRACKET.sub(lambda m: " " if m.group(1).strip() in kept else m.group(0), t)
    return [w for w in LATIN_WORD.findall(t) if w.lower().strip(".") not in LATIN_OK]


@functools.lru_cache(maxsize=1)
def _learned_terms() -> tuple[dict, ...]:
    """Terms learned from the outlets (learn_glossary.py), each with its section and context words; the
    hand-written ones win (a hand-written English word is never taken from here)."""
    try:
        from .learn_glossary import learned_terms
        hand = {en.lower() for en, _ in glossary()["terms"]}
        return tuple(t for t in learned_terms() if t["en"].lower() not in hand)
    except Exception:  # noqa: BLE001 - no file, or one that does not parse: hand-written terms only
        return ()


def all_terms() -> tuple[tuple[str, str], ...]:
    """Every term as (English, Hindi), whatever its context (for naming a term in a note)."""
    return tuple(glossary()["terms"]) + tuple((t["en"], t["hi"]) for t in _learned_terms())


def learned_sense(english: str, en_word: str, section: str | None, entries=None) -> str | None:
    """The Hindi a learned term gives `en_word` in this English text, or None when no sense's context matches
    (context.best: the section, and 2+ of the sense's context words in the sentence; 3+ with no section). A
    learned term with no section and no context (written by hand in the learned file) applies everywhere."""
    from . import context
    entries = [t for t in (entries if entries is not None else _learned_terms()) if t["en"] == en_word]
    if not entries:
        return None
    for t in entries:
        if not t["section"] and not t["context"]:
            return t["hi"]
    senses = {i: context.Sense(t["section"], context.YOUNG + 1, {w: context.SIGNATURE_MIN for w in t["context"]})
              for i, t in enumerate(entries)}
    sentence = context.sentence_with(english, en_word, "en") or english
    k = context.best(senses, section or "", context.words(sentence, "en", en_word))
    return entries[k]["hi"] if k is not None else None


def terms_in(english: str, section: str | None = None) -> list[tuple[str, str]]:
    """The binding terms an English text uses: (English, our Hindi). Hand-written terms everywhere; a learned term
    only where the text's context matches one of its senses (owner, Oct 16 2026: "bank" is not बैंक by a river)."""
    t = fold(english)
    out = [(en, hi) for en, hi in glossary()["terms"] if _pat(en, "en").search(t)]
    seen = {en for en, _ in out}
    for en in dict.fromkeys(x["en"] for x in _learned_terms()):
        if en in seen or not _pat(en, "en").search(t):
            continue
        hi = learned_sense(english, en, section)
        if hi:
            out.append((en, hi))
    return out


def missing_terms(english: str, hindi: str, section: str | None = None) -> list[str]:
    h = fold(hindi)
    return [en for en, hi in terms_in(english, section) if not _pat(hi, "hi").search(h)]


def check_translation(english: str, hindi: str, strict_only: bool = True, section: str | None = None) -> list[Problem]:
    """Everything code can say is wrong with one Hindi string made from an English one (`section`: the story's
    context section, so a learned term is expected only where its context matches)."""
    out = compare(english, hindi, "en", "hi", strict_only)
    out += [Problem("latin", w) for w in dict.fromkeys(latin_left(hindi, english))]
    out += [Problem("term", t) for t in missing_terms(english, hindi, section)]
    return out

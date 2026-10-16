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
NEAR_NUMBER = 3             # words between a number-bound qualifier and its number


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
    words = [re.escape(fold(w)) for w in phrase.split()]
    body = r"[\s-]+".join(words)
    if lang == "hi":
        return re.compile(rf"(?<![{_DEV}\w]){body}(?![{_DEV}\w])")
    if phrase.startswith("n't"):
        return re.compile(rf"\w{body}\b")
    return re.compile(rf"(?<![\w-]){body}(?![\w-])")


@functools.lru_cache(maxsize=4096)
def _pat(phrase: str, lang: str) -> re.Pattern:
    return _pattern(phrase, lang)


_NUM = re.compile(r"[0-9०-९]")
_EN_NUMWORD = re.compile(r"(?<![\w-])(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|"
                         r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|crore|million|billion|"
                         r"dozen|half)(?![\w-])")
_HI_NUMWORD = re.compile(rf"(?<![{_DEV}])(?:एक|दो|तीन|चार|पांच|पाँच|छह|सात|आठ|नौ|दस|बीस|सौ|हजार|हज़ार|लाख|करोड़|दर्जन|आधा|आधे)(?![{_DEV}])")


def _number_near(text: str, start: int, end: int, lang: str) -> bool:
    words_after = re.split(r"\s+", text[end:].strip())[:NEAR_NUMBER + 1]
    words_before = re.split(r"\s+", text[:start].strip())[-NEAR_NUMBER:] if lang == "hi" else []
    around = " ".join(words_after + words_before)
    word = _HI_NUMWORD if lang == "hi" else _EN_NUMWORD
    return bool(_NUM.search(around) or word.search(around))


def qualifiers(text: str, lang: str) -> set[str]:
    """The glossary qualifiers a text uses."""
    t = fold(text)
    if lang == "en":
        t = re.sub(r"(?<![\w-])no\.\s*\d", " ", t)          # "No. 5" is a number, not a negation
    found = set()
    for q in glossary()["qualifiers"]:
        for phrase in (q.hi if lang == "hi" else q.en):
            for m in _pat(phrase, lang).finditer(t):
                if q.number and not _number_near(t, m.start(), m.end(), lang):
                    continue
                found.add(q.id)
                break
            if q.id in found:
                break
    if "never" in found:
        found.add("negation")
    return found


def compare(source: str, target: str, src_lang: str, tgt_lang: str, strict_only: bool = False) -> list[Problem]:
    """Qualifiers the source has and the target lost, and the ones the target added."""
    a, b = qualifiers(source, src_lang), qualifiers(target, tgt_lang)
    strict = {q.id: q.strict for q in glossary()["qualifiers"]}
    out = [Problem("lost", q, strict[q]) for q in sorted(a - b)] + [Problem("added", q, strict[q]) for q in sorted(b - a)]
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
    n = len(figures.canon_set(statement) & figures.canon_set(sentence))
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
    return win, compare(win, statement, src_lang, "en", strict_only)


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


def terms_in(english: str) -> list[tuple[str, str]]:
    """The binding terms an English text uses: (English, our Hindi)."""
    t = fold(english)
    return [(en, hi) for en, hi in glossary()["terms"] if _pat(en, "en").search(t)]


def missing_terms(english: str, hindi: str) -> list[str]:
    h = fold(hindi)
    return [en for en, hi in terms_in(english) if not _pat(hi, "hi").search(h)]


def check_translation(english: str, hindi: str, strict_only: bool = True) -> list[Problem]:
    """Everything code can say is wrong with one Hindi string made from an English one."""
    out = compare(english, hindi, "en", "hi", strict_only)
    out += [Problem("latin", w) for w in dict.fromkeys(latin_left(hindi, english))]
    out += [Problem("term", t) for t in missing_terms(english, hindi)]
    return out

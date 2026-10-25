"""Does a statement or a translation say what its source says? Decided by the local NLI model (nli.py), not by word lists.

The case that started it (Oct 13 2026): a Hindi report said Rahul Gandhi did not DIRECTLY (सीधे) name any party; our
English read "He did not name the BJP or any specific political party". The old check kept hand-written lists of small
words (not, only, at least, directly ...) in two languages. The multilingual NLI model reads the meaning instead: a
reading is checked by "does the report's sentence entail the statement?", a translation by entailment in both directions
(English -> Hindi lost something, Hindi -> English added something), and a contradiction either way is a problem.

    source_window / quoted_window / find_source   the sentence of a report a statement came from: the words the reading
                                             copied (quote), else anchors only (numbers, dates, names exactly)
    check_reading(statement, source, lang)   NLI between the found sentence and the statement
    check_translation(english, hindi)        NLI both ways, Latin words left, our binding terms (glossary `terms`)

No NLI model (not loaded, or a pair it could not read): nothing is flagged, never a guess.
"""
from __future__ import annotations

import dataclasses
import functools
import pathlib
import re

import yaml

FILE = pathlib.Path(__file__).resolve().parent.parent / "config" / "glossary.yaml"
_DEV = "ऀ-ॿ"
SUPPORT = 0.50              # P(entailment) below this: the other side is not carrying what this one says
CONTRA = 0.80               # P(contradiction) at or above this: they cannot both be right


@dataclasses.dataclass(frozen=True)
class Problem:
    kind: str                   # lost / added / contradicted / unsupported / latin / term
    what: str                   # "meaning" for the NLI kinds, the Latin word, the term
    strict: bool = True

    def __str__(self) -> str:
        return f"{self.kind}:{self.what}"


@functools.lru_cache(maxsize=4)
def glossary(path: str | None = None) -> dict:
    data = yaml.safe_load(pathlib.Path(path or FILE).read_text(encoding="utf-8")) or {}
    return {"terms": tuple((str(t["en"]), str(t["hi"])) for t in data.get("terms") or [])}


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


# -- which sentence of the report ----------------------------------------------------------------------------------

_SENT = re.compile(r"(?<=[।॥?!.])\s+|\n+")


def sentences(text: str) -> list[str]:
    """A report's sentences (danda, full stop, question and exclamation marks, line breaks). An abbreviation's
    full stop may split one sentence in two; that only makes a window smaller."""
    return [s.strip() for s in _SENT.split(text or "") if s and s.strip()]


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
    its names (exact; Hindi through the registry)."""
    from . import figures, when
    n = len(numbers(statement) & numbers(sentence))
    dv = set(when.date_values(statement))
    n += len(dv & set(when.date_values(sentence)))
    n += _name_hits(statement, sentence, src_lang, registry)
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


_QTOK = re.compile(rf"[{_DEV}\w]+")
QUOTE_WORDS = 8             # words of a quote compared (the reading model copies the sentence's first words)
QUOTE_MIN = 4               # fewest words a quote must match, in order, exactly once in the report


def quoted_window(quote: str | None, source: str) -> str | None:
    """The report sentence a statement came from, found by the words the reading model copied from its start
    (`quote`, context plan session 6, Oct 16 2026): the sentence where those words stand, word for word, in order
    (folded, punctuation ignored), with the next sentences while the quote runs on. Code checks the copy: a quote
    that is not in the report (the model paraphrased or translated it) or that stands in two places finds nothing."""
    q = _QTOK.findall(fold(quote or ""))[:QUOTE_WORDS]
    if len(q) < QUOTE_MIN:
        return None
    sents = sentences(source)
    flat: list[tuple[str, int]] = []
    for i, s in enumerate(sents):
        flat += [(w, i) for w in _QTOK.findall(fold(s))]
    words = [w for w, _ in flat]
    for n in range(len(q), QUOTE_MIN - 1, -1):          # the whole copy, else its first words (a slip at its end)
        hits = [k for k in range(len(words) - n + 1) if words[k:k + n] == q[:n]]
        if len(hits) == 1:
            k = hits[0]
            a, b = flat[k][1], flat[k + n - 1][1]
            return " ".join(sents[a:b + 1])
        if len(hits) > 1:
            return None
    return None


def find_source(statement: str, source: str, src_lang: str, registry=None,
                quote: str | None = None) -> tuple[str | None, str]:
    """(the report sentence a statement came from, how it was found: "quote", "anchors" or "none")."""
    win = quoted_window(quote, source)
    if win is not None:
        return win, "quote"
    win = source_window(statement, source, src_lang, registry)
    return win, ("anchors" if win is not None else "none")


def check_reading(statement: str, source: str, src_lang: str, registry=None,
                  strict_only: bool = True, quote: str | None = None,
                  stance: str | None = None) -> tuple[str | None, list[Problem]]:
    """(the source sentence found, the problems). An English statement read from a Hindi or English report: the
    report's sentence must entail it. A denial is written as the positive claim (reading rule 4), so only support is
    asked of it, not the absence of contradiction."""
    from . import nli
    win, how = find_source(statement, source, src_lang, registry, quote)
    if win is None:
        return None, []
    r = nli.predict([(win, statement)])[0]
    if r is None:
        return win, []
    if r[2] >= CONTRA and stance != "denies":
        return win, [Problem("contradicted", "meaning")]
    if r[0] < SUPPORT and stance != "denies":
        return win, [Problem("unsupported", "meaning")]
    return win, []


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


def terms_in(english: str, section: str | None = None) -> list[tuple[str, str]]:
    """The binding terms an English text uses: (English, our Hindi), hand-written in glossary.yaml."""
    t = fold(english)
    return [(en, hi) for en, hi in glossary()["terms"] if _pat(en, "en").search(t)]


def all_terms() -> tuple[tuple[str, str], ...]:
    return tuple(glossary()["terms"])


def missing_terms(english: str, hindi: str, section: str | None = None) -> list[str]:
    h = fold(hindi)
    return [en for en, hi in terms_in(english, section) if not _pat(hi, "hi").search(h)]


def check_translation(english: str, hindi: str, strict_only: bool = True, section: str | None = None) -> list[Problem]:
    """Everything wrong with one Hindi string made from an English one: the NLI model reads both ways (English ->
    Hindi not entailed = something lost; Hindi -> English not entailed = something added; a contradiction either way),
    then Latin words left and our binding terms."""
    from . import nli
    out: list[Problem] = []
    both = nli.both([(english, hindi)])[0]
    if both is not None:
        fwd, bwd = both
        if max(fwd[2], bwd[2]) >= CONTRA:
            out.append(Problem("contradicted", "meaning"))
        else:
            if fwd[0] < SUPPORT:
                out.append(Problem("lost", "meaning"))
            if bwd[0] < SUPPORT:
                out.append(Problem("added", "meaning"))
    out += [Problem("latin", w) for w in dict.fromkeys(latin_left(hindi, english))]
    out += [Problem("term", t) for t in missing_terms(english, hindi, section)]
    return out

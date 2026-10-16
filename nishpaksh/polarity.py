"""Negation written into a word (owner, Oct 16 2026; context plan session 5).

"Roads were unaffected" and "सड़कें प्रभावित नहीं हुईं" say the same thing, but only the Hindi has a negation word, so
the fidelity checks called it a lost or added negation. And "Roads were affected", read from "unaffected", turns the
fact around while no negation word went missing, so nothing noticed. A negation can be a WORD FORM.

    forms(text, lang)    each negated word form in a text: (start, end, word, base, strong), on fidelity.fold(text)
    strong               config/negation.yaml `strong`: a negation like "not" / "नहीं" (its usual rendering in the other
                         language is itself negated); gair- (गैर-, गैर) and non- are strong by rule
    weak                 an English un- word not listed (unhurt, unprecedented): its rendering often carries no
                         negation (unprecedented = अभूतपूर्व), so it never counts as a negation alone; it only answers
                         a negation on the other side, and is lost when the other text has its base word bare
    as_particles(text)   English with each strong form written as "not <base>" ("unaffected" -> "not affected"), for
                         statement matching (relate.py)
"""
from __future__ import annotations

import dataclasses
import functools
import pathlib
import re

FILE = pathlib.Path(__file__).resolve().parent.parent / "config" / "negation.yaml"
_DEV = "ऀ-ॿ"
_EN_TOKEN = re.compile(r"(?<![\w-])[a-z][a-z-]*[a-z](?![\w-])")
_HI_GAIR = re.compile(rf"(?<![{_DEV}\w-])गैर[- ]?([{_DEV}]{{3,}})(?![{_DEV}\w-])")
_EN_NON = re.compile(r"(?<![\w-])non-?([a-z]{3,})(?![\w-])")
_NON_NOT = ("none", "nonetheless", "nonsense", "nonchalant")


@dataclasses.dataclass(frozen=True)
class Form:
    start: int
    end: int
    word: str
    base: str
    strong: bool


def _fold(text: str) -> str:
    from .fidelity import fold
    return fold(text)


@functools.lru_cache(maxsize=2)
def data(path: str | None = None) -> dict:
    """{"strong": {"en": {word: base}, "hi": {...}}, "not": (English un- words left alone)}, folded. A missing or
    broken file gives nothing (the checks then work as before)."""
    try:
        import yaml
        d = yaml.safe_load(pathlib.Path(path or FILE).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        d = {}
    strong = {}
    for lang in ("en", "hi"):
        raw = (d.get("strong") or {}).get(lang) or {}
        strong[lang] = {_fold(str(k)): _fold(str(v or "")) for k, v in raw.items() if isinstance(k, str)}
    nn = d.get("not_negation") or {}
    nots = tuple(str(x).lower() for x in (nn.get("en") or []) if isinstance(x, str))
    non = frozenset(str(x).lower() for x in (nn.get("non") or []) if isinstance(x, str))
    gair = frozenset(_fold(str(x)) for x in (nn.get("hi") or []) if isinstance(x, str))
    return {"strong": strong, "not": nots, "non": non, "gair": gair}


def _non_base(word: str) -> str | None:
    """The base of a non- word that negates ("non-bailable" -> "bailable"), or None."""
    m = _EN_NON.fullmatch(word)
    if not m or word.replace("-", "") in _NON_NOT or word.startswith(_NON_NOT) or m.group(1) in data()["non"]:
        return None
    return m.group(1)


def _weak_en(word: str) -> str | None:
    """The base of an English un- word the list does not hold ("unhurt" -> "hurt"), or None."""
    if not word.startswith("un") or len(word) < 6 or "-" in word:
        return None
    if any(word.startswith(x) for x in data()["not"]):
        return None
    return word[2:]


def forms(text: str, lang: str, folded: bool = False) -> list[Form]:
    """The negated word forms of a text, with positions on its folded form (or on `text` itself when `folded`)."""
    t = text if folded else _fold(text)
    strong = data()["strong"].get(lang) or {}
    out: list[Form] = []
    taken: list[tuple[int, int]] = []

    def add(a, b, w, base, s):
        if not any(x < b and a < y for x, y in taken):
            taken.append((a, b))
            out.append(Form(a, b, w, base, s))
    if lang == "hi":
        for m in _HI_GAIR.finditer(t):
            if m.group(1) not in data()["gair"]:
                add(m.start(), m.end(), m.group(0), m.group(1), True)
        for m in re.finditer(rf"[{_DEV}]+", t):
            w = m.group(0)
            if w in strong:
                if (m.start() > 0 and re.match(rf"[\w-]", t[m.start() - 1])) or (m.end() < len(t) and re.match(r"[\w-]", t[m.end()])):
                    continue
                add(m.start(), m.end(), w, strong[w], True)
        return sorted(out, key=lambda f: f.start)
    for m in _EN_NON.finditer(t):
        base = _non_base(m.group(0))
        if base:
            add(m.start(), m.end(), m.group(0), base, True)
    for m in _EN_TOKEN.finditer(t):
        w = m.group(0)
        if w in strong:
            add(m.start(), m.end(), w, strong[w], True)
            continue
        base = _weak_en(w)
        if base:
            add(m.start(), m.end(), w, base, False)
    return sorted(out, key=lambda f: f.start)


def as_particles(text: str) -> str:
    """English with each strong negated form written as "not <base>": "Roads were unaffected" -> "Roads were not
    affected" (case of the rest kept). Weak forms stay as written."""
    t = text or ""
    strong = data()["strong"].get("en") or {}

    def sub(m):
        w = m.group(0)
        lw = w.lower()
        if lw in strong:
            return f"not {strong[lw]}".strip()
        base = _non_base(lw)
        return f"not {base}" if base else w
    return re.sub(r"(?<![\w-])[A-Za-z][A-Za-z-]*[A-Za-z](?![\w-])", sub, t)


def has_base(text: str, base: str, lang: str) -> bool:
    """Does the text use the base word bare (not inside its negated form)? English compares stems."""
    t = _fold(text)
    if not base:
        return False
    if lang == "hi":
        return bool(re.search(rf"(?<![{_DEV}\w-]){re.escape(base)}(?![{_DEV}\w-])", t))
    from .frames import _stem
    b = _stem(base)
    return any(_stem(w) == b for w in re.findall(r"[a-z]+", t))

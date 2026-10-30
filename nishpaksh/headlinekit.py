"""Headline kit: what the headline step needs besides the model (owner, Oct 30 2026: "the headlines are uninteresting").

Measured on 242 archived stories with 4+ outlet headlines (Oct 30 2026): our headlines carried 45% of the words most outlets
put in theirs (a typical outlet headline: 64%), included the figure half the outlets headline 41% of the time, and used no
colon or exact quote (outlets: 40% and 22%).

Pure code. No model call, no network, no database: it only reads what `write_headline` already has (the outlets' own English
headlines of the story, the statements) and runs in well under a millisecond. Every public function returns a neutral value
(empty, None, 0) on any error, so the caller's old behaviour is the fallback and a headline is never held back by this module.

  consensus()      the words most outlets' headlines share (names, figures, the verb): the facts professionals put first.
  coverage()       how much of that a candidate headline carries.
  quotes()         exact quoted words of a speaker in the statements (the only quotes a headline may use).
  quote_problem()  a quotation in a headline must be letter for letter in the statements, with its speaker named.
  copy_problem()   a headline may not copy an outlet's headline (7 words in a row, or nearly all its words).
  repetition()     how many of the recent headlines have the same skeleton (shape and verb): a day of "X orders Y".
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from functools import lru_cache

log = logging.getLogger(__name__)

SHARE = 0.5          # a word counts as shared when this share of the outlets' headlines carry it (and at least MINIMUM)
MINIMUM = 2
CAP = 10             # shared words kept
OUTLETS_SHOWN = 5    # outlet headlines shown to the model
COPY_RUN = 7         # this many words in a row equal to an outlet's headline = a copy
COPY_SHARE = 0.85    # or this share of a 6+ word headline's words
QUOTE_WORDS = (3, 10)
STOP = {"the", "and", "for", "with", "from", "over", "into", "after", "amid", "its", "his", "her", "their", "that", "this",
        "will", "has", "have", "been", "says", "said", "than", "who", "not", "are", "was", "were", "may", "can", "all", "but",
        "new", "one", "two", "out", "also", "now", "how", "why", "what", "when", "where", "while", "about", "more", "most",
        "over", "under", "against", "after", "before", "says", "say", "here", "there", "they", "them", "your", "our"}


@lru_cache(maxsize=4096)
def _stem(w: str) -> str:
    try:
        from .frames import _stem as s
        return s(w)
    except Exception:  # noqa: BLE001 - no stemmer: strip the commonest endings
        for suf in ("ing", "ed", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                return w[:-len(suf)]
        return w


def words(text: str) -> list[tuple[str, str]]:
    """[(stem, surface)] of the content words and figures of a headline (figures without separators)."""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?|[A-Za-z][A-Za-z'’-]*", (text or "").replace("per cent", "%")):
        w = m.group(0)
        if w[0].isdigit():
            n = w.replace(",", "").rstrip(".")
            out.append((n, n))
            continue
        lw = re.sub(r"(?:'s|’s)$", "", w.lower()).strip("'-’")
        if len(lw) >= 3 and lw not in STOP:
            out.append((_stem(lw), lw))
    return out


def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return re.split(r"\s[|–—]\s|\s-\s(?=[A-Z][\w .&']{2,30}$)", t)[0].strip()


def _rows(titles) -> list[tuple[str, str]]:
    """[(outlet, title)] one per outlet, no duplicate titles. `titles`: strings or {"outlet", "title"} dicts."""
    seen_o, seen_t, rows = set(), set(), []
    for t in titles or []:
        outlet, title = (t.get("outlet"), t.get("title")) if isinstance(t, dict) else (None, t)
        title = _clean_title(str(title or ""))
        key = title.lower()
        if len(title.split()) < 3 or key in seen_t or (outlet and outlet in seen_o):
            continue
        seen_t.add(key)
        if outlet:
            seen_o.add(outlet)
        rows.append((str(outlet or ""), title))
    return rows


def consensus(titles) -> dict[str, dict]:
    """{stem: {"w": share of outlets, "n": outlets, "word": surface}} for the words that at least SHARE of the outlets' headlines
    carry (never fewer than MINIMUM outlets), strongest first, figures first among equals. {} with fewer than two headlines."""
    try:
        rows = _rows(titles)
        if len(rows) < MINIMUM:
            return {}
        count: Counter = Counter()
        surface: dict[str, Counter] = {}
        for _, title in rows:
            seen = set()
            for st, sf in words(title):
                if st in seen:
                    continue
                seen.add(st)
                count[st] += 1
                surface.setdefault(st, Counter())[sf] += 1
        need = max(MINIMUM, math.ceil(SHARE * len(rows)))
        keep = [(st, n) for st, n in count.items() if n >= need]
        keep.sort(key=lambda x: (-x[1], not x[0][0].isdigit(), x[0]))
        return {st: {"w": n / len(rows), "n": n, "word": surface[st].most_common(1)[0][0]} for st, n in keep[:CAP]}
    except Exception as e:  # noqa: BLE001
        log.info("headlinekit.consensus: %s", str(e)[:120])
        return {}


def coverage(h: str, cons: dict) -> float:
    """Share (0..1) of the shared words' weight that the headline carries; 0 without a consensus."""
    try:
        total = sum(v["w"] for v in cons.values())
        if not total:
            return 0.0
        have = {st for st, _ in words(h)}
        return sum(v["w"] for st, v in cons.items() if st in have) / total
    except Exception:  # noqa: BLE001
        return 0.0


def has_figure(h: str, cons: dict) -> bool:
    """The headline carries a figure most outlets' headlines carry."""
    try:
        have = {st for st, _ in words(h)}
        return any(st[0].isdigit() and st in have for st in cons)
    except Exception:  # noqa: BLE001
        return False


def outlet_lines(titles, n: int = OUTLETS_SHOWN) -> list[str]:
    """The outlets' own headlines to show the model (one per outlet, the ones with most shared words first)."""
    try:
        rows = _rows(titles)
        cons = consensus(titles)
        rows.sort(key=lambda r: -coverage(r[1], cons))
        return [t for _, t in rows[:n]]
    except Exception:  # noqa: BLE001
        return []


# ------------------------------------------------------------------------------------------------ quotes
_DQ = re.compile(r"[“\"]([^“”\"]{8,160}?)[”\"]")
_SAID = re.compile(r"^[\s,.;:]*([A-Z][\w.'’ -]{2,60}?)\s+(?:said|says|stated|added|told|alleged|asked|noted|claimed|"
                   r"warned|wrote|argued|insisted|declared|demanded)\b")


def _norm(s: str) -> str:
    s = (s or "").replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).lower().strip()


def quotes(items) -> list[tuple[str, str]]:
    """[(exact words, speaker)] a headline may quote: a quoted span of 3-10 words in a statement, with the speaker named by the
    statement's own speaker or by the "..., X said" after it. Best-reported statements first, at most three."""
    out: list[tuple[int, str, str]] = []
    try:
        for i in items or []:
            txt = i.get("text") or ""
            sp0 = i.get("speaker") if isinstance(i.get("speaker"), str) else ""
            for m in _DQ.finditer(txt):
                q = m.group(1).strip().rstrip(",.;")
                if not QUOTE_WORDS[0] <= len(q.split()) <= QUOTE_WORDS[1]:
                    continue
                m2 = _SAID.match(txt[m.end():])
                sp = (m2.group(1).strip() if m2 else "") or sp0
                if sp and len(sp.split()) <= 5:
                    out.append((i.get("n_sources") or 0, q, sp))
    except Exception as e:  # noqa: BLE001
        log.info("headlinekit.quotes: %s", str(e)[:120])
        return []
    out.sort(key=lambda x: -x[0])
    seen, res = set(), []
    for _, q, sp in out:
        if q.lower() not in seen:
            seen.add(q.lower())
            res.append((q, sp))
    return res[:3]


_QUOTED = re.compile(r"[“\"]([^“”\"]+)[”\"]|(?<![A-Za-z0-9])[‘']([^’']{3,100})[’'](?![A-Za-z0-9])")


def quote_problem(h: str, facts: str, quoted: list[tuple[str, str]] = ()) -> str | None:
    """A quotation in a headline must be in the statements letter for letter. A span of 4+ words must lie inside one of `quoted`
    (an exact quote with a speaker) and that speaker must be named in the headline; a span of 1-3 words (a quoted name or term)
    only has to be in the statements. None when fine or when there is no quotation."""
    try:
        spans = [(m.group(1) or m.group(2) or "").strip() for m in _QUOTED.finditer(h or "")]
        spans = [s for s in spans if s]
        if not spans:
            return None
        nf = _norm(facts)
        rest = _norm(_QUOTED.sub(" ", h))
        for s in spans:
            ns = _norm(s).rstrip(".,;:!… ")
            if ns not in nf:
                return f"the quoted words '{s}' are not in the statements letter for letter: quote exact words only"
            if len(ns.split()) <= 3:
                continue
            speakers = [sp for q, sp in quoted if ns in _norm(q)]
            if not speakers:
                return f"the quoted words '{s}' are not one of the QUOTES given"
            names = {w for sp in speakers for w in re.findall(r"[a-z]{3,}", sp.lower())}
            if not any(re.search(rf"\b{re.escape(n)}\b", rest) for n in names):
                return "a quotation needs its speaker named in the headline"
        return None
    except Exception:  # noqa: BLE001 - never block on a fault in this check
        return None


# ------------------------------------------------------------------------------------------------ copies
def _grams(ws: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def copy_problem(h: str, titles) -> str | None:
    """The outlet headline `h` copies (7 words in a row, or 85% of its words for a headline of 6+ words), or None."""
    try:
        hw = re.findall(r"[a-z0-9']+", (h or "").lower())
        hs = set(hw)
        for _, t in _rows(titles):
            tw = re.findall(r"[a-z0-9']+", t.lower())
            if _grams(hw, COPY_RUN) & _grams(tw, COPY_RUN) or (len(hw) >= 6 and len(hs & set(tw)) >= COPY_SHARE * len(hs)):
                return f"it copies an outlet's headline ('{t}'): write it in your own words"
    except Exception:  # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------------------------------------------ skeleton
def skeleton(h: str) -> str:
    """The shape of a headline: N (capitalised) / # (figure) / w (other) for its first three words, and its first verb-like word."""
    toks = (h or "").split()
    shape, verb = [], ""
    for k, t in enumerate(toks):
        if t[0].isdigit():
            shape.append("#")
        elif t[0].isupper():
            shape.append("N")
        else:
            shape.append("w")
            if not verb and k > 0 and len(t) > 3 and t.lower() not in STOP:
                verb = t.lower()
    return "".join(shape[:3]) + ":" + verb


def repetition(h: str, recent, limit: int = 40) -> int:
    """How many of the last `limit` headlines have this headline's skeleton."""
    try:
        sk = skeleton(h)
        return sum(1 for r in list(recent or [])[:limit] if skeleton(r) == sk)
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------------------------------------------ the prompt blocks
def blocks(titles, items) -> dict:
    """Everything `write_headline` adds to its prompt and its scoring: {"cons", "outlets", "must", "quotes", "quoted"}.
    All empty when nothing can be read (the prompt then reads as before)."""
    try:
        cons = consensus(titles)
        lines = outlet_lines(titles)
        qs = quotes(items)
        outlets = ("\nHOW THE OUTLETS HEADLINED IT (what professionals put first; use their facts in your own words, never copy "
                   "a headline):\n" + "\n".join(f"- {t}" for t in lines) + "\n") if lines else ""
        must = ("Most outlets' headlines carry: " + ", ".join(v["word"] for v in cons.values()) + ". Put as many of these as fit "
                "(the figure and the names first).\n") if cons else ""
        qtxt = ("QUOTES (exact words, for headline E; copy them letter for letter and name the speaker):\n"
                + "\n".join(f'- {sp}: "{q}"' for q, sp in qs) + "\n") if qs else ""
        return {"cons": cons, "outlets": outlets + (must if must else ""), "quotes": qtxt, "quoted": qs}
    except Exception as e:  # noqa: BLE001
        log.info("headlinekit.blocks: %s", str(e)[:120])
        return {"cons": {}, "outlets": "", "quotes": "", "quoted": []}

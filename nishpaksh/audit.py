"""Read-only audits of published articles (owner, Oct 16 2026; session 1 of the translation and learning plan).

Measure before building: four questions the plan's later sessions depend on, answered on stored real articles with no
model call. Every function here is pure (plain inputs, plain results) so it is tested without a database; the thin reader
is `nishpaksh.tools.audit`, which runs on GitHub's runner against the newsroom and writes one `diagnostics` row (kind
'audit').

1. Missed merges, by the language mix of the story's sources (en / hi / mixed): pairs of a story's statements that share
   most of their root words but stayed apart, how many of those code (`relate.relate`) calls "different", how many carry
   a clock time ("12:30 PM", read as the numbers 12 and 30), and the pairs the model was ASKED about and said "different"
   (`analysis.same_checks`). The owner's hunch: Hindi-sourced statements miss merges English-only ones do not.
2. English left in Hindi pages: Latin words inside Hindi strings, strings left wholly in English (untranslated), the
   leftover words most seen, by field.
3. Repeated openings: sentences of one paragraph opening with the same two words as the one before ("Modi will ...").
4. Mixed forms inside one article: "October 15" and "15 October", "₹" and "rupees", "per cent" and "%".
"""
from __future__ import annotations

import collections
import re

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN_WORD = re.compile(r"(?<![\w/.@])[A-Za-z][A-Za-z'’.-]*[A-Za-z]|(?<![\w/.@])[A-Za-z](?![\w])")
URL = re.compile(r"https?://\S+|www\.\S+")
# Latin that belongs in a Hindi news sentence: units and symbols readers know in this form
LATIN_OK = {"km", "kg", "cm", "mm", "mw", "kv", "gw", "kwh", "ml", "mg", "gb", "mb", "rs", "am", "pm"}
CLOCK = re.compile(r"\b\d{1,2}[:.]\d{2}\s*(?:a\.?m\.?|p\.?m\.?|hrs|hours|IST)\b|\b\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
MONTH_FIRST = re.compile(rf"\b{MONTHS}\.?\s+\d{{1,2}}\b")
DAY_FIRST = re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTHS}\b")
RUPEE_SIGN = re.compile(r"₹|\bRs\.?\s?\d|\bINR\b")
RUPEE_WORD = re.compile(r"\d[\d,.]*\s*(?:lakh|crore|million|billion)?\s*rupees\b", re.I)
PER_CENT = re.compile(r"\bper\s?cent\b|\bpercent\b", re.I)
PCT_SIGN = re.compile(r"\d\s?%")
STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "by", "with", "from", "as", "is", "was",
        "were", "are", "be", "been", "has", "have", "had", "that", "this", "it", "its", "will", "would", "said", "says"}


# ------------------------------------------------------------------ 1. missed merges

def roots(text: str) -> set[str]:
    """Root words of a statement, stop words and numbers out (Snowball stemmer, as relate.py)."""
    from .frames import _stem
    words = re.findall(r"[a-z]+", (text or "").lower())
    return {_stem(w) for w in words if w not in STOP and len(w) > 2}


def near_pairs(texts: dict[int, str], min_share: float = 0.6, min_roots: int = 5) -> list[tuple[int, int, float]]:
    """Pairs of statements sharing at least `min_share` of their root words (Jaccard), each with `min_roots`+ roots:
    candidates for "the same fact, left apart". Best first."""
    r = {i: roots(t) for i, t in texts.items()}
    ids = sorted(i for i in r if len(r[i]) >= min_roots)
    out = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            j = len(r[a] & r[b]) / len(r[a] | r[b])
            if j >= min_share:
                out.append((a, b, round(j, 2)))
    return sorted(out, key=lambda x: -x[2])


def has_clock(text: str) -> bool:
    return bool(CLOCK.search(text or ""))


def merge_report(texts: dict[int, str], asked: dict[str, bool], relate_fn=None) -> dict:
    """One story's merge numbers. `asked`: analysis.same_checks (key -> the twice-asked answer; "f..." and "c..." keys are
    first answers and covers questions, left out). `relate_fn(a, b)` -> code's verdict, when given."""
    pairs = near_pairs(texts)
    out = {"statements": len(texts), "near_pairs": len(pairs),
           "near_with_clock": sum(1 for a, b, _ in pairs if has_clock(texts[a]) or has_clock(texts[b])),
           "asked": sum(1 for k in asked if not k[:1] in ("f", "c")),
           "asked_no": sum(1 for k, v in asked.items() if k[:1] not in ("f", "c") and v is False),
           "examples": [[texts[a][:160], texts[b][:160], j] for a, b, j in pairs[:3]]}
    if relate_fn is not None:
        verdicts = collections.Counter(relate_fn(texts[a], texts[b]) for a, b, _ in pairs)
        out["code_verdicts"] = dict(verdicts)
    return out


# ------------------------------------------------------------------ 2. English in Hindi pages

def latin_words(text: str) -> list[str]:
    """Latin words left inside a Hindi string (URLs, and units like km, kg, MW, left out)."""
    t = URL.sub(" ", text or "")
    return [w for w in LATIN_WORD.findall(t) if w.lower().strip(".") not in LATIN_OK]


def hindi_strings(payload_hi: dict) -> list[tuple[str, str]]:
    """(field, text) of what a reader sees on the Hindi page."""
    p = payload_hi or {}
    out = [("headline", p.get("headline") or "")]
    nar = p.get("narrative") or {}
    keys = nar.get("section_keys") or []
    for k, para in enumerate(nar.get("paragraphs") or []):
        field = f"section:{keys[k]}" if k < len(keys) and keys[k] else "section:?"
        out += [(field, s.get("text") or "") for s in para or []]
    out += [("also", x.get("text") or "") for x in nar.get("other_coverage") or []]
    return [(f, t) for f, t in out if t.strip()]


def hindi_report(payload_hi: dict) -> dict:
    """One Hindi page: strings, wholly English strings, strings with Latin words inside, the words."""
    strings = hindi_strings(payload_hi)
    untranslated, with_latin, words, by_field = 0, 0, collections.Counter(), collections.Counter()
    for field, t in strings:
        if not DEVANAGARI.search(t):
            untranslated += 1
            by_field[f"{field.split(':')[0]}:untranslated"] += 1
            continue
        lw = latin_words(t)
        if lw:
            with_latin += 1
            by_field[field.split(":")[0]] += 1
            words.update(lw)
    return {"strings": len(strings), "untranslated": untranslated, "with_latin": with_latin,
            "latin_words": sum(words.values()), "words": dict(words), "by_field": dict(by_field)}


# ------------------------------------------------------------------ 3. repeated openings

def opening(text: str, n: int = 2) -> str:
    return " ".join(re.findall(r"[\w'’-]+", (text or "").lower())[:n])


def openings_report(paragraphs: list[list[dict]]) -> dict:
    """Sentences opening with the same two words as the sentence before, in the same paragraph; and runs of 3+."""
    sentences, alike, runs = 0, 0, 0
    examples = []
    for para in paragraphs or []:
        texts = [s.get("text") or "" for s in para or []]
        sentences += len(texts)
        run = 1
        for prev, cur in zip(texts, texts[1:]):
            if opening(prev) and opening(prev) == opening(cur):
                alike += 1
                run += 1
                if len(examples) < 3:
                    examples.append(opening(cur))
            else:
                runs += run >= 3
                run = 1
        runs += run >= 3
    return {"sentences": sentences, "alike": alike, "runs_of_3": runs, "examples": examples}


# ------------------------------------------------------------------ 4. mixed forms

def forms_report(text: str) -> dict:
    """Which of the pairs of written forms appear together in one article."""
    t = text or ""
    return {"date_both": bool(MONTH_FIRST.search(t)) and bool(DAY_FIRST.search(t)),
            "money_both": bool(RUPEE_SIGN.search(t)) and bool(RUPEE_WORD.search(t)),
            "percent_both": bool(PER_CENT.search(t)) and bool(PCT_SIGN.search(t)),
            "clock_times": len(CLOCK.findall(t))}


def article_text(payload: dict) -> str:
    nar = (payload or {}).get("narrative") or {}
    return " ".join(s.get("text") or "" for para in nar.get("paragraphs") or [] for s in para or [])


# ------------------------------------------------------------------ the whole report

def language_mix(langs: set[str]) -> str:
    """'en', 'hi' or 'mixed', by the languages of the articles a story was read from."""
    langs = {(x or "en")[:2] for x in langs} or {"en"}
    return "mixed" if len(langs) > 1 else next(iter(langs))


def summarise(stories: list[dict]) -> dict:
    """`stories`: [{id, mix, merge, hindi, openings, forms}] -> totals and rates by language mix."""
    out: dict = {"stories": len(stories), "by_mix": {}}
    for mix in ("en", "hi", "mixed"):
        grp = [s for s in stories if s["mix"] == mix]
        if not grp:
            continue
        m = [s["merge"] for s in grp if s.get("merge")]
        h = [s["hindi"] for s in grp if s.get("hindi")]
        o = [s["openings"] for s in grp if s.get("openings")]
        f = [s["forms"] for s in grp if s.get("forms")]
        st = sum(x["statements"] for x in m) or 1
        hs = sum(x["strings"] for x in h) or 1
        se = sum(x["sentences"] for x in o) or 1
        verdicts = collections.Counter()
        for x in m:
            verdicts.update(x.get("code_verdicts") or {})
        out["by_mix"][mix] = {
            "stories": len(grp),
            "merge": {"statements": sum(x["statements"] for x in m), "near_pairs": sum(x["near_pairs"] for x in m),
                      "near_pairs_per_100_statements": round(100 * sum(x["near_pairs"] for x in m) / st, 1),
                      "near_with_clock": sum(x["near_with_clock"] for x in m), "code_verdicts": dict(verdicts),
                      "asked": sum(x["asked"] for x in m), "asked_no": sum(x["asked_no"] for x in m)},
            "hindi": {"strings": sum(x["strings"] for x in h), "untranslated": sum(x["untranslated"] for x in h),
                      "with_latin": sum(x["with_latin"] for x in h),
                      "with_latin_pct": round(100 * sum(x["with_latin"] for x in h) / hs, 1),
                      "untranslated_pct": round(100 * sum(x["untranslated"] for x in h) / hs, 1)},
            "openings": {"sentences": sum(x["sentences"] for x in o), "alike": sum(x["alike"] for x in o),
                         "alike_pct": round(100 * sum(x["alike"] for x in o) / se, 1),
                         "runs_of_3": sum(x["runs_of_3"] for x in o)},
            "forms": {k: sum(1 for x in f if x[k]) for k in ("date_both", "money_both", "percent_both")}
            | {"articles": len(f), "with_clock_times": sum(1 for x in f if x["clock_times"])},
        }
    words = collections.Counter()
    fields = collections.Counter()
    for s in stories:
        words.update((s.get("hindi") or {}).get("words") or {})
        fields.update((s.get("hindi") or {}).get("by_field") or {})
    out["latin_top_words"] = words.most_common(40)
    out["latin_by_field"] = dict(fields)
    out["merge_examples"] = [{"id": s["id"], "mix": s["mix"], "pairs": s["merge"]["examples"]}
                             for s in sorted(stories, key=lambda s: -(s.get("merge") or {}).get("near_pairs", 0))[:8]
                             if (s.get("merge") or {}).get("near_pairs")]
    return out

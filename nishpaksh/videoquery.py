"""What to search YouTube for, and what a found video must share with the story (owner, Oct 12 2026).

Why this exists. The videos step searched with the story's raw statement fields (`who`, `what`, `where`: whole
phrases, often with figures: "Rs 661.50 crore deal for BrahMos launchers") and sent the SAME English words for
the Hindi search too, then kept a video only if its title shared two words with the HEADLINE. Three ways to
find nothing: a figure no video title repeats, English words for a Hindi search, and a headline that is now
written to be read, not matched (news.py, Oct 12), so it shares fewer words with a video's title.

Now, by code and without any call:
  * numbers, money and ordinals are taken out of every query (titles of videos on one event rarely agree on a figure);
  * the keywords of a story are its NAMES (people, bodies, places) ranked by how many statements carry them, plus
    the main act; the English search uses them, the Hindi search uses the Hindi headline's own words;
  * a second, shorter search is made only when the first one left fewer than 2 usable videos;
  * a video is relevant when its title shares two root words with the story's keywords (names, English headline,
    Hindi headline together), never with the headline alone.
No file here imports the database, so all of it is tested on plain text (tests/test_videos.py).
"""
from __future__ import annotations

import re

# words that say nothing about WHICH story (a video titled "Big news live today" matches every story)
STOP = set("""the a an and or of to in on at for with from by as is are was were be been has have had will would after
before over under into about than this that these those its his her their new says said news live video latest update
updates today full what why how who when where watch big breaking report reports की के का में से पर और है हैं को ने
भी एक यह वह लिए साथ बाद तक कर किया गया गई गए हुआ हुई रहा रही रहे ख़बर खबर""".split())

# figures in any form: digits (Latin and Devanagari), spelled numbers, money and units, ordinals
NUMBERISH = re.compile(
    r"(?i)(?<![\w])(?:rs\.?|inr|usd|us\$|₹|\$)?\s*[\d०-९][\d०-९,.]*(?:st|nd|rd|th|%)?(?![\w])"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|"
    r"thousand|lakh|lakhs|crore|crores|million|billion|trillion|percent|per cent|dozen)\b"
    r"|(?:लाख|करोड़|करोड|हज़ार|हजार|प्रतिशत|रुपये|रुपए|रुपया)")
# the verb that names the act, kept as one keyword; speech and being verbs name nothing
BARE_ACTS = {"said", "says", "is", "are", "was", "were", "has", "have", "had", "will", "would", "can", "could",
             "may", "might", "also", "not", "been", "being", "held", "made", "gave", "took", "went", "came"}
# names too general to find ONE story with
GENERIC_NAMES = {"india", "indian", "government", "centre", "police", "court", "minister", "ministry", "state",
                 "delhi", "new delhi", "country", "people", "party", "leader", "leaders", "officials", "sources", "reports"}

MAX_QUERY_WORDS = 7


def strip_numbers(text: str | None) -> str:
    """The text with every figure, amount and ordinal taken out, spaces closed."""
    t = NUMBERISH.sub(" ", text or "")
    return re.sub(r"\s+", " ", t).strip(" ,.;:-")


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*|[\u0900-\u097f]+", text or "")


def roots(text: str | None) -> set[str]:
    """Root words of a title or headline: lower case, Latin words trimmed to 5 letters, Devanagari kept whole.
    Figures never count (they are not words)."""
    out = set()
    for w in _words(strip_numbers(text)):
        w = w.lower().strip("'’-")
        if w in STOP or (w.isascii() and len(w) < 3):
            continue
        out.add(w[:5] if w.isascii() else w)
    return out


def _capitalised_run(text: str) -> list[str]:
    """Names inside a phrase: runs of capitalised words ('Delhi Police', 'BrahMos'), figures removed."""
    out, run = [], []
    for tok in re.findall(r"[A-Za-z][\w'’.-]*|[^\sA-Za-z]+", strip_numbers(text)):
        if tok[0].isupper() and tok.lower() not in STOP:
            run.append(tok)
        else:
            if run:
                out.append(" ".join(run))
            run = []
    if run:
        out.append(" ".join(run))
    return out


def _short(phrase: str, limit: int = 4) -> str:
    return " ".join(phrase.split()[:limit])


def entities(frames: list[dict], limit: int = 4) -> list[str]:
    """The names a story is about, most-carried first. `frames` are the statement frames
    ({who, action, what, value, where}); a name counts once per statement that carries it, so what many outlets
    repeat comes first. A phrase wholly inside a longer one ('Modi' in 'Narendra Modi') is folded into it."""
    count: dict[str, int] = {}
    shown: dict[str, str] = {}
    for fr in frames:
        seen = set()
        for field in ("who", "where", "what"):
            val = (fr or {}).get(field) or ""
            # who/where are short names already; `what` is a phrase: only its proper names are wanted
            names = _capitalised_run(val) if field == "what" else [strip_numbers(val)]
            for nm in names:
                nm = _short(nm)
                key = nm.lower()
                if len(nm) < 3 or key in GENERIC_NAMES or key in STOP or key in seen:
                    continue
                seen.add(key)
                count[key] = count.get(key, 0) + 1
                shown.setdefault(key, nm)
    ranked = sorted(count, key=lambda k: (-count[k], list(count).index(k)))
    keep: list[str] = []
    have_roots: list[set[str]] = []
    for k in ranked:
        if any(k in other for other in ranked if other != k and count[other] >= count[k]):
            continue       # folded into the longer name that is carried at least as often
        r = roots(k)
        if r and any(r == h for h in have_roots):
            continue       # the same words in another order ("Defence Ministry", "Ministry of Defence")
        have_roots.append(r)
        keep.append(k)
    return [shown[k] for k in keep[:limit]]


def act_word(frames: list[dict]) -> str:
    """The main act as one search word ('arrested'), from the most common action in the frames, or ''."""
    count: dict[str, int] = {}
    for fr in frames:
        a = ((fr or {}).get("action") or "").strip().lower().split()
        if a and a[0].isalpha() and a[0] not in BARE_ACTS and a[0] not in STOP and len(a[0]) >= 4:
            count[a[0]] = count.get(a[0], 0) + 1
    return max(count, key=count.get) if count else ""


def _content(text: str | None, limit: int) -> list[str]:
    out: list[str] = []
    for w in _words(strip_numbers(text)):
        if w.lower() in STOP or (w.isascii() and len(w) < 3):
            continue
        out.append(w)
        if len(out) >= limit:
            break
    return out


def english_query(names: list[str], act: str, headline_en: str, short: bool = False) -> str:
    """Names first (up to 3, within MAX_QUERY_WORDS words), then the act. A story with no names is searched by
    the content words of its headline. `short`: the names only, at most 2 (the second try)."""
    words: list[str] = []
    for nm in names[: 2 if short else 3]:
        parts = nm.split()
        if len(words) + len(parts) > (4 if short else MAX_QUERY_WORDS):
            break
        words += parts
    if not words:
        words = _content(headline_en, 4 if short else MAX_QUERY_WORDS)
    elif act and not short and len(words) < MAX_QUERY_WORDS:
        words.append(act)
    return " ".join(words)


def hindi_query(headline_hi: str, short: bool = False) -> str:
    """The Hindi headline's own content words (figures out): a Hindi search must be made in Hindi."""
    return " ".join(_content(headline_hi, 4 if short else MAX_QUERY_WORDS))


def queries(frames: list[dict], headline_en: str, headline_hi: str, short: bool = False) -> list[tuple[str, str]]:
    """[(query, relevanceLanguage)] for a story: English then Hindi, empty ones left out, no repeats."""
    names = entities(frames)
    act = act_word(frames)
    out = []
    for q, lang in ((english_query(names, act, headline_en, short), "en"), (hindi_query(headline_hi, short), "hi")):
        if q and (q, lang) not in out:
            out.append((q, lang))
    return out


def keywords(frames: list[dict], headline_en: str, headline_hi: str) -> set[str]:
    """The root words a video's title is compared with: the story's names and both headlines, figures out."""
    out = roots(headline_en) | roots(headline_hi)
    for nm in entities(frames, limit=6):
        out |= roots(nm)
    return out


def name_keywords(frames: list[dict]) -> set[str]:
    """The root words of the story's NAMES alone (people, bodies, places): what a loosely related video shares."""
    out: set[str] = set()
    for nm in entities(frames, limit=6):
        out |= roots(nm)
    return out


def loosely_relevant(title: str, names: set[str]) -> bool:
    """A weaker bar (owner, Oct 12 2026: a slightly unrelated recent video beats none): the title shares at least
    one root word with the story's NAMES. Titles with no name of the story (audiobooks, drama, ads) stay out."""
    return bool(roots(title) & names)


def relevant(title: str, kw: set[str]) -> bool:
    """A video is about this story when its title shares at least two root words with the story's keywords."""
    return len(roots(title) & kw) >= 2

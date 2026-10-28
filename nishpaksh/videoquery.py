"""What to search YouTube for, which videos are in a language we are SURE of, and how to rank them (owner, Oct 12 2026).

Why this was rebuilt. The first design searched the story's NAMES and demanded two shared words in a video's title.
It found almost nothing: a video about the same event rarely repeats a story's names and words. Scrapped.

The idea now (owner's):
  1. SEARCH VAGUE. Take the headline and keep only the kind of event, no names, no figures: "Delhi Police releases
     detained CJP leader Abhijit after conditional bond" -> "release of detained leader"; "Rahul Gandhi announces Monday
     opposition march to Supreme Court over election disputes" -> "opposition march". A vague phrase always brings
     videos back. One small model call writes the phrase (checked by code); without a model, code writes it.
  2. RANK BY SIMILARITY. Every video found is scored against the story's own words (the headline and the article's
     text; English videos against the English article, Hindi videos against the Hindi one) and the best are kept.
  3. LANGUAGE ONLY WHEN SURE. A video is shown as English or Hindi only when its title and YouTube's language tags
     leave no doubt (an English search once returned a Bengali video that was then labelled English). Any other script,
     Marathi/Nepali in Devanagari, romanised Hindi, an unclear title: not shown.
No file here imports the database, so all of it is tested on plain text (tests/test_videos.py).
"""
from __future__ import annotations

import math
import re

from . import auditcount, langid

# words that say nothing about WHICH story (a video titled "Big news live today" matches every story)
STOP = set("""the a an and or of to in on at for with from by as is are was were be been has have had will would after
before over under into about against amid than this that these those its his her their new says said news live video latest update
updates today full what why how who when where watch big breaking report reports की के का में से पर और है हैं को ने
भी एक यह वह लिए साथ बाद तक कर किया गया गई गए हुआ हुई रहा रही रहे ख़बर खबर""".split())

# figures in any form: digits (Latin and Devanagari), money, ordinals
NUMBERISH = re.compile(r"(?i)(?<![\w])(?:rs\.?|inr|usd|us\$|₹|\$)?\s*[\d०-९][\d०-९,.]*(?:st|nd|rd|th|%)?(?![\w])")

MAX_PHRASE_WORDS = 5


def strip_numbers(text: str | None) -> str:
    t = NUMBERISH.sub(" ", text or "")
    return re.sub(r"\s+", " ", t).strip(" ,.;:-")


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*|[\u0900-\u097f]+", text or "")


def roots(text: str | None) -> set[str]:
    """Root words: lower case, Latin words trimmed to 5 letters, Devanagari kept whole. Figures and stop words out."""
    out = set()
    for w in _words(strip_numbers(text)):
        w = w.lower().strip("'’-")
        if w in STOP or (w.isascii() and len(w) < 3):
            continue
        out.add(w[:5] if w.isascii() else w)
    return out


# ------------------------------------------------------------------------------------------------ the search phrase
def _capitalised_inside(headline: str) -> set[str]:
    """Lower-cased words the headline writes with a capital (names, places, bodies) after its first word."""
    ws = _words(headline)
    return {w.lower() for w in ws[1:] if w[0].isupper()}


def code_phrase(headline: str, limit: int = 3) -> str:
    """The vague phrase made by code: the headline's plain content words, names and figures left out. A headline
    written in Title Case (most words capitalised) keeps every content word. Used when no model answered."""
    ws = _words(strip_numbers(headline))
    if not ws:
        return ""
    deva = any("\u0900" <= ch <= "\u097f" for ch in headline)
    caps = [w for w in ws if w[0].isupper()]
    title_case = len(caps) > 0.6 * len(ws)
    out: list[str] = []
    for w in ws:
        if w.lower() in STOP or (w.isascii() and len(w) < 3):
            continue
        if not deva and not title_case and (w[0].isupper() or w.isupper()):
            continue                        # a name, a place, a body: too specific
        out.append(w.lower() if not deva else w)
        if len(out) >= limit:
            break
    if not out:                             # everything was a name: the first content words, as written
        out = [w for w in ws if w.lower() not in STOP][:2]
    return " ".join(out)


def clean_phrase(phrase: str | None, headline: str, deva: bool, thread: list[str] | None = None) -> str:
    """The model's phrase if it is usable, else ''. Usable: 1-5 words, no figure, in the right script, no name of
    the headline (or of the story's earlier headlines, `thread`), and (English) it shares a word beginning with
    the headline's or an earlier one's."""
    p = re.sub(r"\s+", " ", (phrase or "").strip().strip("\"'`“”.,;:")).strip()
    if not p or re.search(r"[\d०-९]", p):
        return ""
    ws = p.split()
    if not 1 <= len(ws) <= MAX_PHRASE_WORDS:
        return ""
    has_deva = any("\u0900" <= ch <= "\u097f" for ch in p)
    if deva != has_deva or (not deva and not p.isascii()):
        return ""
    if not deva:
        names = set()
        for h in [headline] + list(thread or []):
            names |= _capitalised_inside(h)
        if any(w.lower().strip("'’-") in names for w in ws):
            return ""
        heads = {w.lower()[:4] for h in [headline] + list(thread or []) for w in _words(h) if len(w) >= 4}
        if not any(w.lower()[:4] in heads for w in ws if len(w) >= 4):
            return ""
    return p.lower() if not deva else p


PHRASE_PROMPT = """You write YouTube search phrases for news headlines.
For each headline write the VAGUE phrase a person would type to find videos about this KIND of event: only the main
act or event, 2 to 4 plain words, grammatical. NO names of people, parties, places or outlets. NO numbers.
Write the English phrase for the English headline and the Hindi phrase (in Devanagari) for the Hindi headline.

Examples:
Delhi Police releases detained CJP leader Abhijit after conditional bond -> release of detained leader
Rahul Gandhi announces Monday opposition march to Supreme Court over election disputes -> opposition march
Donald Trump waives sanctions on Russian diesel while demanding Zelensky be replaced -> waiving of sanctions
RBI keeps repo rate unchanged at 5.5 per cent -> repo rate decision
If unsure: the two most important plain words of the headline.

English headline: {en}
Hindi headline: {hi}

{thread}Reply with JSON only: {{"en": "...", "hi": "..."}}"""

THREAD_NOTE = """EARLIER HEADLINES OF THE SAME ONGOING STORY (the headline above is only its newest step, written to say what
is new):
{lines}
Videos exist about the ONGOING story or process, not about the newest step alone. Write the phrase for the ongoing
event these headlines share, in plain words, still with no names and no numbers.

"""


def phrases(headline_en: str, headline_hi: str, router=None, thread_en: list[str] | None = None,
            thread_hi: list[str] | None = None) -> dict[str, str]:
    """{"en": phrase, "hi": phrase} (a language with no words is left out). One small model call, every answer checked
    by `clean_phrase`; whatever the model did not give usably, code writes. `thread_en`/`thread_hi`: the headlines
    of the story's earlier stories (parents, nearest first): the follow-up's own headline says only what is new, so
    the model is asked for the phrase of the whole ongoing story. Same single call, no extra quota."""
    out = {"en": "", "hi": ""}
    thread_en, thread_hi = [h for h in thread_en or [] if h], [h for h in thread_hi or [] if h]
    if router is not None and (headline_en or headline_hi):
        try:
            lines = [f"English: {e}" + (f" | Hindi: {h}" if h else "") for e, h in zip(thread_en, thread_hi + [""] * len(thread_en))]
            lines += [f"Hindi: {h}" for h in thread_hi[len(thread_en):]]
            note = THREAD_NOTE.format(lines="\n".join(lines)) if lines else ""
            res = router.call("page", PHRASE_PROMPT.format(en=headline_en or "-", hi=headline_hi or "-", thread=note),
                              json_out=True, max_output_tokens=200)
            data = res.data if isinstance(res.data, dict) else {}
            out["en"] = clean_phrase(data.get("en"), headline_en or "", deva=False, thread=thread_en) if headline_en else ""
            out["hi"] = clean_phrase(data.get("hi"), headline_hi or "", deva=True, thread=thread_hi) if headline_hi else ""
        except Exception:  # noqa: BLE001  (quota, refusal, bad JSON: code does it)
            pass
    if not out["en"] and headline_en:
        out["en"] = code_phrase(headline_en)
    if not out["hi"] and headline_hi:
        out["hi"] = code_phrase(headline_hi)
    return {k: v for k, v in out.items() if v}


# ------------------------------------------------------------------------------------------------ the story's words
THREAD_WEIGHT = 2.0       # a word of an earlier headline of the same story (the video may use the story's old words)
NEIGHBOUR_WEIGHT = 0.75   # a word that two or more other recent headlines on this topic share (a weak topic hint)
NEIGHBOUR_MIN = 2         # ...one other headline alone says nothing about THIS story, so it adds nothing
NEIGHBOUR_SHARED = 2      # a recent headline is a topic neighbour when it shares this many root words with the headline
NEIGHBOURS_MAX = 6


def neighbours(headline: str, pool: list[str], n: int = NEIGHBOURS_MAX) -> list[str]:
    """The recent headlines of OTHER stories nearest this one: those sharing at least NEIGHBOUR_SHARED root words
    with `headline`, most shared first. Not the story's own thread (the caller leaves that out of `pool`)."""
    mine = roots(headline)
    scored = []
    for h in pool:
        shared = len(mine & roots(h))
        if h and h != headline and shared >= NEIGHBOUR_SHARED:
            scored.append((shared, h))
    scored.sort(key=lambda t: -t[0])
    out: list[str] = []
    for _, h in scored:
        if h not in out:
            out.append(h)
    return out[:n]


def document(headline: str, paragraphs: list[str] | None = None, thread: list[str] | None = None,
             neighbours: list[str] | None = None) -> dict[str, float]:
    """root word -> weight for one language of one story: a headline word weighs 3, and a word of the article adds
    half a point per mention (at most four mentions), so what the article keeps coming back to counts most.

    Owner, Oct 13 2026: headlines now avoid repeating the story's earlier ones, so a follow-up's headline names only
    what is new, while videos are titled for the ongoing story. So the words of the story's earlier headlines
    (`thread`) weigh at least THREAD_WEIGHT even when this article never uses them, and a word that two or more
    other recent headlines on the topic (`neighbours`, other stories) share weighs at least NEIGHBOUR_WEIGHT. These
    only RAISE a weight to that floor; the headline's and the article's own words keep theirs."""
    w: dict[str, float] = {}
    for r in roots(headline):
        w[r] = 3.0
    counts: dict[str, int] = {}
    for para in paragraphs or []:
        for word in _words(strip_numbers(para)):
            word = word.lower().strip("'’-")
            if word in STOP or (word.isascii() and len(word) < 3):
                continue
            r = word[:5] if word.isascii() else word
            counts[r] = counts.get(r, 0) + 1
    for r, n in counts.items():
        w[r] = w.get(r, 0.0) + 0.5 * min(n, 4)
    for h in thread or []:
        for r in roots(h):
            w[r] = max(w.get(r, 0.0), THREAD_WEIGHT)
    seen_in: dict[str, int] = {}
    for h in neighbours or []:
        for r in roots(h):
            seen_in[r] = seen_in.get(r, 0) + 1
    for r, k in seen_in.items():
        if k >= NEIGHBOUR_MIN:
            w[r] = max(w.get(r, 0.0), NEIGHBOUR_WEIGHT)
    return w


def scores(videos: list[dict], doc: dict[str, float]) -> list[float]:
    """Similarity of each video (title, and its short description at a third of the weight) to the story's words.
    A word in most of the found titles (the search words themselves) counts less (inverse document frequency)."""
    n = len(videos)
    title_roots = [roots(v.get("title")) for v in videos]
    df: dict[str, int] = {}
    for tr in title_roots:
        for r in tr:
            df[r] = df.get(r, 0) + 1

    def idf(r: str) -> float:
        return 1.0 if n < 3 else math.log((n + 1) / (df.get(r, 0) + 1)) + 1.0
    out = []
    for v, tr in zip(videos, title_roots):
        s = sum(doc.get(r, 0.0) * idf(r) for r in tr)
        s += 0.33 * sum(doc.get(r, 0.0) for r in roots(v.get("desc")) - tr)
        out.append(s / math.sqrt(max(len(tr), 1)))
    return out


# ------------------------------------------------------------------------------------------------ language, if sure
HINDI_WORDS = {"है", "हैं", "में", "के", "की", "का", "को", "से", "ने", "और", "पर", "यह", "था", "थे", "थी", "रहा", "रहे",
               "रही", "गया", "गए", "गई", "कर", "किया", "लिए", "क्या", "कैसे", "बाद", "तक", "नहीं", "भी", "वो", "यहां"}
# Devanagari is also Marathi, Nepali and Sanskrit: these words are theirs, not Hindi's
OTHER_DEVA = {"आहे", "आणि", "नाही", "मध्ये", "च्या", "ची", "चे", "साठी", "झाले", "झाला", "आहेत", "छ", "हुन्छ", "भयो",
              "गर्छ", "गरेको", "लाई", "छन्", "पनि", "र", "अनि", "तथा", "भएको", "गर्न", "बाट"}
ROMAN_HINDI = {"kya", "hai", "hain", "mein", "kaise", "kyun", "kyon", "nahi", "nahin", "aur", "ki", "ka", "ke", "ko",
               "se", "tha", "thi", "hua", "hui", "kab", "kaun", "bada", "badi", "ne", "par", "yeh", "ye", "wo", "abhi",
               "kiya", "gaya", "gayi", "raha", "rahi", "rahe", "sabse", "lekin", "ab", "bhi", "toh", "ek", "liye",
               "kuch", "sach", "jaaniye", "dekhiye", "bol", "khabar"}
ENGLISH_WORDS = {"the", "of", "to", "in", "on", "at", "for", "with", "over", "after", "as", "is", "are", "was", "were", "and",
                 "by", "from", "says", "said", "will", "has", "have", "amid", "against", "after", "before", "that",
                 "how", "why", "what", "who", "his", "her", "its", "their", "not", "be", "into", "out", "new", "live",
                 "vs", "about", "may", "can", "could", "would", "under", "up", "down", "than", "but", "or"}


def _script_letters(title: str) -> tuple[int, int, int]:
    """(latin ascii, devanagari, other) letter counts of a title; digits and punctuation are not letters."""
    latin = deva = other = 0
    for ch in title:
        if not ch.isalpha():
            continue
        if ch.isascii():
            latin += 1
        elif "\u0900" <= ch <= "\u097f":
            deva += 1
        else:
            other += 1      # any other script, or an accented Latin letter (Spanish, French, Turkish...)
    return latin, deva, other


def _tag(*tags: str | None) -> str | None:
    """The primary language subtag of YouTube's audio/default language, lower case ('hi-IN' -> 'hi'), or None."""
    for t in tags:
        t = (t or "").strip().lower()
        if t:
            return re.split(r"[-_]", t)[0]
    return None


def video_language(title: str, tag: str | None = None, channel_lang: str | None = None) -> str | None:
    """'hi' or 'en' only when sure, else None.

    Never sure: a title with any letter outside plain Latin and Devanagari (Bengali, Tamil, Urdu, accented Latin);
    a language tag that is neither hi nor en; romanised Hindi (Hinglish).
    Hindi: Devanagari title; the tag says hi, or there is no tag and the title has a Hindi function word and none of
    Marathi's or Nepali's.  English: plain Latin title with no romanised-Hindi word, and the tag says en (or the
    channel is a known English channel), or there is no tag and the title has an English function word."""
    latin, deva, other = _script_letters(title or "")
    if other or latin + deva == 0:
        return None
    tag = _tag(tag)
    if tag is not None and tag not in ("hi", "en"):
        return None
    words = {w.lower().strip("'’-") for w in _words(title)}
    sure = _model_language(title)
    if deva > latin:
        if latin > 0.25 * (latin + deva):
            return None
        if tag == "en":
            return None
        deva_words = {w for w in words if "\u0900" <= w[0] <= "\u097f"}
        if deva_words & OTHER_DEVA:
            return None
        old = bool(tag == "hi" or deva_words & HINDI_WORDS)
        # the model reads the Devanagari title: Hindi when it leads (Marathi and Nepali are told apart or vetoed above)
        if sure is not None:
            new = bool(tag == "hi" or (sure[0] == "hindi" and sure[2] >= langid.HI_MARGIN))
            _count("hi", old, new)
            return "hi" if new else None
        return "hi" if old else None
    if deva:                                # a few Devanagari letters in a Latin title: not clear
        return None
    if tag == "hi":
        return None
    old_veto = bool(words & ROMAN_HINDI)
    old_en = not old_veto and bool(tag == "en" or channel_lang == "en" or words & ENGLISH_WORDS)
    if sure is not None:
        lang, prob, margin = sure
        if lang == "english" and margin >= langid.EN_MARGIN:
            new = True                      # English leads clearly; romanised Hindi never does
        elif lang != "english" and prob >= langid.OTHER_SURE:
            new = False                     # clearly another language (romanised Hindi reads as Swahili, Tagalog ...)
        else:
            new = old_en                    # the model is unsure: the old words decide
        _count("en", old_en, new)
        return "en" if new else None
    return "en" if old_en else None


def _model_language(title: str):
    return langid.identify(title)


def _count(kind: str, old: bool, new: bool) -> None:
    c = auditcount.counter("language")
    c[f"{kind}_asked"] += 1
    if old != new:
        c[f"{kind}_model_{'yes' if new else 'no'}_list_{'no' if new else 'yes'}"] += 1


# ------------------------------------------------------------------------------------------------ shorts
# YouTube Shorts (owner, Oct 13 2026): made by anyone, add nothing to the story; the one reliable sign is how short
# they are. A Short could be up to 60 s, since Oct 2024 up to 3 min, so duration alone cannot catch them all: the
# #shorts tag in the title or description is the second sign. 90 s keeps a real news clip of a minute and a half.
MIN_SECONDS = 90
SHORT_TAG = re.compile(r"(?i)#shorts?\b|\bshorts?\s*video\b|\byoutube\s*shorts?\b")
_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_duration(iso: str | None) -> int | None:
    """Seconds in an ISO 8601 duration as YouTube gives it ('PT1M5S' -> 65), or None when missing, unreadable or
    zero ('P0D' is what a live broadcast reports: its length is not known yet, so it is not called short)."""
    m = _ISO_DURATION.match((iso or "").strip())
    if not m:
        return None
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    total = d * 86400 + h * 3600 + mi * 60 + sec
    return total or None


def is_short(title: str | None, desc: str | None, seconds: int | None, min_seconds: int = MIN_SECONDS) -> bool:
    """A YouTube Short: shorter than `min_seconds` (when the length is known), or tagged as one."""
    if seconds is not None and seconds < min_seconds:
        return True
    return bool(SHORT_TAG.search(f"{title or ''} {desc or ''}"))

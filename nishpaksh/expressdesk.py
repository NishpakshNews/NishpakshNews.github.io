"""The express desk's layouts (owner, Oct 16 2026: "the numbered sections can be different ... the one which maximizes
the coverage"; a layout per kind of story).

A story written from many reports is laid out by what the reports agree and disagree on (narrative.SECTIONS). A story
written from ONE report is laid out by what KIND of story it is, so everything the report has finds its place:

  match     a match or race report (sport): the build-up, how it went, top performers, what they said, the numbers,
            what next
  profile   a person's story or interview: who they are, their journey, in their own words, what next
  results   a company's results: the numbers, what drove them, what management said, the market's reaction, what next
  general   anything else: the story, in their own words, the numbers, how we got here, what next

`kind_of` decides by code from the lane and the statements; `sections` places each statement (starting from
narrative.assign_sections and moving what the layout names differently). The lead ("news") is chosen as before.
"""
from __future__ import annotations

import re
from collections import Counter

LAYOUTS: dict[str, list[str]] = {
    "match": ["news", "background", "happened", "performers", "say", "numbers", "next", "related"],
    "profile": ["news", "who", "journey", "words", "next", "related"],
    "results": ["news", "numbers", "drivers", "say", "market", "next", "related"],
    "general": ["news", "happened", "words", "say", "numbers", "background", "explained", "next", "related"],
}

# one line for the writer per section (the normal sections keep narrative's own descriptions)
SAYS = {
    "background": "the build-up: form, earlier meetings, what was at stake, oldest first",
    "happened": "how it went, in time order, with each turning point",
    "performers": "each standout player or team, with their figures, one paragraph each",
    "say": "what each person or body said (their exact words in quotation marks where given), one speaker per paragraph",
    "numbers": "the figures, each with what it measures",
    "next": "what happens next: fixtures, dates, steps",
    "related": "other events the report connects to this one",
    "who": "who the person is: role, age, where from, what they are known for",
    "journey": "their path so far, oldest first: each step with its time and its figures",
    "words": "the person's own words: their exact quotes in quotation marks, each with what it is about",
    "drivers": "what explains the figures: segments, volumes, costs, prices, one subject per paragraph",
    "market": "how the share price and investors reacted",
    "explained": "what a rule, term or number means",
}

_RESULT = re.compile(r"(?i)\b(?:beat|beats|defeat\w*|won|wins|win|lost|loses|draw|drew|edged|thrash\w*|clinch\w*|"
                     r"knocked out|eliminat\w*|innings|wickets?|goals?|sets?|points?|medal|gold|silver|bronze|final)\b")
_SCORE = re.compile(r"\b\d+\s*[-/]\s*\d+\b|\b\d+\s+(?:runs|wickets|goals|points|sets)\b|\bby \d+")
_MONEY = re.compile(r"(?i)\b(?:profit|revenue|income|ebitda|margin|sales|turnover|quarter|q[1-4]|fy\d{2}|crore|"
                    r"lakh crore|net loss|earnings|dividend)\b")
_MARKET = re.compile(r"(?i)\b(?:shares?|stock|bse|nse|sensex|nifty|traded|trading|market cap\w*|investors?)\b")
_IDENTITY = re.compile(r"(?i)\b(?:years? old|aged \d+|was born|hails from|is known (?:for|as)|is an? |\d+-year-old)")
_NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


def kind_of(lane: str | None, items: list[dict]) -> str:
    texts = [i.get("text") or "" for i in items]
    if not texts:
        return "general"
    if lane == "sport" and sum(1 for t in texts if _RESULT.search(t) and _SCORE.search(t)) >= 2:
        return "match"
    if lane in ("companies", "tech") and sum(1 for t in texts if _MONEY.search(t) and re.search(r"\d", t)) >= 3:
        return "results"
    # one person the story is about: named in most statements (as subject or speaker)
    names = Counter()
    for i in items:
        found = {m.group(0).split()[-1] for m in _NAME.finditer((i.get("text") or "") + " " + (i.get("speaker") or ""))}
        names.update(found)
    if names:
        top, n = names.most_common(1)[0]
        if n >= max(3, 0.6 * len(items)):
            return "profile"
    return "general"


def sections(kind: str, items: list[dict], sec: dict[int, str]) -> dict[int, str]:
    """The layout's section for each statement, from narrative.assign_sections' choice `sec`."""
    from .narrative import _is_figure
    keys = set(LAYOUTS[kind])
    out = {}
    for i in items:
        k = sec.get(i["id"], "happened")
        has_words = bool(i.get("words"))
        figure = _is_figure(i)
        if k == "news":
            out[i["id"]] = "news"
            continue
        if kind == "match":
            if figure and k in ("numbers", "happened") and _NAME.search(i.get("text") or ""):
                k = "performers"
            elif k == "explained":
                k = "background"
        elif kind == "profile":
            if k in ("say",) or has_words:
                k = "words"
            elif k in ("background", "happened", "numbers", "related"):
                k = "journey"
            elif k == "explained":
                k = "who"
            if k == "journey" and i.get("kind") == "claim" and not (i.get("time") or {}).get("start") and (
                    not figure or _IDENTITY.search(i.get("text") or "")):
                k = "who"                       # what they are, not a step on their way
        elif kind == "results":
            t = i.get("text") or ""
            if _MARKET.search(t):
                k = "market"
            elif k == "say" or i.get("speaker"):
                k = "say"
            elif figure:
                k = "numbers"
            elif k in ("happened", "background", "explained"):
                k = "drivers"
        else:                                   # general
            if has_words:
                k = "words"
        out[i["id"]] = k if k in keys else ("happened" if "happened" in keys else LAYOUTS[kind][1])
    return out


def structure(kind: str) -> str:
    """The structure paragraph of the writer's prompt for this layout."""
    lines = "\n".join(f"  {k:<11} {SAYS.get(k, '')}" for k in LAYOUTS[kind] if k != "news")
    return (f"""Structure: this story comes from ONE report and is laid out as a {kind} story. Write EXACTLY ONE paragraph for
each PARAGRAPH below, in that order, from ONLY its statements; never move a statement to another paragraph,
never join or split paragraphs. A PARAGRAPH says how it opens ("opens with ..."): begin it that way. Within a
paragraph write 3-5 sentences, the main point first. The sections:
  news        1-2 sentences, the thing that makes this a story today, with who, where and when, from the statements
              in SECTION news (the first sentence tells the first of them and must cite it)
{lines}
Write only the sections that have statements (and "news"); skip the others. The reader gets EVERYTHING the report
says: use every statement, and write it fully (who, what, when, the figures), not as a list.""")


# headings on the page (site/index.html reads them from the payload for the keys narrative.SECTIONS lacks)
LABELS = {
    "en": {"performers": "Top performers", "who": "Who they are", "journey": "The journey so far",
           "words": "In their own words", "drivers": "What drove the numbers", "market": "Market reaction"},
    "hi": {"performers": "शीर्ष प्रदर्शन", "who": "परिचय", "journey": "अब तक का सफ़र",
           "words": "उन्हीं के शब्दों में", "drivers": "आँकड़ों के पीछे", "market": "बाज़ार की प्रतिक्रिया"},
}

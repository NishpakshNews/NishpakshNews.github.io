"""Dates and times, read by code (owner's plan, session 2, Oct 16 2026). No model in it.

Why: the reading model was asked to turn an outlet's time words ("Tuesday night", "कल", "October 15") into dates
itself, using the article's publish time. That is the model TYPING a value, and a wrong date moves a line to "unsure",
drops a "scheduled" line as past, or ranks old news as today's. Several modules also read dates on their own (frames,
relate, disputes, compose, audit), none of them in Hindi. Now:

  find(text)                every date / weekday / relative day / clock time / part of the day in an English or Hindi
                            text, with its place in the text (identifies only, never rewrites)
  resolve(words, ref, future=None, absolute_only=False)
                            the time words of one statement as {start, end, precision}, IST, "YYYY-MM-DDTHH:MM";
                            None when code cannot be sure (never guesses: "कल" with no tense, a clock time in another
                            time zone, a weekday with no reference time)
  read_time(time, text, published_at)
                            used by reading: code's reading of `when_text` replaces the model's start/end; the model's
                            value is kept only when code cannot read the words, and refused when it puts a past event
                            after the report was published. Counted in STATS.
  date_of(text)             (year, month, day), None for a part not given: the old frames.date_of contract, now also
                            Hindi and "15/10/2026"
  english(when_text)        Hindi time words in English ("26 सितंबर" -> "26 September") for an English page
  house_dates(text)         OUR article's dates in one form, "15 October" ("October 15", "Oct. 15", "15th of October"
                            -> "15 October"); the audit found both forms in 57% of mixed-language articles. Only the
                            article we write: outlets' statements are compared by value and stay as written.
  is_future(text)           the statement speaks of what will happen ("will", "is scheduled to", "करेंगे", "होगी")
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FMT = "%Y-%m-%dT%H:%M"

_EN_MONTHS = (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
              ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
              ("oct", "october"), ("nov", "november"), ("dec", "december"))
_HI_MONTHS = (("जनवरी",), ("फरवरी", "फ़रवरी"), ("मार्च",), ("अप्रैल", "अप्रेल"), ("मई",), ("जून",), ("जुलाई",),
              ("अगस्त",), ("सितंबर", "सितम्बर"), ("अक्टूबर", "अक्तूबर"), ("नवंबर", "नवम्बर"), ("दिसंबर", "दिसम्बर"))
MONTHS = {w: n for n, ws in enumerate(_EN_MONTHS, 1) for w in ws}
MONTHS.update({w: n for n, ws in enumerate(_HI_MONTHS, 1) for w in ws})
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6,
            "सोमवार": 0, "मंगलवार": 1, "बुधवार": 2, "गुरुवार": 3, "बृहस्पतिवार": 3, "वीरवार": 3, "शुक्रवार": 4,
            "शनिवार": 5, "रविवार": 6, "इतवार": 6}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# parts of the day as hour ranges (the old reading rule: "Tuesday night" -> 18:00 to 23:59)
PARTS = {"morning": (6, 11), "afternoon": (12, 16), "evening": (17, 20), "night": (18, 23),
         "सुबह": (6, 11), "दोपहर": (12, 16), "शाम": (17, 20), "रात": (18, 23)}
PART_EN = {"सुबह": "morning", "दोपहर": "afternoon", "शाम": "evening", "रात": "night"}

DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_W = r"(?<![\wऀ-ॿ])"          # a word start, Devanagari included (\b does not see Hindi letters' edges)
_E = r"(?![\wऀ-ॿ])"
_MON = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"((?:19|20)\d\d)"
_WD = "(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\.?"

# order matters: the longer forms first, and one place of the text is read once
PATTERNS = [
    ("iso", re.compile(rf"{_W}{_YEAR}-(\d{{1,2}})-(\d{{1,2}})(?:[T ](\d{{1,2}}):(\d\d))?{_E}")),
    ("dmy_num", re.compile(rf"{_W}(\d{{1,2}})[/.-](\d{{1,2}})[/.-]{_YEAR}{_E}")),
    # 17-22 October 2026 / 17 to 22 October / 17 से 22 अक्टूबर
    ("range_dm", re.compile(rf"(?i){_W}{_DAY}\s*(?:-|–|to|till|until|से)\s*{_DAY}\s+(?:of\s+)?{_MON}{_E}(?:,?\s+{_YEAR}{_E})?")),
    # October 17 to 22 / October 17-22, 2026
    ("range_md", re.compile(rf"(?i){_W}{_MON}\s+{_DAY}\s*(?:-|–|to|till|until)\s*{_DAY}{_E}(?:,?\s+{_YEAR}{_E})?")),
    ("dm", re.compile(rf"(?i){_W}{_DAY}\s+(?:of\s+)?{_MON}{_E}(?:,?\s+{_YEAR}{_E})?")),
    ("md", re.compile(rf"(?i){_W}{_MON}\s+{_DAY}{_E}(?!\s*(?:%|per\b|crore|lakh|million|billion))(?:,?\s+{_YEAR}{_E})?")),
    ("my", re.compile(rf"(?i){_W}{_MON}[,\s]+{_YEAR}{_E}")),
    ("weekday", re.compile(rf"(?i){_W}{_WD}{_E}")),
    ("relative", re.compile(r"(?i)(?<![\wऀ-ॿ])(today|tonight|yesterday|tomorrow|last night|this morning|"
                            r"this evening|this afternoon|day before yesterday|day after tomorrow|last week|"
                            r"this week|next week|last month|this month|next month|last year|this year|next year|"
                            r"आज रात|आज|कल रात|कल|परसों|बीते सप्ताह|पिछले सप्ताह|पिछले हफ्ते|अगले सप्ताह|अगले हफ्ते|"
                            r"पिछले महीने|इस महीने|अगले महीने|पिछले साल|इस साल|अगले साल)(?![\wऀ-ॿ])")),
    # 12:30 PM, 5 p.m., 17:30 hrs, 10.30 am IST, शाम 5 बजे, सुबह 10:30 बजे
    ("clock", re.compile(r"(?i)(?<![\wऀ-ॿ])(?:(सुबह|दोपहर|शाम|रात)\s+)?(\d{1,2})(?:[:.](\d\d))?\s*"
                         r"(a\.?m\.?|p\.?m\.?|hrs|hours|बजे)(?![\wऀ-ॿ])(?:\s*\(?(IST|GMT|UTC|BST|CET|"
                         r"EST|EDT|ET|PST|PDT|PT|JST|SGT|GST|local time)\)?)?")),
    ("part", re.compile(r"(?i)(?<![\wऀ-ॿ])(early hours|morning|afternoon|evening|night|सुबह|दोपहर|शाम|रात)"
                        r"(?![\wऀ-ॿ])")),
    ("year", re.compile(rf"(?i)(?:\bin\s+|\bof\s+|{_W}साल\s+|{_W}वर्ष\s+){_YEAR}{_E}")),
]


@dataclass
class Mention:
    kind: str
    start: int
    end: int
    text: str
    groups: tuple


def find(text: str | None) -> list[Mention]:
    """Every time expression of the text, in order; a place of the text belongs to one expression."""
    t = (text or "").translate(DIGITS)
    taken: list[tuple[int, int]] = []
    out = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(t):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            if kind == "clock" and m.group(4).lower() in ("hrs", "hours") and not m.group(3) and len(m.group(2)) < 3:
                continue          # "24 hours" is a span, not a time; "17:30 hrs" is a time
            mon = {"dm": 2, "md": 1, "range_dm": 3, "range_md": 1, "my": 1}.get(kind)
            if mon and m.group(mon)[:1].isascii() and m.group(mon)[:1].islower():
                continue          # an English month is written with a capital: "may 20", "march 5 km" are words
            if kind == "weekday" and len(m.group(1)) <= 4 and m.group(1)[:1].islower():
                continue          # "sun", "wed", "sat" in lower case are words
            taken.append((m.start(), m.end()))
            out.append(Mention(kind, m.start(), m.end(), m.group(0), m.groups()))
    return sorted(out, key=lambda x: x.start)


FUTURE = re.compile(r"(?i)\b(?:will|shall|would be|is (?:scheduled|set|slated|due|expected|likely) to|are (?:scheduled|"
                    r"set|slated|due|expected|likely) to|to be (?:held|announced|launched)|upcoming|next)\b|"
                    r"(?:ेंगे|ेगा|ेगी|ेंगी|ूंगा|ूँगा|ोगे|ाएगा|ाएगी|ाएंगे|ायेगा|होगा|होगी|होंगे)(?![ऀ-ॿ])")


def is_future(text: str | None) -> bool:
    return bool(FUTURE.search(text or ""))


def _ref(ref) -> dt.datetime:
    """The reference time in IST (a naive time is read as UTC, the database clock)."""
    if ref is None:
        ref = dt.datetime.now(dt.timezone.utc)
    if isinstance(ref, str):
        ref = dt.datetime.fromisoformat(ref)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=dt.timezone.utc)
    return ref.astimezone(IST)


def _date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _nearest_year(m: int, d: int, ref: dt.date, future: bool | None) -> dt.date | None:
    """A day and month with no year: the year that puts it nearest the report (a report in January about
    "28 December" means last year); a past event is never after the report, a future one never before it."""
    options = [x for x in (_date(ref.year + k, m, d) for k in (-1, 0, 1)) if x]
    if future is False:
        options = [x for x in options if x <= ref + dt.timedelta(days=1)] or options
    elif future is True:
        options = [x for x in options if x >= ref - dt.timedelta(days=1)] or options
    return min(options, key=lambda x: abs((x - ref).days)) if options else None


def _month_end(y: int, m: int) -> dt.date:
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))


def _span(mention: Mention, ref: dt.datetime, future: bool | None) -> tuple[dt.date, dt.date, str] | None:
    """A date mention as (first day, last day, precision), or None when it cannot be placed for sure."""
    g, today = mention.groups, ref.date()
    k = mention.kind
    if k == "iso":
        d = _date(int(g[0]), int(g[1]), int(g[2]))
        return (d, d, "day") if d else None
    if k == "dmy_num":
        d = _date(int(g[2]), int(g[1]), int(g[0]))          # Indian order: day / month / year
        return (d, d, "day") if d else None
    if k in ("dm", "md"):
        day, mon = (g[0], g[1]) if k == "dm" else (g[1], g[0])
        m, dd = MONTHS[mon.lower().rstrip(".")], int(day)
        d = _date(int(g[2]), m, dd) if g[2] else _nearest_year(m, dd, today, future)
        return (d, d, "day") if d else None
    if k in ("range_dm", "range_md"):
        a, b, mon = (g[0], g[1], g[2]) if k == "range_dm" else (g[1], g[2], g[0])
        m = MONTHS[mon.lower().rstrip(".")]
        if g[3]:
            d1, d2 = _date(int(g[3]), m, int(a)), _date(int(g[3]), m, int(b))
        else:
            d1 = _nearest_year(m, int(a), today, future)
            d2 = _date(d1.year, m, int(b)) if d1 else None
        return (d1, d2, "day") if d1 and d2 and d1 <= d2 else None
    if k == "my":
        m, y = MONTHS[g[0].lower().rstrip(".")], int(g[1])
        return dt.date(y, m, 1), _month_end(y, m), "month"
    if k == "year":
        y = int(g[0])
        return dt.date(y, 1, 1), dt.date(y, 12, 31), "year"
    if k == "weekday":
        wd = WEEKDAYS[g[0].lower().rstrip(".")]
        back = (today.weekday() - wd) % 7
        d = today + dt.timedelta(days=(7 - back) % 7) if future else today - dt.timedelta(days=back)
        return d, d, "day"
    if k == "relative":
        w = g[0].lower()
        one = {"today": 0, "tonight": 0, "this morning": 0, "this evening": 0, "this afternoon": 0, "आज": 0,
               "आज रात": 0, "yesterday": -1, "last night": -1, "tomorrow": 1, "day before yesterday": -2,
               "day after tomorrow": 2}
        if w in one:
            d = today + dt.timedelta(days=one[w])
            return d, d, "day"
        if w in ("कल", "कल रात", "परसों"):
            if future is None:
                return None                                   # yesterday or tomorrow: the tense decides, never a guess
            n = (2 if w == "परसों" else 1) * (1 if future else -1)
            d = today + dt.timedelta(days=n)
            return d, d, "day"
        step = -1 if w.startswith(("last", "पिछले", "बीते")) else 1 if w.startswith(("next", "अगले")) else 0
        if "week" in w or "सप्ताह" in w or "हफ्ते" in w:
            monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=step)
            return monday, monday + dt.timedelta(days=6), "week"
        if "month" in w or "महीने" in w:
            y, m = today.year, today.month + step
            y, m = y + (m > 12) - (m < 1), (m - 1) % 12 + 1
            return dt.date(y, m, 1), _month_end(y, m), "month"
        if "year" in w or "साल" in w:
            y = today.year + step
            return dt.date(y, 1, 1), dt.date(y, 12, 31), "year"
    return None


def _clock(m: Mention) -> tuple[int, int, bool] | None:
    """(hour, minute, minute given) in IST, or None (another time zone, "local time", or not a real time)."""
    part, h, mi, unit, zone = m.groups
    if zone and zone.upper() != "IST":
        return None                                           # never converted: "local time" abroad is not IST
    h, mi = int(h), int(mi or 0)
    u = unit.lower().replace(".", "")
    if u == "pm" and h < 12:
        h += 12
    elif u == "am" and h == 12:
        h = 0
    elif u == "बजे" and part in ("दोपहर", "शाम", "रात") and h < 12 and not (part == "रात" and h < 4):
        h += 12
    elif u == "बजे" and not part:
        return None                                           # "5 बजे" alone: morning or evening is not said
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h, mi, bool(m.groups[2])


def resolve(words: str | None, ref=None, future: bool | None = None, absolute_only: bool = False) -> dict | None:
    """One statement's time words as {start, end, precision} in IST, or None. `ref` is when the report was
    published (the day "Tuesday", "yesterday" and a date with no year are counted from); `future` is the tense of
    the statement (None = unknown: "कल" is then not read). `absolute_only`: only dates written in full or with a
    month (for a reference that is not the report's own time)."""
    found = find(words)
    if not found:
        return None
    r = _ref(ref)
    if future is None and is_future(words):
        future = True
    dates = [m for m in found if m.kind not in ("clock", "part")]
    if absolute_only:
        dates = [m for m in dates if m.kind not in ("weekday", "relative", "year")]
    spans = [s for s in (_span(m, r, future) for m in dates) if s]
    if dates and len(spans) < len(dates):
        return None                                           # a date code could not place: not half a reading
    # two different days ("Monday, October 15" when the 15th is a Thursday, or two dates): not read. A weekday next to
    # its own date is the date ("Thursday, 15 October").
    days = {(a, b) for a, b, p in spans if p == "day"}
    if len(days) > 1:
        named = [s for s, m in zip(spans, dates) if m.kind != "weekday" and s[2] == "day"]
        weekdays = [m for m in dates if m.kind == "weekday"]
        if len(named) == 1 and len(days) == 2 and all(
                WEEKDAYS[w.groups[0].lower().rstrip(".")] == named[0][0].weekday() for w in weekdays):
            spans = named
        else:
            return None
    if not spans:
        return None       # a clock time or a part of the day alone: "at 5 pm" in a report of 9 am may be yesterday's
    # the narrowest span wins: "on Tuesday, last week" is the Tuesday
    first, last, prec = min(spans, key=lambda s: (s[1] - s[0]).days)
    if absolute_only and prec not in ("day", "month"):
        return None
    if prec != "day" or first != last:
        return {"start": dt.datetime.combine(first, dt.time(0, 0)).strftime(FMT),
                "end": dt.datetime.combine(last, dt.time(23, 59)).strftime(FMT), "precision": prec}
    clocks = [c for c in (_clock(m) for m in found if m.kind == "clock") if c]
    bad_clock = any(m.kind == "clock" for m in found) and not clocks
    parts = [m for m in found if m.kind == "part"]
    word = next((m.groups[0].lower() for m in dates if m.kind == "relative"), "")
    if clocks and not bad_clock:
        h, mi, exact = clocks[0]
        t = dt.datetime.combine(first, dt.time(h, mi)).strftime(FMT)
        return {"start": t, "end": t, "precision": "exact" if exact else "hour"}
    part = parts[0].groups[0].lower() if parts else ("night" if word in ("tonight", "last night", "आज रात", "कल रात")
                                                     else "morning" if word == "this morning"
                                                     else "evening" if word == "this evening"
                                                     else "afternoon" if word == "this afternoon" else "")
    if part in PARTS and not bad_clock:
        h1, h2 = PARTS[part]
        return {"start": dt.datetime.combine(first, dt.time(h1, 0)).strftime(FMT),
                "end": dt.datetime.combine(first, dt.time(h2, 59)).strftime(FMT), "precision": "part_of_day"}
    return {"start": dt.datetime.combine(first, dt.time(0, 0)).strftime(FMT),
            "end": dt.datetime.combine(first, dt.time(23, 59)).strftime(FMT), "precision": "day"}


STATS: dict[str, int] = {}


def _count(k: str) -> None:
    STATS[k] = STATS.get(k, 0) + 1


def read_time(time: dict | None, text: str | None, published_at) -> dict | None:
    """Reading's time for one statement: code's reading of its time words first. Keys kept: when_text, start, end,
    precision; `by` says who placed it ("code" / "model"). Counted in STATS: code (agrees / differs with the
    model), model (code could not read the words), refused (the model put a past event after publication), none."""
    if not time:
        return time
    out = dict(time)
    fut = is_future(text) or is_future(out.get("when_text"))
    code = resolve(out.get("when_text"), published_at, future=fut or (False if (text or out.get("when_text")) else None))
    if code:
        same = (out.get("start") or "")[:10] == code["start"][:10]
        _count("code_agrees" if same or not out.get("start") else "code_differs")
        out.update(code, by="code")
        return out
    if out.get("start"):
        pub = _ref(published_at).replace(tzinfo=None)
        try:
            s = dt.datetime.fromisoformat(out["start"])
        except (TypeError, ValueError):
            s = None
        if s and not fut and s > pub + dt.timedelta(hours=1):
            _count("model_refused")
            out.update(start=None, end=None, precision="unknown", by=None)
            return out
        _count("model_only")
        out["by"] = "model"
        return out
    _count("none")
    return out


def date_of(text: str | None) -> tuple | None:
    """(year, month, day), None for a part not given, for the first date written with a month (or ISO / numeric):
    "1986-12-06", "6 December 1986", "December 6, 1986", "31st October", "July 2026", "15 अक्टूबर", "15/10/2026".
    The contract of the old frames.date_of; relative words and weekdays are not dates here."""
    for m in find(text):
        g = m.groups
        if m.kind == "iso":
            return int(g[0]), int(g[1]), int(g[2])
        if m.kind == "dmy_num":
            return int(g[2]), int(g[1]), int(g[0])
        if m.kind in ("dm", "md"):
            day, mon = (g[0], g[1]) if m.kind == "dm" else (g[1], g[0])
            d = int(day)
            return (int(g[2]) if g[2] else None), MONTHS[mon.lower().rstrip(".")], (d if 1 <= d <= 31 else None)
        if m.kind in ("range_dm", "range_md"):
            day, mon = (g[0], g[2]) if m.kind == "range_dm" else (g[1], g[0])
            return (int(g[3]) if g[3] else None), MONTHS[mon.lower().rstrip(".")], int(day)
        if m.kind == "my":
            return int(g[1]), MONTHS[g[0].lower().rstrip(".")], None
    return None


def date_values(text: str | None) -> list[tuple]:
    """Every date written with a month in the text, as (year, month, day) with None for a part not given: the
    values a translation must keep ("15 October" and "15 अक्टूबर" are one value)."""
    out = []
    for m in find(text):
        if m.kind in ("iso", "dmy_num", "dm", "md", "range_dm", "range_md", "my"):
            out.append(date_of(m.text))
            if m.kind in ("range_dm", "range_md"):
                g = m.groups
                b, mon = (g[1], g[2]) if m.kind == "range_dm" else (g[2], g[0])
                out.append(((int(g[3]) if g[3] else None), MONTHS[mon.lower().rstrip(".")], int(b)))
    return out


_HI_WORD = {**{w: MONTH_NAMES[n] for n, ws in enumerate(_HI_MONTHS, 1) for w in ws},
            **{w: DAY_NAMES[n] for w, n in WEEKDAYS.items() if re.search(r"[ऀ-ॿ]", w)},
            **PART_EN, "आज": "today", "बजे": "o'clock"}


def english(when_text: str | None) -> str:
    """Hindi time words in English for an English page ("26 सितंबर" -> "26 September", "मंगलवार रात" -> "Tuesday
    night"); "" when any Hindi word is left (those are not guessed: "कल" is yesterday or tomorrow)."""
    w = (when_text or "").translate(DIGITS)
    if not re.search(r"[ऀ-ॿ]", w):
        return w.strip()
    for hi, en in sorted(_HI_WORD.items(), key=lambda x: -len(x[0])):
        w = re.sub(rf"(?<![ऀ-ॿ]){hi}(?![ऀ-ॿ])", en, w)
    w = re.sub(r"\s+", " ", w).strip(" ,")
    return "" if re.search(r"[ऀ-ॿ]", w) else w


def _in_quote(text: str, i: int) -> bool:
    before = text[:i]
    return before.count("“") > before.count("”") or before.count('"') % 2 == 1


def house_dates(text: str | None) -> str:
    """Our article's dates in one form, day first: "October 15" / "Oct. 15" / "October 15th, 2026" / "15th of
    October" -> "15 October" / "15 October 2026". Never inside a quotation; ranges and weekdays kept ("Thursday,
    15 October"); English text only (a Hindi page has its own form)."""
    t = text or ""
    if not t or re.search(r"[ऀ-ॿ]", t):
        return t
    out, last = [], 0
    for m in find(t):
        if m.kind not in ("dm", "md", "range_md") or _in_quote(t, m.start):
            continue
        g = m.groups
        if not re.fullmatch(r"[A-Za-z]+\.?", g[1] if m.kind == "dm" else g[0]):
            continue
        if m.kind == "dm":
            day, mon, year = g[0], g[1], g[2]
            new = f"{int(day)} {MONTH_NAMES[MONTHS[mon.lower().rstrip('.')]]}" + (f" {year}" if year else "")
        elif m.kind == "md":
            mon, day, year = g[0], g[1], g[2]
            new = f"{int(day)} {MONTH_NAMES[MONTHS[mon.lower().rstrip('.')]]}" + (f" {year}" if year else "")
        else:
            mon, a, b, year = g
            new = f"{int(a)} to {int(b)} {MONTH_NAMES[MONTHS[mon.lower().rstrip('.')]]}" + (f" {year}" if year else "")
            if "–" in m.text or "-" in m.text:
                new = f"{int(a)}-{int(b)} {MONTH_NAMES[MONTHS[mon.lower().rstrip('.')]]}" + (f" {year}" if year else "")
        if new == m.text:
            continue
        out.append(t[last:m.start])
        out.append(new)
        last = m.end
    out.append(t[last:])
    return "".join(out)


def forms(text: str | None) -> set[str]:
    """Which date forms an English text uses: "day_first" ("15 October"), "month_first" ("October 15")."""
    s = set()
    for m in find(text):
        if m.kind in ("dm", "range_dm") and re.fullmatch(r"[A-Za-z]+\.?", m.groups[1] if m.kind == "dm" else m.groups[2]):
            s.add("day_first")
        elif m.kind in ("md", "range_md"):
            s.add("month_first")
    return s

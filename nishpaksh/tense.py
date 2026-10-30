"""Tense from the statements' day (owner, Oct 30 2026: a lead and two background lines about Oct 6 and Oct 28 were
printed in the present tense two days and three weeks later; the writer is told NOW, `clock.py`, but a small model
does not always follow it, and a rule left to the prompt is not a rule).

A sentence whose statements ALL belong to a day before today (IST) cannot be in the present: its progressive and
passive auxiliaries ("is taking place", "are underway", "is scheduled") become past ("was"/"were") and "will"
becomes "would". Nothing else is touched: no verb is re-inflected, quoted words stay as written, a sentence the
parser cannot read fully (part of speech missing) is left alone, and a sentence with a statement of today, an
undated statement or no known day is not changed ("code never guesses").
The day of a statement: the END of its own time (a span reaching today is today), else the day its earliest report
was published. No model in it, no word list: the auxiliaries come from the parse.
"""
from __future__ import annotations

import datetime as dt
import re

from . import clock, nlp

_QUOTED = re.compile(r"[\"“][^\"”]*[\"”]")


def item_day(item: dict) -> dt.date | None:
    """The last day this statement can belong to, or None when nothing dates it."""
    t = item.get("time") or {}
    for key in ("end", "start"):
        s = t.get(key)
        if s:
            try:
                return dt.datetime.fromisoformat(str(s)).date()
            except ValueError:
                pass
    days = []
    for s in item.get("sources") or []:
        p = s.get("published_at")
        if p:
            try:
                days.append(dt.datetime.fromisoformat(str(p)).date())
            except ValueError:
                pass
    return min(days) if days else None


def is_past(ids: list, by_id: dict, today: dt.date) -> bool:
    days = [item_day(by_id[i]) for i in ids if i in by_id]
    return bool(days) and all(d is not None and d < today for d in days)


def to_past(text: str) -> str | None:
    """The sentence with its present auxiliaries in the past, or None when there is nothing to change (or it cannot
    be read well enough to change safely)."""
    toks = nlp.parse(text)
    if not toks or any(not t.tag for t in toks):
        return None
    quoted = [(m.start(), m.end()) for m in _QUOTED.finditer(text)]
    edits = []
    for t in toks:
        if any(a <= t.start < b for a, b in quoted):
            continue
        if t.dep in {"aux", "auxpass"} and t.tag in {"VBZ", "VBP"} and t.lemma == "be":
            new = "were" if t.text.lower() == "are" else "was"
        elif t.dep == "aux" and t.tag == "MD" and t.text.lower() == "will":
            new = "would"
        else:
            continue
        edits.append((t.start, t.end, new[:1].upper() + new[1:] if t.text[:1].isupper() else new))
    if not edits:
        return None
    for a, b, new in reversed(edits):
        text = text[:a] + new + text[b:]
    return text


def fix_article(paragraphs: list[list[dict]], by_id: dict, now: dt.datetime | None = None) -> int:
    """Put the sentences of earlier days into the past. Returns how many sentences changed (counted in the
    article's `narrative.tense_fixed`)."""
    today = clock.ist_now(now).date()
    n = 0
    for para in paragraphs:
        for sent in para:
            ids = [int(i) for i in sent.get("ids") or [] if str(i).lstrip("-").isdigit()]
            if not is_past(ids, by_id, today):
                continue
            pieces = sent.get("parts") or [sent]
            changed = False
            for piece in pieces:
                new = to_past(piece["text"])
                if new and new != piece["text"]:
                    piece["text"] = new
                    changed = True
            if changed:
                if sent.get("parts"):
                    sent["text"] = " ".join(p["text"].strip() for p in sent["parts"])
                n += 1
    return n


_DAYWORD = re.compile(r"(?i)\b(?:today|yesterday|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|"
                      r"sunday|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|"
                      r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2})\b")


def name_lead_day(paragraphs: list[list[dict]], keys: list[str], by_id: dict, now: dt.datetime | None = None) -> bool:
    """The lead of an article about an earlier day says which day ("On 28 October, ..."): a reader meeting it on the
    30th takes an undated sentence for today's news. Only when every statement of the lead is dated (its own day, else
    the day it was first reported) before today, the lead has no day word, and the parse shows how to join the day to
    the sentence (a lead that opens with a name keeps its capital)."""
    if not paragraphs or not keys or keys[0] != "news" or not paragraphs[0]:
        return False
    today = clock.ist_now(now).date()
    lead = paragraphs[0][0]
    ids = [int(i) for i in lead.get("ids") or [] if str(i).lstrip("-").isdigit()]
    if not is_past(ids, by_id, today) or _DAYWORD.search(lead.get("text") or ""):
        return False
    day = max(item_day(by_id[i]) for i in ids)
    pieces = lead.get("parts") or [lead]
    text = pieces[0]["text"]
    toks = nlp.parse(text)
    if not toks or not toks[0].tag:
        return False
    first = toks[0]
    word = text[first.start:first.end]
    lower = first.pos not in {"PROPN"} and first.tag not in {"NNP", "NNPS"} and not word.isupper()
    if first.pos in {"ADV", "SCONJ", "ADP", "CCONJ"} or first.tag in {"RB", "IN", "CC"}:
        return False      # "Later ...", "After ...": the sentence has a time word of its own
    rest = text[:1].lower() + text[1:] if lower else text
    pieces[0]["text"] = f"On {day.day} {day.strftime('%B')}, {rest}"
    if lead.get("parts"):
        lead["text"] = " ".join(p["text"].strip() for p in lead["parts"])
    return True

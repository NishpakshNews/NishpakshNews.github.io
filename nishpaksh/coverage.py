"""How much of a report reached us (the express desk, owner Oct 16 2026: "maximize the coverage").

An express story has ONE report, so the page is only as full as what was read from it. Coverage is measured on the
report itself, by code:

  fact_sentences(text)   the report's sentences that can hold a fact: page clutter ("Also read", "Download the app",
                         "Stay updated ..."), captions, headings, questions and fragments under MIN_WORDS words left
                         out (they are not misses)
  covered(items, text)   which of them some statement came from: the statement's `quote` (the sentence's first words
                         as the reading copied them, fidelity.quoted_window), else its anchors (numbers, names, dates;
                         fidelity.source_window)
  report(items, text)    (covered, total, the sentences no statement came from)

TARGET (0.7): the reading aims at it; a first reading under it gets ONE more call on the sentences left
(extract.second_pass). MINIMUM (0.6): the desk's pass mark, counted on the article (`extraction["coverage"]`) and
in the run's stats; under it the story is still published (publication is never blocked) and counted.
"""
from __future__ import annotations

import re

TARGET = 0.7
MINIMUM = 0.6
MIN_WORDS = 6

CLUTTER = re.compile(
    r"(?i)^\W*(?:also read|read also|read more|watch|watch video|download (?:the )?\w*\s*app|stay updated|get the latest|"
    r"follow us|subscribe|click here|advertisement|sponsored|recommended|trending|top stories|photo:|image:|"
    r"(?:photo|image|video)\s*(?:credit|courtesy)|first published|updated:|published:|"
    r"यह भी पढ़ें|ये भी पढ़ें|इसे भी पढ़ें|पढ़ें:|वीडियो देखें|डाउनलोड करें)"
    r"|\b(?:download the \w+ app|sports news and live updates|check the \w+ medal tally|follow .{0,30} on (?:x|twitter|"
    r"instagram|facebook|whatsapp|google news))\b")


def fact_sentences(text: str) -> list[str]:
    from .fidelity import sentences
    out = []
    for s in sentences(text or ""):
        t = s.strip()
        if len(re.findall(r"[\wऀ-ॿ]+", t)) < MIN_WORDS or CLUTTER.search(t) or t.endswith("?"):
            continue
        out.append(t)
    return out


def _items(ex_or_items) -> list[dict]:
    if isinstance(ex_or_items, dict):
        return [it for k in ("events", "claims", "context") for it in ex_or_items.get(k) or []]
    return list(ex_or_items)


def report(ex_or_items, text: str, lang: str = "en", registry=None) -> tuple[int, int, list[str]]:
    """(sentences some statement came from, fact sentences, the ones none came from)."""
    from .fidelity import quoted_window, source_window
    facts = fact_sentences(text)
    if not facts:
        return 0, 0, []
    hit: set[int] = set()
    for it in _items(ex_or_items):
        win = quoted_window(it.get("quote"), text) or source_window(it.get("text") or "", text, lang, registry)
        if not win:
            continue
        for k, s in enumerate(facts):
            if s in win or win in s:
                hit.add(k)
    left = [s for k, s in enumerate(facts) if k not in hit]
    return len(hit), len(facts), left


def share(ex_or_items, text: str, lang: str = "en", registry=None) -> float | None:
    n, total, _ = report(ex_or_items, text, lang, registry)
    return round(n / total, 2) if total else None

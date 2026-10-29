"""Sentence fusion by alignment: two lines that tell one event, each with a detail the other lacks, become ONE sentence by code.

The task is a known one: sentence fusion (Barzilay & McKeown 2005), multi-sentence compression by word graph (Filippova 2010,
the `takahe` package). A small model asked to "merge these two sentences" invents or drops facts and has to be checked anyway
(and asked twice); this reads both lines, so it can only reuse words an outlet wrote, and the check is the same code check as
for any merge (`tidy.verify_merge`).

First tried here: the plain word graph (every walk through the lines' shared words). On the day's real pairs it found
sentences, but spliced mid verb-phrase ("may revise the annual fee rates will be effective from 1 April", a bracket cut in
two). The lesson of the literature holds: free splicing is the unsafe part. So the fusion is an EDIT of a BASE line:

  1. align the two lines word by word (longest common subsequence); what is left is, per place, a run only the base has
     (kept: the base is the sentence), a run only the other has (an INSERT) or a run each has (a REPLACE);
  2. an INSERT is taken into the base only where it is ATTACHABLE: it opens with a preposition or subordinator (a closed class
     of English: "to participate in the meeting", "with an outlay of ...", "for Master Posts"), a comma run, or an "also"; and
     it goes where it stood in its own line, behind the same anchor word, so it hangs on the same head it hung on in the
     outlet's sentence. A verb phrase is never grafted onto another verb phrase;
  3. a REPLACE takes the other line's run when it is the better reading of the same thing: the more precisely written figure
     (48.54 lakh over 48 lakh), the fuller name (New Delhi over Delhi), a noun over a pronoun (Kalia over He); otherwise the
     base's run stays;
  4. both lines in turn are the base; a result stands only if it passes `tidy.verify_merge` (every figure, name, date, clock
     time and quotation of both lines in it, nothing new, one sentence, same negation) and keeps the content words of both
     (`KEEP_CONTENT`); of the two the one that keeps most with fewest insertions wins.

No model, no list of cases (the prepositions are the grammar's own closed class). A merge no edit can make stays two lines.
"""
from __future__ import annotations

import difflib
import re

from . import figures
from .relate import Profile

KEEP_CONTENT = 0.92    # share of the two lines' content words a fusion must keep
PREPOSITIONS = frozenset("""in on at by for from with without to of under over after before during between among across near
about against into through within including like as since until per amid despite upon onto off out via toward towards beyond
behind below above along alongside around besides except following regarding concerning""".split())
AUXILIARIES = frozenset("""is are was were be been being am has have had do does did can could may might will would shall should must""".split())
PRONOUNS = frozenset("he she they it his her their its him them this that these those".split())
_TOKEN = re.compile(r"[₹$€£]?\d[\d,]*(?:\.\d+)?%?|[^\W\d_][\w'’\-]*|[,;:()\[\]“”\"‘’.!?]")
_QUOTE = re.compile(r"[“\"][^”\"]{12,}[”\"]")
_NO_SPACE_BEFORE = {",", ";", ":", ")", "]", ".", "!", "?"}
_NO_SPACE_AFTER = {"(", "["}


def _tokens(text: str, quotes: list[str]) -> list[str]:
    def hold(m):
        quotes.append(m.group(0))
        return f" QQ{len(quotes) - 1}QQ "
    toks = _TOKEN.findall(_QUOTE.sub(hold, text.strip()))
    while toks and toks[-1] in ".!?":
        toks.pop()
    return toks


def _join(toks: list[str], quotes: list[str]) -> str:
    out = ""
    for i, t in enumerate(toks):
        m = re.fullmatch(r"QQ(\d+)QQ", t)
        if m:
            t = quotes[int(m.group(1))]
        if i and t not in _NO_SPACE_BEFORE and toks[i - 1] not in _NO_SPACE_AFTER:
            out += " "
        out += t
    out += "."
    return out[0].upper() + out[1:]


def attachable(run: list[str]) -> bool:
    """May this run of the other line be grafted into the base? A prepositional phrase, a comma run or an adverb "also"."""
    words = [t for t in run if t not in (",", ";")]
    if not words or any(w.lower() in AUXILIARIES for w in words):      # a verb phrase is never grafted onto another
        return False
    first = words[0].lower()
    if run[0] == "," and len(words) > 1:
        first = words[0].lower()
    return first in PREPOSITIONS or first == "also" or run[0] in "([" or (run[0] == "," and (first in PREPOSITIONS or first.endswith("ing")))


def _precise(tokens: list[str]) -> float | None:
    """Precision of the figures in a run (smaller unit = more precise); None when there is no figure."""
    fs = [figures.unit(f) for f in figures.find(" ".join(tokens)) if f.kind == "digits"]
    return min(fs) if fs else None


def _better(x: list[str], y: list[str]) -> list[str]:
    """Of two runs standing for one thing, the better reading: y when it is the more precise figure, the fuller name or
    a noun over a pronoun; else x."""
    px, py = _precise(x), _precise(y)
    if px is not None and py is not None:
        return y if py < px else x
    if len(x) == 1 and x[0].lower() in PRONOUNS and not (len(y) == 1 and y[0].lower() in PRONOUNS):
        return y
    lx, ly = " ".join(x).lower(), " ".join(y).lower()
    if lx != ly and lx in ly and all(t[0].isupper() for t in y if t.isalpha()):
        return y                                    # Delhi -> New Delhi
    return x


def _edit(base: list[str], other: list[str]) -> tuple[list[str], int, list[str]]:
    """The base with the other line's attachable inserts and better replacements. (tokens, insertions, dropped runs)."""
    kb, ko = [t.lower() for t in base], [t.lower() for t in other]
    sm = difflib.SequenceMatcher(None, kb, ko, autojunk=False)
    out, inserts, dropped = [], 0, []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or op == "delete":
            out += base[i1:i2]
        elif op == "insert":
            run = other[j1:j2]
            if attachable(run):
                out += run
                inserts += 1
            else:
                dropped.append(" ".join(run))
        else:   # replace
            x, y = base[i1:i2], other[j1:j2]
            pick = _better(x, y)
            out += pick
            if pick is x and [t.lower() for t in x] != [t.lower() for t in y]:
                dropped.append(" ".join(y))
    return out, inserts, dropped


def fuse(a: str, b: str) -> dict | None:
    """The best verified fusion of two lines, or None. {"text", "base", "inserts", "dropped"}."""
    from . import tidy
    pa, pb = Profile(a), Profile(b)
    need = set(pa.roots) | set(pb.roots)
    quotes: list[str] = []
    ta, tb = _tokens(a, quotes), _tokens(b, quotes)
    found = []
    for name, base, other in (("a", ta, tb), ("b", tb, ta)):
        toks, inserts, dropped = _edit(base, other)
        text = _join(toks, quotes)
        pm = Profile(text)
        kept = len(need & set(pm.roots)) / max(1, len(need))
        if kept < KEEP_CONTENT:
            continue
        ok, why = tidy.verify_merge(a, b, text)
        if ok:
            found.append({"text": text, "base": name, "inserts": inserts, "dropped": dropped, "kept": round(kept, 2)})
    if not found:
        return None
    return max(found, key=lambda f: (f["kept"], -f["inserts"], f["base"] == "a"))

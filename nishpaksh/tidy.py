"""Paragraph tidy (B9, step 2): lines of one FINISHED paragraph that say the same thing are found and folded.

Why here. A repeat is only visible in the finished text: the statements behind two lines were different facts to the
matcher ("The deadline is 25 November" / "The window closes on 25 November" / "It runs 27 October to 25 November"), so
nothing upstream could fold them, but a reader sees one fact three times. `narrative._drop_repeats` already folds what
`relate` calls the same or covered; this module takes over from there, with the algorithms of near-duplicate detection:

  1. weighted overlap: every line is a bag of root words and figures weighted by inverse document frequency over the
     article's own lines (`idf.Weights`: a word every line has says nothing); two measures per pair: the weighted COSINE
     (are they about one thing) and the weighted CONTAINMENT of each line in the other (does one say all the other says;
     the asymmetric overlap coefficient used for near-duplicate and plagiarism detection);
  2. gates by CODE on the facts that must never be merged: figures (`figures.agree`), dates, clock times, negation,
     ordinals ("6th" / "5th" pay commission), names (`relate.name_sets_fit`), and two quotations (never merged);
  3. a reader (NLI, only on the runner, `nli_fn`) may only turn an "overlap" into "covered" when the gates already say the
     shorter line adds nothing: it never overrules a gate;
  4. a merge of two lines that each add something is a REWRITE (`rewrite`, one small model question), and code verifies
     the sentence it returns (`verify_merge`): every figure, name, date and quotation of both lines is in it, nothing new
     is. A failed check leaves the paragraph as it was.

Two things a fold must prove (owner, Oct 30 2026, from the first day of shadow samples: a Hindi sentence was folded into an
English one that held only its speaker's name). The cause was not "different languages": it was that SIMILARITY IS NOT
SUBSUMPTION. A line may go only when what is kept says everything it says, and that has two parts:
  5. COMPLETE READING: the overlap measures see only what the tokenizer reads. A line whose letters are partly in a script the
     bag cannot read (`unread_share`) has an invisible part, so "all of it is in the other line" is a claim about the visible
     remainder only: the pair is not judged (`distinct`), never folded;
  6. THE READER IS A NECESSARY CONDITION, not a booster: a fold or merge is applied only when the local entailment reader
     (multilingual NLI) reads "the kept line says the dropped one" (`verify=True`). No reader, or a reader that could not
     read the pair, is "unverified": the paragraph stays as it was. Code proves what it can read (figures, names, dates), the
     reader judges what it cannot, and either one unsure keeps both lines.

Four outcomes: `same` / `covered` (one line goes, its ids and sources join the other, the sentence takes the WEAKEST
colour of the two: it can only get more cautious), `overlap` (each adds a detail: a merge candidate), `conflict` (the
same question answered differently: both stay, the pair is reported), `distinct` (nothing).

SHADOW first (the build charter's adoption rule): `tools/tidy_shadow.py` runs this beside the current code on stored
articles; nothing calls `tidy` from the pipeline until it beats the current code at 99% precision. Untuned numbers are
below; they are read once in the audit (E8).
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass

from . import figures, idf, reconcile
from .relate import Profile, core_names, name_sets_fit, nums_within, numbers_near, relate as relate_pair

COVER = 0.95       # share of the shorter line's weight the longer line holds, to call it covered (a fact never goes for a word)
OVERLAP = 0.45     # weighted cosine from which two lines are one subject
HELD = 0.75        # ... or the share of the shorter line the longer holds (a short line inside a long one)
QUESTION = 0.55    # weighted cosine from which two lines asked the same question (a conflict needs it)
NEAR = 0.02        # figures this close are one figure written at two precisions, not a conflict (48 / 48.54)
REWRITE_MIN = 0.55  # a merge is only asked of the writer from this cosine (below it the pair is reported, not offered)
NEW_ROOTS = 2      # a merged sentence may use at most this many words neither original had (a joining word)
# words that change HOW MUCH a sentence claims (restrictors, quantifiers, modals, conditions): a closed class of English
_STRENGTH = frozenset("""only solely merely just alone all every each any some most few both either neither none except unless if
may might could can would should must""".split())
_LEANS = re.compile(r"(?i)^\s*(?:he|she|they|it|his|her|their|its|this|that|these|those|the latter|both)\b")
UNREAD_MAX = 0.05  # a line may have at most this share of its letters in a script the bag cannot read (else coverage cannot be certified)
GUARDED = {"disputed", "false"}            # a line in one of these colours is never folded into another

_QUOTE = re.compile(r"[“\"]([^”\"]{12,})[”\"]")
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_ORDINAL = re.compile(rf"(?i)\b(\d{{1,3}})(?:st|nd|rd|th)\b(?!\s+(?:of\s+)?{_MONTH})")
_SENT_BREAK = re.compile(r"[.!?][\"”')\]]?\s+[A-Zऀ-ॿ]")
_WEEKDAY_DATE = re.compile(r"(?i)\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+(\d{1,2})(?:st|nd|rd|th)?\s+"
                           r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})")
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass
class Verdict:
    a: int
    b: int
    outcome: str            # same | covered | overlap | conflict | distinct
    drop: int | None        # the line that goes (same / covered)
    keep: int | None        # the line that stays and takes its ids
    cos: float
    cont_a: float           # share of line a's weight that line b holds
    cont_b: float
    why: str = ""
    notes: tuple = ()       # ((figure the kept line has, the other reading), ...): put in brackets if the owner wants them
    conflict_kind: str = ""

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "outcome": self.outcome, "drop": self.drop, "keep": self.keep,
                "cos": round(self.cos, 2), "cont_a": round(self.cont_a, 2), "cont_b": round(self.cont_b, 2), "why": self.why,
                "notes": [list(n) for n in self.notes], "conflict_kind": self.conflict_kind}


# --- parts of a line -----------------------------------------------------------------------------------------------
def quotes(text: str) -> list[str]:
    return [relate_norm(q) for q in _QUOTE.findall(text or "")]


def relate_norm(s: str) -> str:
    from .relate import normalise
    return normalise(s)


def bag(p: Profile) -> frozenset:
    """What a line says: its root words and its figures (a figure is a word with a value)."""
    return frozenset(p.roots) | frozenset(f"#{n}" for n in p.nums)


def claim_strength(text: str) -> frozenset:
    """The restrictors, quantifiers and modals of a line ("only", "all", "may", "unless"). Two lines that differ here claim
    different amounts, so one cannot stand for both; a merged sentence must carry exactly the set both lines carry."""
    return frozenset(w for w in re.findall(r"[a-z']+", (text or "").lower()) if w in _STRENGTH)


def ordinals(text: str) -> frozenset:
    return frozenset(_ORDINAL.findall(text or ""))


def unread_share(text: str) -> float:
    """The share of a line's letters the overlap measures cannot see: letters outside the Latin script (the tokenizer reads
    Latin words only, so a Devanagari sentence is an empty bag, or just the Latin names written inside it). A measure computed
    on part of a line cannot certify that the rest says nothing new."""
    letters = [c for c in (text or "") if c.isalpha()]
    return sum(ord(c) > 0x024F for c in letters) / len(letters) if letters else 0.0


def weekday_errors(text: str) -> list[str]:
    """A weekday that is not the day of the date it is written beside ("Tuesday, 28 October 2026": it is a Wednesday).
    Reported, never repaired: either the weekday or the date is the outlet's, and code cannot tell which."""
    out = []
    for m in _WEEKDAY_DATE.finditer(text or ""):
        day, d, mon, y = m.group(1).lower(), int(m.group(2)), m.group(3).lower(), int(m.group(4))
        try:
            month = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                     "november", "december"].index(mon) + 1
            real = _DAYS[dt.date(y, month, d).weekday()]
        except ValueError:
            continue
        if real != day:
            out.append(f"{m.group(0)} (a {real})")
    return out


# --- measures ------------------------------------------------------------------------------------------------------
def weights(profiles: list[Profile]) -> idf.Weights:
    return idf.Weights([set(bag(p)) for p in profiles])


def measures(W: idf.Weights, a: frozenset, b: frozenset) -> tuple[float, float, float]:
    """(cosine, share of a held by b, share of b held by a), all weighted by inverse document frequency."""
    wa, wb = sum(W.w(x) for x in a), sum(W.w(x) for x in b)
    if not wa or not wb:
        return 0.0, 0.0, 0.0
    sh = W.shared(set(a), set(b))
    return sh / math.sqrt(wa * wb), sh / wa, sh / wb


def adds_nothing(small: Profile, big: Profile, ts: str, tb: str, ignore_neg: bool = False) -> bool:
    """True when every fact of `small` that code can read is in `big`: figures (by value, at their own precision), clock
    times, years, a date, names, ordinals and the negation. What code cannot read (a plain word) is the measures' job."""
    if small.neg != big.neg and not ignore_neg:
        return False
    if not nums_within(small, big):
        return False
    if not small.clocks <= big.clocks or not small.years <= big.years:
        return False
    if small.date and not big.date:
        return False
    if small.date and big.date and any(x is not None and y is not None and x != y for x, y in zip(small.date, big.date)):
        return False
    if not ordinals(ts) <= ordinals(tb):
        return False
    cs, cb = core_names(small), core_names(big)
    from .relate import _names_match
    return all(any(_names_match(x, y) for y in cb) for x in cs)


def question_differs(pa: Profile, pb: Profile, ta: str, tb: str) -> str | None:
    """Why two lines on one subject cannot both stand as they are written: 'clock', 'date', 'figure' or 'negation'."""
    if pa.clocks and pb.clocks and not pa.clocks & pb.clocks:
        return "clock"
    if pa.date and pb.date and any(x is not None and y is not None and x != y for x, y in zip(pa.date, pb.date)):
        return "date"
    if pa.neg != pb.neg:
        return "negation"
    if pa.nums and pb.nums and not numbers_near(pa, pb, NEAR) and not (nums_within(pa, pb) or nums_within(pb, pa)):
        return "figure"
    return None


# --- one pair ------------------------------------------------------------------------------------------------------
def judge(i: int, j: int, ta: str, tb: str, pa: Profile, pb: Profile, W: idf.Weights, nli_fn=None) -> Verdict:
    ba, bb = bag(pa), bag(pb)
    cos, ca, cb = measures(W, ba, bb)

    def v(outcome, drop=None, keep=None, why=""):
        return Verdict(i, j, outcome, drop, keep, cos, ca, cb, why)

    if unread_share(ta) > UNREAD_MAX or unread_share(tb) > UNREAD_MAX:
        return v("distinct", why="a line is partly in a script the measures cannot read: coverage cannot be certified")

    # two quotations are never merged; one inside the other is the same words
    qa, qb = quotes(ta), quotes(tb)
    if qa and qb:
        if any(x in y or y in x for x in qa for y in qb) and cos >= OVERLAP:
            short, big = (i, j) if len(" ".join(qa)) <= len(" ".join(qb)) else (j, i)
            ps, pbig = (pa, pb) if short == i else (pb, pa)
            ts, tbig = (ta, tb) if short == i else (tb, ta)
            # the small line's quotation is IN the big one word for word, so its negations are too: only the rest is compared
            if adds_nothing(ps, pbig, ts, tbig, ignore_neg=True):
                return v("covered", short, big, "quotation inside a longer one")
            return v("overlap", why="quotation inside a longer one, but the line adds a fact")
        return v("distinct", why="two quotations")

    r = relate_pair(ta, tb, pa=pa, pb=pb)
    if r == "same":
        keep, drop = (i, j) if len(ta) >= len(tb) else (j, i)
        return v("same", drop, keep, "relate: same")
    if r in ("a_covers_b", "b_covers_a"):
        keep, drop = (i, j) if r == "a_covers_b" else (j, i)
        return v("covered", drop, keep, "relate: covers")

    if cos < OVERLAP and max(ca, cb) < HELD:
        return v("distinct", why="not one subject")
    if ordinals(ta) != ordinals(tb) and (ordinals(ta) and ordinals(tb)):
        return v("distinct", why="different ordinals")

    # how the two lines differ, read by `reconcile` (figures and dates as intervals, name aliases, negation by scope)
    diff = reconcile.difference(ta, tb, pa, pb)
    if diff.conflicts and any(k == "names" for k, _ in diff.soft):
        return v("distinct", why="different answers beside different names: different subjects")
    if diff.conflicts:
        if cos >= QUESTION:
            return Verdict(i, j, "conflict", None, None, cos, ca, cb, "; ".join(f"{k}: {x}" for k, x in diff.conflicts[:2]),
                           conflict_kind=diff.kind)
        return v("distinct", why="different answers, but not one question")
    # paired figures count as one word in both lines (7,395 and 7,395.55 are the same word here), so the measures see them
    for k, fp in enumerate(x for x in diff.pairs if x.relation in ("equal", "within", "covers", "near")):
        ta_tok, tb_tok = f"#{round(fp.a.value, 3)}", f"#{round(fp.b.value, 3)}"
        if ta_tok in ba and tb_tok in bb:
            ba = (ba - {ta_tok}) | {f"#pair{k}"}
            bb = (bb - {tb_tok}) | {f"#pair{k}"}
    cos, ca, cb = measures(W, ba, bb)
    if diff.status == "part":
        return v("overlap" if cos >= OVERLAP else "distinct", why="a smaller count of the same thing in a narrower place")

    # the small line is the one with less to say (less weight); `cont` is how much of it the other line holds
    wa, wb = sum(W.w(x) for x in ba), sum(W.w(x) for x in bb)
    small, big = (i, j) if (wa, len(ta)) <= (wb, len(tb)) else (j, i)
    cont = ca if small == i else cb
    ps, pbig = (pa, pb) if small == i else (pb, pa)
    ts, tbig = (ta, tb) if small == i else (tb, ta)
    nothing = diff.adds_nothing("a" if small == i else "b") and ordinals(ts) <= ordinals(tbig)
    # the second reading of each near figure, oriented to the line that stays
    notes = tuple(((n[2], n[1]) if small == i else (n[1], n[2])) for n in diff.notes)      # (the figure of the line that stays, the other reading)
    if cont >= COVER and nothing:
        if quotes(ts) and not quotes(tbig):
            return v("overlap", why="a quotation is kept, the other line says the same around it")
        if _LEANS.match(tbig) and not _LEANS.match(ts):
            return v("overlap", why="the longer line leans on the one before it (a pronoun): the fold would leave it without a subject")
        return Verdict(i, j, "covered", small, big, cos, ca, cb, f"{cont:.2f} of the shorter line is in the longer", notes)
    if cos >= OVERLAP or cont >= HELD:
        if nli_fn is not None and nothing and not (quotes(ts) and not quotes(tbig)):
            try:
                ok = nli_fn([(tbig, ts)])[0]
            except Exception:  # noqa: BLE001
                ok = None
            if ok:
                return Verdict(i, j, "covered", small, big, cos, ca, cb, "reader: the longer line says all the shorter says", notes)
        return v("overlap", why="each line adds a detail")
    return v("distinct", why="below the overlap floor")


# --- a paragraph, an article ---------------------------------------------------------------------------------------
def _cls(x: dict) -> str:
    return x.get("class") or "unverified"


def _rank(c: str) -> int:
    try:
        from .recap import CLASS_RANK
    except Exception:  # noqa: BLE001
        CLASS_RANK = {"established": 0, "developing": 1, "unverified": 2, "partial": 3, "single": 4, "disputed": 5, "false": 6}
    return CLASS_RANK.get(c, 2)


def pairs_of(paragraphs: list[list[dict]], nli_fn=None) -> list[tuple[int, Verdict]]:
    """Every pair of lines inside a paragraph, judged. [(paragraph index, Verdict)]; a/b are positions in the paragraph."""
    profiles = [[Profile(x.get("text") or "") for x in para] for para in paragraphs]
    W = weights([p for ps in profiles for p in ps])
    out = []
    for n, para in enumerate(paragraphs):
        for i in range(len(para)):
            for j in range(i + 1, len(para)):
                ta, tb = para[i].get("text") or "", para[j].get("text") or ""
                if ta.strip() and tb.strip():
                    out.append((n, judge(i, j, ta, tb, profiles[n][i], profiles[n][j], W, nli_fn)))
    return out


def _fold(host: dict, gone: dict) -> None:
    """The host takes the ids and sources of the line that goes, and the weaker colour of the two."""
    host["ids"] = list(dict.fromkeys(list(host.get("ids") or []) + list(gone.get("ids") or [])))
    if "sources" in host or "sources" in gone:
        host["sources"] = sorted(set(host.get("sources") or []) | set(gone.get("sources") or []))
    if "class" in host or "class" in gone:
        host["class"] = max(_cls(host), _cls(gone), key=_rank)
    host.pop("parts", None)                  # which part belongs to whom is unknown: one colour


def _orphans(para: list[dict], gone: set, drop: int, keep: int) -> bool:
    """Would taking line `drop` out leave the next line, which leans on it (He / She / It / This ...), after a line that is
    not the survivor? A pronoun needs the sentence before it: dropping its antecedent in favour of a line elsewhere strands it."""
    nxt = next((k for k in range(drop + 1, len(para)) if k not in gone), None)
    if nxt is None or not _LEANS.match(para[nxt].get("text") or ""):
        return False
    prev = next((k for k in range(drop - 1, -1, -1) if k not in gone), None)
    return prev != keep and nxt != keep


def _reading_notes(a: str, b: str, merged: str) -> list:
    """The readings of a figure that the merged sentence did not keep: [(kept, other)]."""
    from .relate import Profile
    out = []
    for facet, x, y in reconcile.difference(a, b, Profile(a), Profile(b)).notes:
        if x in merged and y not in merged:
            out.append((x, y))
        elif y in merged and x not in merged:
            out.append((y, x))
    return out


def _variants(host: dict, gone: dict, notes) -> None:
    """Another outlet's reading of a figure the host keeps, as data: {"shown", "value", "ids", "sources"}."""
    for shown, other in notes:
        host.setdefault("variants", []).append({"shown": shown, "value": other, "ids": list(gone.get("ids") or []),
                                                "sources": list(gone.get("sources") or [])})


def _reader_says(nli_fn, keep: str, drop: str) -> bool | None:
    """Does the kept line say everything the dropped one says (the local reader, premise = kept)? None = could not read."""
    if nli_fn is None:
        return None
    try:
        return nli_fn([(keep, drop)])[0]
    except Exception:  # noqa: BLE001
        return None


def tidy(paragraphs: list[list[dict]], protect=frozenset(), nli_fn=None, rewrite=None, fuse=True, verify=True) -> tuple[list[list[dict]], dict]:
    """The article with its repeats folded, and a report. Nothing is changed in place. `protect`: ids that are never
    folded (the lead's, a dispute's). `rewrite(a, b) -> str | None` makes one sentence of two overlapping lines; it is
    optional and every answer is checked by `verify_merge`. `fuse`: two overlapping lines are first merged by CODE
    (`fusion.fuse`: an edit of one line with the other's attachable detail); a model is only the fallback, asked once.
    A fold whose dropped line read a figure a little differently keeps that reading as DATA on the line that stays
    (`variants`: the value and the sources that gave it), never as words in the sentence: the site shows it on tap, the way it
    already shows source numbers."""
    paras = [[dict(x) for x in para] for para in paragraphs]
    judged = pairs_of(paras, nli_fn)
    report = {"pairs": len(judged), "outcomes": {}, "folded": 0, "merged": 0, "merge_refused": 0, "skipped_guard": 0,
              "to_one_sentence": 0, "unverified": 0, "reader_refused": 0, "items": []}
    for _, vd in judged:
        report["outcomes"][vd.outcome] = report["outcomes"].get(vd.outcome, 0) + 1
    gone: set[tuple[int, int]] = set()

    def guarded(x: dict) -> bool:
        return _cls(x) in GUARDED or bool(set(x.get("ids") or []) & set(protect))

    order = {"same": 0, "covered": 1, "overlap": 2}
    for n, vd in sorted((t for t in judged if t[1].outcome in order), key=lambda t: (order[t[1].outcome], -t[1].cos)):
        para = paras[n]
        a, b = para[vd.a], para[vd.b]
        item = {"paragraph": n, **vd.as_dict(), "a_text": a.get("text"), "b_text": b.get("text")}
        if (n, vd.a) in gone or (n, vd.b) in gone:
            continue
        if guarded(a) or guarded(b):
            report["skipped_guard"] += 1
            item["applied"] = "guarded"
            report["items"].append(item)
            continue
        if vd.outcome in ("same", "covered"):
            if _orphans(para, gone, vd.drop, vd.keep):
                report["skipped_guard"] += 1
                item["applied"] = "guarded: the line after it would be left without its subject"
                report["items"].append(item)
                continue
            if verify:                                          # the reader must read: kept line says all the dropped one says
                says = _reader_says(nli_fn, para[vd.keep]["text"], para[vd.drop]["text"])
                item["reader"] = says
                if says is not True:
                    report["unverified" if says is None else "reader_refused"] += 1
                    item["applied"] = "unverified: no reader answer" if says is None else "refused: the reader does not read the kept line as saying it all"
                    report["items"].append(item)
                    continue
            _fold(para[vd.keep], para[vd.drop])
            _variants(para[vd.keep], para[vd.drop], vd.notes)
            gone.add((n, vd.drop))
            report["folded"] += 1
            item["applied"] = "folded"
        else:
            merged, how = None, ""
            if fuse:                                           # by code: the lines' own words, an attachable detail added
                from . import fusion
                try:
                    got = fusion.fuse(a["text"], b["text"])
                except Exception:  # noqa: BLE001
                    got = None
                if got:
                    merged, how = got["text"], "fusion"
            if merged is None and rewrite is not None and (vd.cos >= REWRITE_MIN or max(vd.cont_a, vd.cont_b) >= HELD):
                try:                                           # a model, asked once; the check below is what decides
                    merged, how = rewrite(a["text"], b["text"]), "model"
                except Exception:  # noqa: BLE001
                    merged = None
            if merged is None:
                item["applied"] = "candidate"
                report["items"].append(item)
                continue
            ok, why = tidy_check(a["text"], b["text"], merged)
            if ok:
                notes = _reading_notes(a["text"], b["text"], merged)
                a["text"] = merged.strip()
                _fold(a, b)
                _variants(a, b, notes)
                gone.add((n, vd.b))
                report["merged"] += 1
                report.setdefault("merged_by", {})[how] = report.get("merged_by", {}).get(how, 0) + 1
                item["applied"] = f"merged ({how})"
                item["merged_text"] = a["text"]
            else:
                report["merge_refused"] += 1
                item["applied"] = f"refused: {why}"
        report["items"].append(item)
    out = []
    for n, para in enumerate(paras):
        keep = [x for k, x in enumerate(para) if (n, k) not in gone]
        if len(keep) == 1 and len(para) > 1:
            report["to_one_sentence"] += 1
        if keep:
            out.append(keep)
    return out, report


# --- the check on a merged sentence --------------------------------------------------------------------------------
def tidy_check(a: str, b: str, merged: str | None) -> tuple[bool, str]:
    return verify_merge(a, b, merged)


def verify_merge(a: str, b: str, merged: str | None) -> tuple[bool, str]:
    """Is `merged` the two lines in one sentence and nothing else? Every figure, name, date, clock time and quotation of
    both is in it; nothing new; one sentence; the same negation. (The model proposes; this decides.)"""
    if not merged or not merged.strip():
        return False, "empty"
    m = merged.strip()
    if _SENT_BREAK.search(m):
        return False, "more than one sentence"
    if len(m) > len(a) + len(b):
        return False, "longer than both together"
    sa, sb = claim_strength(a), claim_strength(b)
    if sa != sb:
        return False, f"the lines claim different amounts ({sorted(sa ^ sb)})"
    if claim_strength(m) != sa:
        return False, "the sentence claims a different amount"
    pa, pb, pm = Profile(a), Profile(b), Profile(m)
    if pa.neg != pb.neg or pm.neg != pa.neg:
        return False, "negation"
    for x in set(pa.nums) | set(pb.nums):
        if not any(abs(x - y) <= NEAR * max(abs(x), abs(y), 1e-9) for y in pm.nums):
            return False, f"figure {x} lost"
    for y in pm.nums:
        if not any(abs(x - y) <= NEAR * max(abs(x), abs(y), 1e-9) for x in set(pa.nums) | set(pb.nums)):
            return False, f"figure {y} invented"
    if (pa.clocks | pb.clocks) != pm.clocks or (pa.years | pb.years) != pm.years:
        return False, "date or time changed"
    if pm.date and not (pa.date == pm.date or pb.date == pm.date):
        return False, "date changed"
    from .relate import _names_match
    union = core_names(pa) | core_names(pb)
    mine = core_names(pm)
    if any(not any(_names_match(x, y) for y in mine) for x in union):
        return False, "a name was lost"
    if any(not any(_names_match(x, y) for y in union) for x in mine):
        return False, "a name was invented"
    for q in _QUOTE.findall(a) + _QUOTE.findall(b):
        if q not in m:
            return False, "a quotation was changed"
    new = set(pm.roots) - set(pa.roots) - set(pb.roots)
    if len(new) > NEW_ROOTS:
        return False, f"new words: {sorted(new)[:4]}"
    return True, "ok"

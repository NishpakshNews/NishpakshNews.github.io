"""Are two statements the same fact? One place decides it, for the whole pipeline (owner, Oct 7 2026).

It replaces a chain of judges that could each veto the others (Oct 5-7: real_difference,
typed_difference, frames, may_be_same, same_facts), where a weak model's labels outvoted the words:
"11 of the 12 injured crew members are Indian nationals", word for word from two outlets, stayed two
statements because the two readings labelled it "identify / nationality" and "be / Indian nationals".

The words outrank the labels. Judges, in this order:

  1. code, on the words themselves: the numbers (as numbers: "eleven" = 11, "1.2 lakh" = 120000),
     the names (capitalised words inside the sentence) and the root words (stemmed, small words out)
       same        identical wording; or the same numbers, the same names and almost the same words
       covers      one says everything the other says (every number, name and nearly every word) and more:
                   the detailed line takes in the short one ("12 crew members, including 11 Indians, were
                   injured" covers "12 crew members were injured")
       different   different numbers or names, one negated and the other not, or little in common
       ask         the same numbers and names, but worded differently enough that code cannot tell
  2. the model, only for "ask": one plain question (match.same_facts), asked twice with A and B swapped;
     only two "same" answers count
  3. labels (statement frames) only point to pairs worth looking at; they never block anything

A covered line is not merged into the detailed one (that would lend its outlets to details they never
reported, and could turn them green): it is kept, marked covered, and not written separately.
"""
from __future__ import annotations

import re

from . import figures
from .frames import STOP as _STOP, _stem, numbers as _numbers, words as _roots

# the words of a spelled number ("twenty", "six", "crore", "dozen") are not root words: their value is in `nums`,
# so "twenty-six crore" and "26 crore" have the same words as well as the same figures
_NUMBER_STEMS = {_stem(w) for w in figures.NUMBER_WORDS}
NEGATION = re.compile(r"(?i)\b(not|no|never|nobody|none|neither|nor|without|denied|denies|deny|refused|"
                      r"refuses|rejected|rejects)\b|n't\b")
# words that say how a line was reported, not what happened: never a difference between two lines
FILLER = {_stem(w) for w in """said say says stated told added according report reports reported article also
officials official sources source claimed claims noted informed confirmed will would shall can could may might
must also new current currently""".split()}

# the same meaning in other words, as Indian news writes it (owner, Oct 7 2026): each group is read as
# ONE word. Kept short and hand-checked: words that differ in meaning are never grouped ("injured" and
# "killed" stay apart; so do "arrested" and "questioned").
# The list lives in config/synonyms.yaml so it can keep growing without touching code (owner, Oct 11 2026: "where
# they can keep on adding"); this short list is only the fallback when that file is missing or broken. Pairs the
# outlets themselves show are appended by learn_synonyms.py to config/synonyms_learned.yaml and read after it.
DEFAULT_SYNONYM_GROUPS = [
    "injured hurt wounded", "killed dead died death deaths die dies lost", "arrested detained nabbed apprehended",
    "attack attacked assault assaulted", "vessel ship boat", "blast explosion", "fire blaze",
    "police cops", "rescued saved", "missing untraceable", "village hamlet", "residents locals",
    "part section portion", "collapsed caved",
]


def load_never() -> list[frozenset[str]]:
    """The `never:` lines of config/synonyms.yaml: words that are never one word, however often the outlets seem to
    swap them (each line: the stems of its words; any two of them must stay apart). Empty when there is no such
    list or the file is broken."""
    try:
        from .config import load_yaml
        raw = (load_yaml("synonyms.yaml") or {}).get("never") or []
        return [frozenset(_stem(w) for w in str(g).lower().split()) for g in raw if isinstance(g, str) and len(g.split()) >= 2]
    except Exception:  # noqa: BLE001
        return []


def _learned_raw() -> list[dict]:
    """The well-formed entries of config/synonyms_learned.yaml (a dict with a string `words` of 2+ words, not two
    words of a `never:` line). A missing or broken file gives nothing."""
    try:
        from .config import load_yaml
        raw = (load_yaml("synonyms_learned.yaml") or {}).get("groups") or []
        never = load_never()
        out = []
        for g in raw:
            words = " ".join(str(g.get("words")).lower().split()) if isinstance(g, dict) and isinstance(g.get("words"), str) else ""
            stems = {_stem(w) for w in words.split()}
            if len(words.split()) >= 2 and not any(len(stems & n) >= 2 for n in never):
                out.append(dict(g, words=words))
        return out
    except Exception:  # noqa: BLE001
        return []


def load_learned_groups() -> list[str]:
    """Learned groups that apply EVERYWHERE: lines in the learned file with no `context` (written there by hand),
    read after the hand-written file so its groups win. Pairs the job learned carry their context and apply only
    where it matches (`LEARNED_SENSES`, owner Oct 16 2026: "charge" is an allegation in court and a fee in a shop)."""
    return [g["words"] for g in _learned_raw() if not g.get("context")]


def load_learned_senses() -> list[dict]:
    """The learned pairs with their context: [{"stems": (a, b), "section": str, "context": set of stems}]."""
    out = []
    for g in _learned_raw():
        ctx = g.get("context")
        if not ctx:
            continue
        ws = [_stem(w) for w in g["words"].split()][:2]
        if len(ws) == 2 and ws[0] != ws[1]:
            out.append({"stems": tuple(ws), "section": str(g.get("section") or ""),
                        "context": {str(w) for w in ctx}})
    return out


def load_synonym_groups() -> list[str]:
    """The groups of config/synonyms.yaml (one string of space-separated words each), then the learned ones; the
    built-in list instead of the hand-written file when it is missing, broken or empty. A line that is not a string
    of 2+ words is skipped."""
    try:
        from .config import load_yaml
        raw = (load_yaml("synonyms.yaml") or {}).get("groups") or []
        groups = [" ".join(str(g).lower().split()) for g in raw if isinstance(g, str) and len(str(g).split()) >= 2]
    except Exception:  # noqa: BLE001  (a missing or malformed file must never stop a run)
        groups = []
    return (groups or list(DEFAULT_SYNONYM_GROUPS)) + load_learned_groups()


def build_synonyms(groups: list[str]) -> dict[str, str]:
    """{stemmed word: the group's first stemmed word}. A word already in an earlier group stays there."""
    out: dict[str, str] = {}
    for g in groups:
        ws = [_stem(w) for w in g.split()]
        for w in ws:
            out.setdefault(w, ws[0])
    return out


SYNONYM_GROUPS = load_synonym_groups()
SYNONYM = build_synonyms(SYNONYM_GROUPS)
LEARNED_SENSES = load_learned_senses()


def learned_map(pa: "Profile", pb: "Profile", section: str = "", senses: list[dict] | None = None) -> dict[str, str]:
    """{stem: the pair's first stem} for the learned pairs that join these two lines HERE: one word in each line, and
    the two lines' other words matching one of the pair's senses (context.best: the section if known, and 2+ of the
    sense's context words, 3+ when the section is unknown, as while statements are matched before publication)."""
    from . import context
    senses = LEARNED_SENSES if senses is None else senses
    if not senses:
        return {}
    out: dict[str, str] = {}
    by_pair: dict[tuple, list[dict]] = {}
    for s in senses:
        by_pair.setdefault(tuple(sorted(s["stems"])), []).append(s)
    ra, rb = pa.roots | pa.names, pb.roots | pb.names
    for pair, ss in by_pair.items():
        x, y = pair
        if not ((x in ra and y in rb) or (y in ra and x in rb)) or (x in ra and y in ra) or (x in rb and y in rb):
            continue
        ctx = (pa.roots | pb.roots) - {x, y}
        cand = {i: context.Sense(s["section"], context.YOUNG + 1, {w: context.SIGNATURE_MIN for w in s["context"]})
                for i, s in enumerate(ss)}
        if context.best(cand, section, ctx) is not None:
            out[y] = x
    return out

SAME_WORDS = 0.8        # share of root words for "same" (with the same numbers and names)
COVER_WORDS = 0.85      # share of the short line's root words the detailed line must contain
ASK_WORDS = 0.4         # below this, two lines with the same numbers and names are still different


# words that can turn the detailed line into a different event ("arrested him in another case")
CONTRAST = re.compile(r"(?i)\b(another|other|earlier|previous|previously|former|formerly|last year|last month|"
                      r"separate|different|second|again|also|before|after)\b")


_DATE_WORDS = {_stem(w) for w in """monday tuesday wednesday thursday friday saturday sunday january february
march april may june july august september october november december jan feb mar apr jun jul aug sep sept oct
nov dec""".split()}


_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


class Profile:
    __slots__ = ("norm", "nums", "names", "roots", "neg", "contrast", "date", "years", "clocks")

    def __init__(self, text: str):
        t = text or ""
        self.norm = re.sub(r"\W+", " ", t.lower()).strip()
        # a clock time is a time, not figures and not a name ("12:30 PM" read as 12, 30 and a name "PM" kept two
        # tellings of the Ladakh inauguration apart, Oct 15 2026); compared as times, through the statements' times
        from .when import find as _find_times
        clocks = set()
        for m in reversed([m for m in _find_times(t) if m.kind == "clock"]):
            clocks.add(_clock_value(m.text))
            t = t[:m.start] + " " + t[m.end:]
        self.clocks = frozenset(c for c in clocks if c)
        # the numbers of a date are a time, compared as one (times), not figures ("October 8, 2026")
        nt = re.sub(r"(?i)\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTHS + r"\b(?:,?\s+(?:19|20)\d\d)?|"
                    + _MONTHS + r"\s+\d{1,2}(?:st|nd|rd|th)?\b(?:,?\s+(?:19|20)\d\d)?|\b(?:19|20)\d\d\b", " ", t)
        # figures.py: 26 = twenty-six = twenty six = २६, 1.2 lakh = 1,20,000, "29th", "Section IV" = "Section 4"
        self.nums = frozenset(round(x, 3) for x in _numbers(nt))
        # names: capitalised words inside the sentence (the first word is capitalised anyway)
        toks = re.findall(r"[A-Za-z][\w'-]*", t)
        names = {_stem(w.lower()) for w in toks[1:] if w[0].isupper() and len(w) > 1}
        # the first word is a name when it starts a run of capitalised words ("Air Marshal ...")
        if len(toks) > 1 and toks[0][0].isupper() and toks[1][0].isupper() and toks[0].lower() not in _STOP:
            names.add(_stem(toks[0].lower()))
        # days and months are dates, compared as dates (times), not names: "on Thursday" kept two
        # tellings of one call apart (Oct 8 2026, story 14231)
        self.names = frozenset(names - _DATE_WORDS - _CURRENCY)
        # negation written into a word reads as the word negated: "unaffected" = "not affected" (polarity.py)
        from .polarity import as_particles
        tp = as_particles(t)
        self.roots = frozenset(SYNONYM.get(r, r) for r in _roots(tp)
                               if r not in FILLER and r not in _NUMBER_STEMS and r not in _CURRENCY and not r.isdigit())
        self.neg = bool(NEGATION.search(tp))
        from .frames import date_of
        self.date = date_of(t)
        self.years = frozenset(re.findall(r"\b(?:19|20)\d\d\b", t))
        self.contrast = bool(CONTRAST.search(t))


# the currency is said by the number's own word: "Rs 375" = "375 rupees" = "₹375" (Oct 16 2026 audit, story 26318)
_CURRENCY = {"rs", "inr", "rupe", "rupee", "rupees"}


def _with_roots(p: "Profile", m: dict[str, str]) -> "Profile":
    q = Profile.__new__(Profile)
    for k in Profile.__slots__:
        setattr(q, k, getattr(p, k))
    q.roots = frozenset(m.get(r, r) for r in p.roots)
    return q


def _with_names(p: "Profile", names: frozenset) -> "Profile":
    if names == p.names:
        return p
    q = Profile.__new__(Profile)
    for k in Profile.__slots__:
        setattr(q, k, getattr(p, k))
    q.names = frozenset(names)
    return q


def _share(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def _within(small: frozenset, big: frozenset) -> float:
    return len(small & big) / len(small) if small else 1.0


def _times_apart(x: dict | None, y: dict | None) -> bool:
    from .frames import _times_apart as apart
    return apart(x, y)


def _clock_value(s: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*([ap])?", (s or "").lower())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "p" and h < 12:
        h += 12
    if m.group(3) == "a" and h == 12:
        h = 0
    return (h, mi)


def relate(a: str, b: str, time_a: dict | None = None, time_b: dict | None = None,
           pa: Profile | None = None, pb: Profile | None = None) -> str:
    """'same', 'a_covers_b', 'b_covers_a', 'ask' or 'different', by code from the words. Clock times (Oct 16 2026):
    two different ones are different facts; a time only one line has is a detail it adds, so code never lets the
    line without it stand for both: the model is asked whether the timed line covers the other."""
    pa, pb = pa or Profile(a), pb or Profile(b)
    if pa.clocks and pb.clocks and not pa.clocks & pb.clocks:
        return "different"
    r = _relate(a, b, time_a, time_b, pa, pb)
    if r not in ("same", "a_covers_b", "b_covers_a"):
        m = learned_map(pa, pb)
        if m:                                 # a learned pair whose context fits these two lines: one word here
            r2 = _relate(a, b, time_a, time_b, _with_roots(pa, m), _with_roots(pb, m))
            if r2 != "different":
                r = r2
    if bool(pa.clocks) != bool(pb.clocks) and r in ("same", "ask", "a_covers_b", "b_covers_a"):
        timed_a = bool(pa.clocks)
        if r == "same" or r == "ask" or (r == "a_covers_b") != timed_a:
            return "ask_a_covers_b" if timed_a else "ask_b_covers_a"
    return r


def _relate(a: str, b: str, time_a, time_b, pa: Profile, pb: Profile) -> str:
    if pa.neg != pb.neg or _times_apart(time_a, time_b):
        return "different"
    # dates in the words: two lines with different dates are never one fact (arrested in 2019 / 2024)
    if pa.years and pb.years and not pa.years & pb.years:
        return "different"
    if pa.date and pb.date and any(x is not None and y is not None and x != y for x, y in zip(pa.date, pb.date)):
        return "different"
    if pa.norm == pb.norm:
        return "same"
    # the names both lines share (the subject, "Air Marshal Ashutosh Dixit") are compared as names and
    # left out of the word overlap: in a story about one person every line shares them, and they made
    # unrelated lines look alike (Oct 7 2026, story 13809)
    # a name one line capitalises and the other writes in lower case is the same name ("Divyangjan Pension Scheme" /
    # "divyangjan pension scheme", Oct 16 2026 audit: Hindi-sourced lines often lose the capitals)
    na, nb = pa.names | (pb.names & pa.roots), pb.names | (pa.names & pb.roots)
    pa, pb = _with_names(pa, na), _with_names(pb, nb)
    common = pa.names & pb.names
    ra, rb = pa.roots - common, pb.roots - common
    same_facts = pa.nums == pb.nums and pa.names == pb.names
    if same_facts and _share(ra, rb) >= SAME_WORDS:
        return "same"
    for big, small, rbig, rsmall, label in ((pa, pb, ra, rb, "a_covers_b"), (pb, pa, rb, ra, "b_covers_a")):
        if (len(rsmall) >= 3 and len(rbig) > len(rsmall) and small.nums <= big.nums
                and small.names <= big.names and _within(rsmall, rbig) >= COVER_WORDS):
            # code alone only when the detailed line adds no number and no word that could make it a
            # different event; otherwise the model is asked
            if big.nums == small.nums and not (big.contrast and not small.contrast):
                return label
            return "ask_" + label
    if same_facts and _share(ra, rb) >= ASK_WORDS and (pa.nums or pa.names or len(ra) >= 3):
        return "ask"
    # nearly covered: every number and name, all but one or two words ("injured in the incident" /
    # "injured in the attack"); code cannot tell "incident" = "attack" from "injured" vs "killed",
    # so the model is asked whether the detailed line says everything the short one says
    for big, small, rbig, rsmall, label in ((pa, pb, ra, rb, "ask_a_covers_b"), (pb, pa, rb, ra, "ask_b_covers_a")):
        if (len(rsmall) >= 2 and len(rbig) > len(rsmall) and small.nums <= big.nums and small.names <= big.names
                and len(rsmall - rbig) <= 1 and _within(rsmall, rbig) >= 0.6):
            return label
    return "different"


def group(texts: dict[int, str], times: dict[int, dict | None] | None = None, asked: dict | None = None
          ) -> tuple[list[tuple[int, int]], dict[int, int], list[tuple[int, int]], list[tuple[int, int]]]:
    """For a story's statements {id: text}: (pairs that are the same, {covered id: covering id}, pairs
    to ask "same?", pairs (detailed, short) to ask "covers?"). Code only; the caller asks the model."""
    times = times or {}
    prof = {i: Profile(t) for i, t in texts.items()}
    ids = sorted(texts)
    same, covered, ask, ask_cover = [], {}, [], []
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            r = relate(texts[a], texts[b], times.get(a), times.get(b), prof[a], prof[b])
            if r == "same":
                same.append((a, b))
            elif r == "a_covers_b":
                covered.setdefault(b, a)
            elif r == "b_covers_a":
                covered.setdefault(a, b)
            elif r == "ask":
                ask.append((a, b))
            elif r == "ask_a_covers_b":
                ask_cover.append((a, b))
            elif r == "ask_b_covers_a":
                ask_cover.append((b, a))
    return same, covered, ask, ask_cover


def resolve_covered(covered: dict[int, int]) -> dict[int, int]:
    """Each covered line points at the most detailed line that covers it (no chains, no loops)."""
    out = dict(covered)
    for x in list(out):
        seen = {x}
        while out.get(out[x]) is not None and out[out[x]] not in seen:
            seen.add(out[x])
            out[x] = out[out[x]]
        if out[x] == x:
            del out[x]
    return out


def numbers_close(pa: Profile, pb: Profile, tol: float = 0.05) -> bool:
    """Every number of the line with fewer numbers has one within `tol` in the other (rounding:
    "125.27 million" / "about 125 million"); True when either line has none."""
    small, big = sorted((pa.nums, pb.nums), key=len)
    if not small:
        return True
    return all(any(abs(x - y) <= tol * max(abs(x), abs(y), 1e-9) for y in big) for x in small)

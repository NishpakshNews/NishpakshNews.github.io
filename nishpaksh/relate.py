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

import datetime as dt

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
# they can keep on adding"); this short list is only the fallback when that file is missing or broken.
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
    return groups or list(DEFAULT_SYNONYM_GROUPS)


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


SAME_WORDS = 0.8        # share of root words for "same" (with the same numbers and names)
COVER_WORDS = 0.85      # share of the short line's root words the detailed line must contain
ASK_WORDS = 0.4         # below this, two lines with the same numbers and names are still different


# words that can turn the detailed line into a different event ("arrested him in another case")
# "another event" cues: contrast.py (a closed-class seed plus the words the newsroom's own answers show to tell pairs apart)


_DATE_WORDS = {_stem(w) for w in """monday tuesday wednesday thursday friday saturday sunday january february
march april may june july august september october november december jan feb mar apr jun jul aug sep sept oct
nov dec""".split()}


_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


_NORM_RULES = [
    (re.compile(r"[\u2010-\u2015\u2212]"), "-"),                                    # every dash is a hyphen
    (re.compile(r"(?i)(?:\b(?:rs\.?|inr|rupees?)|₹)\s*(?=\d)|(?<=\d)\s*(?:rupees?)\b"), " rs "),   # Rs 375 = 375 rupees = ₹375
    (re.compile(r"(?i)\bper\s*cent\b|\bpercent\b|%"), " percent "),
    (re.compile(r"(?<=\d)\s*[-–]\s*(?=\d)"), " to "),                                # a range: 10-12 = 10 to 12
    (re.compile(r"(?i)\bbetween\s+(\d[\d.,]*)\s+and\s+(\d)"), r"\1 to \2"),
]


def fold_latin(text: str) -> str:
    """Accents off Latin letters only (Inácio = Inacio, Flávio = Flavio: one line was folded, the other not, and the
    names then "differed", merge_audit Oct 26 2026); Devanagari and every other script are left exactly as written."""
    import unicodedata
    if text.isascii():
        return text
    out = []
    for ch in text:
        if ord(ch) < 0x250 and not ch.isascii():
            d = unicodedata.normalize("NFD", ch)
            ch = "".join(c for c in d if not unicodedata.combining(c)) or ch
        out.append(ch)
    return "".join(out)


def normalise(text: str) -> str:
    """B8: the form two lines are compared in: NFKC, one hyphen, one way to write rupees and per cent, a range as "a to b",
    lower case, punctuation and spacing gone. Two lines equal here are the same words (the exact-match fast path)."""
    import unicodedata
    t = unicodedata.normalize("NFKC", text or "")
    for rx, rep in _NORM_RULES:
        t = rx.sub(rep, t)
    return re.sub(r"\W+", " ", t.lower()).strip()


def _ner_names(text: str) -> set[str]:
    try:
        from . import nlp
        out = set()
        for e in nlp.ents(text):
            if e.label == nlp.PERSON or e.label in nlp.NOT_PERSON_LABELS:
                for w in re.findall(r"[A-Za-z][\w'-]*", e.text):
                    if len(w) > 1:
                        out.add(_stem(w.lower()))
        return out
    except Exception:  # noqa: BLE001
        return set()


class Profile:
    __slots__ = ("norm", "nums", "names", "roots", "neg", "contrast", "date", "years", "clocks")

    def __init__(self, text: str):
        t = fold_latin(text or "")
        self.norm = normalise(t)
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
        # S11: the names a named-entity model finds join the capitalisation rule's (a name that opens the sentence, or that
        # Hindi-sourced text writes in lower case); a missing model adds nothing
        names |= _ner_names(t)
        self.names = frozenset(names - _DATE_WORDS - _CURRENCY)
        tp = t
        self.roots = frozenset(SYNONYM.get(r, r) for r in _roots(tp)
                               if r not in FILLER and r not in _NUMBER_STEMS and r not in _CURRENCY and not r.isdigit())
        self.neg = bool(NEGATION.search(tp))
        from .frames import date_of
        self.date = date_of(t)
        self.years = frozenset(re.findall(r"\b(?:19|20)\d\d\b", t))
        from . import contrast as _c
        self.contrast = _c.has(t)


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
        rr = _result_relation(a, b, time_a, time_b, pa, pb)
        if rr:
            r = rr
    if bool(pa.clocks) != bool(pb.clocks) and r in ("same", "ask", "a_covers_b", "b_covers_a"):
        timed_a = bool(pa.clocks)
        if r == "same" or r == "ask" or (r == "a_covers_b") != timed_a:
            return "ask_a_covers_b" if timed_a else "ask_b_covers_a"
    return r


# -- a contest's result, however it is worded (Oct 16 2026: one express page said "Suhas LY defeated Joytu Dhar ..."
# and "Suhas LY overcame Joytu Dhar 21-8, 21-11 ...", and "Joshi and Raghupati lost to Sadiyah and Setiawan" next to
# "Sadiyah and Setiawan defeated Joshi and Raghupati 21-15, 21-4"). Two lines that name the same winner and the same
# loser report one result; the line with the score covers the one without; two different scores are left to the rest.
_WIN = (r"defeated|defeats|defeat|beat|beats|overcame|overcomes|overcome|edged(?:\s+out|\s+past)?|edges|thrashed|"
        r"outclassed|outplayed|downed|stunned|upset|prevailed\s+over|got\s+the\s+better\s+of|knocked\s+out|eliminated|"
        r"won\s+against|triumphed\s+over")
_LOSE = (r"lost\s+to|loses\s+to|lose\s+to|went\s+down\s+to|goes\s+down\s+to|fell\s+to|falls\s+to|"
         r"(?:was|were)\s+(?:defeated|beaten|edged|knocked\s+out|eliminated|stunned|upset|outclassed)\s+by")
_WIN_RE = re.compile(rf"^(?P<x>.*?)\s+(?:{_WIN})\s+(?P<y>.+)$", re.I)
_LOSE_RE = re.compile(rf"^(?P<y>.*?)\s+(?:{_LOSE})\s+(?P<x>.+)$", re.I)
_SIDE_JOIN = {"and", "&", "of", "de", "van", "der", "bin", "al"}
_OPENERS_CAP = {"on", "in", "at", "after", "before", "the", "a", "an", "when", "while", "earlier", "later", "then"}
_CODE = re.compile(r"[A-Z]{1,3}\d+[A-Z]?")          # a category or class code (SL3, SU5, U23, T20): not a score
# what tells two contests between the same sides apart, one dimension at a time: two lines that both name a stage, a
# kind of event or a sport, and share none of it, are two contests
_EVENT_DIMS = [{_stem(w) for w in s.split()} for s in (
    "final finals semifinal semi-final semi quarterfinal quarter-final quarter league qualifier qualifying playoff "
    "play-off heat repechage",
    "singles doubles mixed men women boys girls junior senior",
    "hockey cricket football kabaddi badminton tennis wrestling boxing shooting archery athletics chess volleyball "
    "basketball test odi t20 t20i ipl ranji")]


def _score_nums(text: str) -> frozenset:
    """The numbers of a result line without its category codes ("SL3-SU5", "U23"): the score and margin."""
    return frozenset(round(x, 3) for x in _numbers(_CODE.sub(" ", text or "")))


def _side(text: str, tail: bool) -> frozenset:
    """The names of one side of a result: the run of capitalised words that ends the text before the verb (`tail`)
    or starts the text after it ("Joytu Dhar in the men's singles" -> {joytu, dhar})."""
    if tail:
        text = text.split(",")[-1]             # "On Saturday, India" -> "India"
    toks = re.findall(r"[\w'.-]+", text)
    if tail:
        toks = toks[::-1]
    out = []
    for t in toks:
        w = t.strip(".'")
        if w.lower() in _OPENERS_CAP or _stem(w.lower()) in _DATE_WORDS:
            break
        if w[:1].isupper() and not _CODE.fullmatch(w) and not w[:1].isdigit():
            out.append(w.lower())
        elif w.lower() in _SIDE_JOIN and out:
            continue
        else:
            break
    return frozenset(_stem(w) for w in out if w != "the" and len(w) > 1)


def result_of(text: str) -> tuple[frozenset, frozenset] | None:
    """(winner names, loser names) of a line that reports who beat whom, or None."""
    t = re.sub(r"\s+", " ", (text or "").strip().rstrip("."))
    for rx in (_LOSE_RE, _WIN_RE):
        m = rx.match(t)
        if m:
            x, y = _side(m.group("x"), tail=rx is _WIN_RE), _side(m.group("y"), tail=rx is _LOSE_RE)
            if x and y and not x & y:
                return x, y
    return None


def _result_relation(a: str, b: str, time_a, time_b, pa: "Profile", pb: "Profile") -> str | None:
    if pa.neg != pb.neg or _times_apart(time_a, time_b):
        return None
    if pa.years and pb.years and not pa.years & pb.years:
        return None
    ra, rb = result_of(a), result_of(b)
    if not ra or not rb:
        return None
    if ra == (rb[1], rb[0]):
        return "different"                    # the same two sides, opposite results
    if ra != rb:
        return None
    # the same two sides in two different contests (a semi-final and a final, hockey and cricket): not one result
    for dim in _EVENT_DIMS:
        ea, eb = pa.roots & dim, pb.roots & dim
        if ea and eb and not ea & eb:
            return None
    na, nb = _score_nums(a), _score_nums(b)
    if na == nb:
        return "same"
    if na <= nb:
        return "b_covers_a"
    if nb <= na:
        return "a_covers_b"
    return None


def time_gap_days(x: dict | None, y: dict | None) -> int | None:
    """S9: the whole days between two statements' time ranges (0 = they overlap or touch, None = not both dated)."""
    try:
        if not x or not y or not (x.get("start") and y.get("start")):
            return None
        d = lambda t: dt.date.fromisoformat(str(t)[:10])  # noqa: E731
        xs, xe = d(x["start"]), d(x.get("end") or x["start"])
        ys, ye = d(y["start"]), d(y.get("end") or y["start"])
        return max((ys - xe).days, (xs - ye).days, 0)
    except (TypeError, ValueError):
        return None


ADJACENT_DAYS = 1       # two lines whose days are this close and whose words are the same are ASKED about, not vetoed


def _relate(a: str, b: str, time_a, time_b, pa: Profile, pb: Profile) -> str:
    if pa.neg != pb.neg:
        return "different"
    if not _times_apart(time_a, time_b):
        return _relate_core(a, b, pa, pb)
    # S9: time is a soft level, not a veto over identical text. Days that are one apart for the same words (a stampede
    # "on Saturday" in one report, "on Sunday" in another) go to the twice-asked question, never to a merge by code;
    # anything further apart, or worded differently, is a different event, as before.
    gap = time_gap_days(time_a, time_b)
    shared = pa.names & pb.names
    alike = pa.nums == pb.nums and pa.names == pb.names and (
        pa.norm == pb.norm or _share(pa.roots - shared, pb.roots - shared) >= SAME_WORDS)
    if gap is None or gap > ADJACENT_DAYS or not alike:
        return "different"
    r = _relate_core(a, b, pa, pb)
    return {"same": "ask", "a_covers_b": "ask_a_covers_b", "b_covers_a": "ask_b_covers_a"}.get(r, r)


def _relate_core(a: str, b: str, pa: Profile, pb: Profile) -> str:
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


BLOCK_MIN = 120          # a story with fewer statements than this is compared exhaustively
BLOCK_K = 12             # nearest neighbours by sentence embedding
RARE_NAME = 6            # a name or figure shared by at most this many statements links them


def blocks(texts: dict[int, str], prof: dict) -> set[tuple[int, int]]:
    """S7, BLOCKING: the pairs worth comparing, instead of every pair. A pair is a candidate when either is among the other's
    BLOCK_K nearest by multilingual sentence embedding (TF-IDF when no model is loaded), or they share a figure or a
    name few statements have. All pairs when the story is small. Everything outside the blocks was never close to anything
    the comparison could call the same: it is skipped, not judged different."""
    ids = sorted(texts)
    if len(ids) <= BLOCK_MIN:
        return {(a, b) for k, a in enumerate(ids) for b in ids[k + 1:]}
    out: set[tuple[int, int]] = set()
    try:
        from . import embed
        v, _how = embed.vectors([texts[i] for i in ids])
        sim = v @ v.T
        for r, a in enumerate(ids):
            sim[r, r] = -1.0
            for c in sim[r].argsort()[::-1][:BLOCK_K]:
                b = ids[int(c)]
                out.add((a, b) if a < b else (b, a))
    except Exception:
        pass
    index: dict = {}
    for i in ids:
        for key in {("n", x) for x in prof[i].nums} | {("w", x) for x in prof[i].names}:
            index.setdefault(key, []).append(i)
    for members in index.values():
        if len(members) <= RARE_NAME:
            out |= {(a, b) for k, a in enumerate(members) for b in members[k + 1:]}
    return out


def group(texts: dict[int, str], times: dict[int, dict | None] | None = None, asked: dict | None = None
          ) -> tuple[list[tuple[int, int]], dict[int, int], list[tuple[int, int]], list[tuple[int, int]]]:
    """For a story's statements {id: text}: (pairs that are the same, {covered id: covering id}, pairs
    to ask "same?", pairs (detailed, short) to ask "covers?"). Code only; the caller asks the model."""
    times = times or {}
    prof = {i: Profile(t) for i, t in texts.items()}
    ids = sorted(texts)
    same, covered, ask, ask_cover = [], {}, [], []
    cand = blocks(texts, prof)
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            if (a, b) not in cand:
                continue
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


# --- pairs the word rules call "different" only because of names or words (merge_audit, Oct 26 2026) -----------------------
# "Modi congratulated Lula on his re-election" / "Modi congratulated Brazilian President Lula on his electoral victory": the
# second line adds a title and a demonym, so the NAME sets differ and the code's veto ended it, though the model reads the
# two as the same fact (0.99 both ways). Code keeps every veto about FACTS (negation, figures, dates, clock times, results);
# a difference only in names or words, where one line has names the other lacks (not both, which is two different people),
# is offered to the local reader (NLI), which decides.
def core_names(p: "Profile") -> frozenset:
    """Names without title words and demonym forms ("senator", "president", "brazilian" next to "brazil")."""
    try:
        from .titles import title_words
        tw = {_stem(w.lower()) for w in title_words()}
    except Exception:  # noqa: BLE001
        tw = set()
    names = {n for n in p.names if n not in tw}
    return frozenset(names)


def _names_match(x: str, y: str) -> bool:
    return x == y or (min(len(x), len(y)) >= 5 and (x.startswith(y) or y.startswith(x)))


def name_sets_fit(pa: "Profile", pb: "Profile") -> bool:
    """True when the names of the two lines do not name two different things: what one line has and the other lacks
    is on one side only."""
    na, nb = core_names(pa), core_names(pb)
    only_a = {x for x in na if not any(_names_match(x, y) for y in nb)}
    only_b = {y for y in nb if not any(_names_match(x, y) for x in na)}
    return not (only_a and only_b)


def soft_candidate(a: str, b: str, time_a: dict | None = None, time_b: dict | None = None,
                   pa: "Profile | None" = None, pb: "Profile | None" = None) -> bool:
    """Is a pair code called "different" worth the model's look? Only when no fact differs: same negation, nothing
    dated apart, no clock or year conflict, figures equal or on one side only, and the names fit (one-sided)."""
    pa, pb = pa or Profile(a), pb or Profile(b)
    if pa.neg != pb.neg or (pa.clocks and pb.clocks and not pa.clocks & pb.clocks):
        return False
    if pa.years and pb.years and not pa.years & pb.years:
        return False
    if pa.date and pb.date and any(x is not None and y is not None and x != y for x, y in zip(pa.date, pb.date)):
        return False
    if _times_apart(time_a, time_b) and time_gap_days(time_a, time_b) not in (None, 0, 1):
        return False
    if not (pa.nums <= pb.nums or pb.nums <= pa.nums):
        return False
    return name_sets_fit(pa, pb)

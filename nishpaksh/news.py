"""The news of a story: chosen once, by code; the lead and the headline are written from it (owner, Oct 8 2026).

Before, the headline was written twice (a draft before the article, keyed to an importance call that
was re-asked whenever the draft changed, and again from the article's lead), up to seven calls a try, and
the writer chose its lead freely: "India Block leaders held a protest" led the story of Rahul and
Priyanka Gandhi's detention, "the court heard the petition" led the order it made. Headlines asked for
"reportedly" on everything not yet green, which at writing time is almost everything.

Now:
  1. pick_news (code, no call): the statement that makes this news today. Candidates: the story's own
     statements (not background or context) carried by 2+ independent outlets (else the best carried).
     Ranked: recent (within 2 days of the newest dated one) > a decisive act (arrested, ordered, killed,
     signed, resigned...) over process or setting (held, met, spoke, heard, began) > outlets > reports.
     A disputed statement can be the news (owner, Oct 8 2026: the article gives the clarity); its
     headline must not take a side.
  2. The writer's lead must cite it (narrative.py checks; the news fill rewrites a lead that does not).
  3. The headline: one call writes three candidates from the news and the lead; code rejects the
     wrong ones (numbers and names not in the statements, who-did-what, cause words, loaded words, any
     hedge, a disputed figure stated as fact) and scores the rest on what makes a good headline:
     the outcome, not the process; one concrete detail; a known name or a role; 7-12 words; no jargon.
     A second call only when all three fail. House style by code (PM, CJI, CM).
"""
from __future__ import annotations

import datetime as dt
import logging
import re

from . import clock
from .router import QuotaExhausted, Router

log = logging.getLogger(__name__)

RECENT = dt.timedelta(days=1)


def _start(i: dict) -> dt.datetime | None:
    s = (i.get("time") or {}).get("start")
    try:
        return dt.datetime.fromisoformat(s).replace(tzinfo=None) if s else None
    except (TypeError, ValueError):
        return None


PAST = re.compile(r"(?i)\b(previously|earlier|formerly|last (?:year|month|week)|had \w+(?:ed|en)|in the past)\b")


def act_score(text: str) -> int:
    """3 for deaths, 2 for another decisive act, -1 for routine activity or what did NOT happen, else 0 (events.py: by
    meaning, zero-shot NLI)."""
    from . import events
    return events.act_score(text)


def _outlets(i: dict) -> set[str]:
    return {s.get("outlet") for s in i.get("sources") or [] if s.get("outlet")} or {f"#{i['id']}"}


def _same_act(pi, pj) -> bool:
    """Two lines with the same decisive verb tell the same act in other words when they share a number, or a
    name AND most of the smaller line's words. A shared name alone was too loose (Oct 9 2026, story 13792: every
    "the GST Council approved ..." line borrowed every other's outlets, all tied, and a vague one-outlet line led)."""
    small = min(len(pi.roots), len(pj.roots)) or 1
    return bool(pi.nums & pj.nums) or bool(pi.names & pj.names and len(pi.roots & pj.roots) >= 0.5 * small)


def pick_news(items: list[dict], titles: list[str] | None = None) -> list[int]:
    return _pick(items, titles)[0]


def _title_words(text: str) -> set[str]:
    from .relate import Profile
    p = Profile(text or "")
    return set(p.roots) | {w.lower() for n in p.names for w in str(n).split()}


def head_support(items: list[dict], titles: list[str] | None) -> dict[int, int]:
    """For each statement, how many of the outlets' own headlines share 2+ content words with it. The headlines are what the
    outlets themselves say the story is; a statement no headline echoes is setting or detail, not the news (Oct 27 2026,
    story 46081: a rainfall figure folded from four outlets led a story whose seven headlines all said "4 districts declared
    drought-hit"). Empty when fewer than 2 headlines can be read (e.g. Hindi only)."""
    words = [w for w in (_title_words(t) for t in titles or []) if len(w) >= 2]
    if len(words) < 2:
        return {}
    out = {}
    for i in items:
        iw = _title_words(i.get("text") or "")
        out[i["id"]] = sum(1 for w in words if len(w & iw) >= 2)
    return out


def lead_news(items: list[dict], titles: list[str] | None = None) -> list[int]:
    """The facts the lead is written from: the news, and the fact of the day when it is a different one."""
    out, today = _pick(items, titles)
    return out[:1] + ([today] if today is not None else [])


def _pick(items: list[dict], titles: list[str] | None = None) -> tuple[list[int], int | None]:
    """The ids of the news, best first (the first is THE news). Code only. Ranked:
      not old    never told as the past ("previously", an older year)
      2 outlets  a fact two or more outlets tell over a one-outlet line, whatever its verb
      act        a decisive act over process or setting
      carried    how many outlets tell this act: the statement's own outlets (folded lines' included,
                 compose.fold_covered runs first) and those of statements telling the same act in other words
                 (same decisive verb, a shared name or number, same day): one detention told three ways by
                 three outlets is three outlets (Oct 8 2026, story 14729). Before "recent" since Oct 9 2026
                 (owner; story 13792: a vague one-outlet line dated today beat the arrest-power decision three
                 outlets carried)
      recent     dated on the story's newest day or the day before; then undated
      central    how many of the story's statements share its subject (2+ root words)
      concrete   names and numbers in it
    """
    from .relate import Profile
    core = [i for i in items if (i.get("role") or "core") == "core" and i.get("kind") in ("event", "claim")
            and i.get("verdict") != "false"]
    if not core:
        return [], None
    prof = {i["id"]: Profile(i["text"]) for i in core}
    hs = head_support(core, titles)
    hmax = max(hs.values(), default=0)

    def topical(i) -> bool:
        """Echoed by at least half as many headlines as the most echoed statement (all pass when headlines say too little)."""
        return hmax < 2 or hs.get(i["id"], 0) >= (hmax + 1) // 2
    from . import events
    verbs = {i["id"]: ({events.verb_lemma(i["text"])} - {None}) for i in core}
    dates = [d for d in (_start(i) for i in core) if d]
    newest = max(dates).date() if dates else None

    def day(i):
        d = _start(i)
        return d.date() if d else None

    def carried(i) -> int:
        out = set(_outlets(i))
        for j in core:
            if j is i or not verbs[i["id"]] & verbs[j["id"]]:
                continue
            if day(i) and day(j) and day(i) != day(j):
                continue
            if _same_act(prof[i["id"]], prof[j["id"]]):
                out |= _outlets(j)
        return len(out)

    def central(i) -> int:
        r = prof[i["id"]].roots
        return sum(1 for j in core if j is not i and len(r & prof[j["id"]].roots) >= 2)

    def key(i):
        d = day(i)
        # 2: dated on the story's newest day or the day before; 1: undated; 0: older, or told as the past
        # ("previously", "had announced", an older year: "the 2023 murder")
        recent = 1 if d is None or newest is None else 2 if newest - d <= RECENT else 0
        years = [int(y) for y in re.findall(r"\b(?:19|20)\d\d\b", i["text"])]
        if PAST.search(i["text"]) or (years and newest and max(years) < newest.year):
            recent = 0
        c = carried(i)
        p = prof[i["id"]]
        # one outlet's line never leads over a fact two or more outlets tell (Oct 9 2026, story 13058: "Nana
        # Patekar ... won millions of hearts", one outlet, led a story four outlets told; "won" read as an act)
        return (recent > 0, topical(i), min(c, 2), act_score(i["text"]), c, recent, central(i), len(p.names) + len(p.nums),
                i.get("n_articles") or 0, -i["id"])
    ranked = sorted(core, key=key, reverse=True)
    out = [i["id"] for i in ranked]
    # the lead may carry two facts (owner, Oct 9 2026): the best-reported one, and, if that is not today's,
    # the best fact dated on the story's newest day, unless it tells the same act in other words
    first, today = ranked[0], None
    if newest is not None and day(first) != newest:
        def same_act(j) -> bool:
            return bool(verbs[first["id"]] & verbs[j["id"]]) and _same_act(prof[first["id"]], prof[j["id"]])
        today = next((j for j in ranked[1:] if day(j) == newest and key(j)[:3] >= key(first)[:3] and act_score(j["text"]) > 0
                      and not same_act(j)), None)
        if today is not None:
            out.remove(today["id"])
            out.insert(1, today["id"])
    return out, (today["id"] if today is not None else None)


# ------------------------------------------------------------------------------------------- headline

HEADLINE_PROMPT = """{now}Write SIX different headlines for this news story, for a reader who has never heard of it.
Each: at most 12 words, plain English, sentence case (capital letters only for names). A good headline tells
the outcome and the one detail that makes it matter, so the reader wants the article. "Who did what" alone is
not enough, and a vague noun ("changes", "concerns", "measures") never beats the figure, the place or the number affected.

The six lead with different things:
A. THE OUTCOME: what changed, ended or was decided, and for whom.
B. THE DETAIL: the one specific, surprising or human fact in the statements (an amount, a place, a contrast).
C. THE STAKES: who is affected, or what is now at risk or unsettled, said as a plain statement.
D. LABEL: DEVELOPMENT: a short label for the story, a colon, then what happened
   ("Seemapuri collapse: police count 40 dead, families say 50").
E. THE WORDS: the speaker, a colon, and their exact words in quotation marks, copied letter for letter from the QUOTES
   below ("Rahul Gandhi: 'Every FIR a medal'"). If no QUOTES are given, write a second outcome headline instead.
F. YOUR OWN ANGLE: what would make a reader open the article that A to E did not say.

Rules:
1. About TODAY: headline the newest development ({newest}), in the present tense with an active verb
   ("orders", "detains", "rejects"). Never an old event as news: no "earlier", "previously", "last year", no "had".
2. A name alone is not a headline. A reader who does not know the person must be told who they are: a role,
   a trade or a town ("Delhi schoolteacher", "IIT Bombay student", "Gujarat police"), or open with the event and
   put the name later. Only names every Indian knows (PM Modi, Rahul Gandhi, Virat Kohli) may open a headline.
3. Say it, do not tease it: no questions, no "what we know", "here's why", "explained", "shocking", no
   exclamation marks, no judging words.
4. Only what the statements say: no number, name or cause ("due to", "amid", "because") that is not in them.
   Never "reportedly", "reports say". Use a figure only when it carries the story (a toll, an amount, a deadline).
5. Short words, no jargon, no abbreviation a reader may not know.
5b. Tense comes from NOW and the date of the newest development: happened today or yesterday -> present tense
   (\"declines\"); not yet happened (dated after NOW) -> future (\"to hear\", \"will\"), never present or past; a
   development of several days ago is not today's headline unless it is all the statements carry, then simple past.
   Never \"had\" or \"has / have\" for a plain event.
{dispute}
Weak -> strong:
- "India Block leaders hold protest near Jantar Mantar" (the setting)
  -> "Police detain Rahul, Priyanka Gandhi at Jantar Mantar protest"
- "Ramesh Kumar produced before court" (a name nobody knows, no reason)
  -> "Kotdwar gym trainer who defended shopkeeper is produced before court"
- "Supreme Court hears Jahangirpuri petition" (the process)
  -> "Supreme Court stops demolition of 200 Jahangirpuri homes"
- "Sahil Wakode found dead" (a name nobody knows)
  -> "IIT Bombay first-year student found dead in hostel room"
- "RBI announces monetary policy decision" (says nothing)
  -> "RBI hikes repo rate to 6.75%, raising home loan EMIs"
- "Defence contract signed under Buy Indian IDDM category" (jargon, no buyer, no amount)
  -> "Defence Ministry signs Rs 661.50 crore deal for BrahMos launchers"
- police put a toll at 40 and families at 50: "Building collapse kills 40" (takes a side)
  -> "Seemapuri collapse: police count 40 dead, families say 50"
{thread}{taken}{outlets}{quotes}
THE NEWS: {news}{news_when}
{latest}The article opens: {lead}
Other statements (for one detail, if needed):
{others}

Reply with JSON only: {{"headlines": ["A...", "B...", "C...", "D...", "E...", "F..."]}}"""

LATEST_NOTE = "LATEST (the newest development, headline THIS one): {latest}\n"

DISPUTE_NOTE = """6. THE NEWS is disputed: {versions}. Do not state either version as fact: say whose it is ("police
   say ..."), or leave the disputed detail out."""

TAKEN_NOTE = """
HEADLINES ALREADY PUBLISHED (owner, Oct 13 2026: follow-ups and later stories repeated them). Yours must NOT repeat
or reword any of them, not even with another verb (\"opens\" for \"inaugurates\"). Say what THIS article adds that they
do not: the new step, figure, person, place, reaction or consequence. Take it from the statements above.
{lines}
"""

TAKEN_MAX = 6          # headlines shown to the model (the closest ones; the story's parents always)
REPEAT_SHARED = 4      # a headline repeats an earlier one when it shares this many content words and half of the
REPEAT_RATIO = 0.5     # shorter headline's, or 3 words and three quarters (REPEAT_CLOSE) of them
REPEAT_CLOSE = 0.75
_FILLER = {"that", "this", "than", "who", "will", "not", "are", "was", "were", "has", "have", "been", "says", "said"}


def _sig(text: str) -> frozenset[str]:
    """The content words of a headline, stemmed (so 'shuts' and 'shut' match); numbers count."""
    from .frames import _stem
    return frozenset(_stem(w) for w in re.findall(r"[a-z]+|\d+", (text or "").lower())
                     if (len(w) > 2 or w.isdigit()) and w not in STOP and w not in _FILLER)


def overlap(a: str, b: str) -> tuple[int, float]:
    """(content words shared, their share of the shorter headline) for two headlines."""
    sa, sb = _sig(a), _sig(b)
    if not sa or not sb:
        return 0, 0.0
    shared = len(sa & sb)
    return shared, shared / min(len(sa), len(sb))


def repeats(h: str, taken: list[str]) -> str | None:
    """The earlier headline `h` repeats (same words, maybe another verb), or None."""
    best, best_ratio = None, 0.0
    for t in taken:
        shared, ratio = overlap(h, t)
        close = (shared >= REPEAT_SHARED and ratio >= REPEAT_RATIO) or (shared >= 3 and ratio >= REPEAT_CLOSE)
        if close and ratio > best_ratio:
            best, best_ratio = t, ratio
    return best


def closest_taken(taken: list[str], text: str, parents: list[str] = ()) -> list[str]:
    """The headlines worth showing the model: the story's parents, then the published ones that share the most
    words with this article's news. Duplicates dropped."""
    out: list[str] = []
    for t in list(parents) + sorted((t for t in taken if overlap(t, text)[0] >= 2), key=lambda t: -overlap(t, text)[0]):
        if t and t not in out:
            out.append(t)
    return out[:TAKEN_MAX]


LINKS = ("due to", "amid", "because", "as a result", "triggered", "led to")
HEDGE = re.compile(r"(?i)\b(reportedly|reports? (?:say|says|said|emerge|suggest|indicate|claim)|according to reports?|"
                   r"it is reported)\b|,?\s*allegedly\s*$")
ATTRIBUTION = re.compile(r"(?i)\b(say|says|said|claim|claims|alleg\w*|accus\w*|den(?:y|ies|ied)|disput\w*|"
                         r"according to|versus|vs)\b")
KNOWN_ABBR = {"PM", "CM", "CJI", "BJP", "AAP", "RSS", "ISRO", "IIT", "IIM", "AIIMS", "NEET", "UPSC", "CBI", "ED",
              "NIA", "UN", "US", "UK", "UAE", "GST", "RBI", "IPL", "FIR", "MP", "MLA", "MLAs", "MPs", "NDA",
              "SC", "HC", "IAS", "IPS", "CRPF", "BSF", "NCR", "TMC", "DMK", "SP", "BSP", "JDU", "RJD", "NCP",
              "LoC", "LAC", "ICC", "BCCI", "NATO", "AI", "IMF", "WHO", "EU", "ODI", "T20", "JNU", "DU", "Rs"}
TITLES = [(re.compile(r"\bPrime Minister\b"), "PM"), (re.compile(r"\bChief Justice of India\b"), "CJI"),
          (re.compile(r"\bChief Minister\b"), "CM"), (re.compile(r"\bPM Narendra Modi\b"), "PM Modi")]
STOP = {"the", "and", "for", "with", "from", "over", "into", "after", "amid", "its", "his", "her", "their"}


def house_style(h: str) -> str:
    """Headline titles as Indian papers write them: 'PM Modi', 'CJI', 'CM'."""
    for pat, rep in TITLES:
        h = pat.sub(rep, h)
    return re.sub(r"\s+", " ", h).strip().rstrip(".")


def _names(text: str) -> set[str]:
    """Capitalised words after the first (names, places, bodies), lower-cased."""
    toks = re.findall(r"[A-Za-z][\w'-]*", text or "")
    return {re.sub(r"'s$", "", t.lower()) for t in toks[1:] if t[0].isupper() and t not in KNOWN_ABBR}


def _actor_problem(h: str, source: str) -> str | None:
    """Who did it must match the statements (Oct 2026: "FSSAI recalls Everest cumin powder" when the
    statements say FSSAI ORDERED the recall; Everest recalls). Checked for the headline's first verb in
    the present tense ("recalls", "arrests"): where the statements use that verb, someone named before
    it in the headline must be its actor there, not "the recall" ordered by them. A verb the
    statements never use (a paraphrase) is not judged here."""
    words = re.findall(r"[A-Za-z'&.-]+", h)
    for k, w in enumerate(words):
        if k == 0 or not re.fullmatch(r"[a-z]{3,}s", w) or w in ("was", "has", "is", "its", "his", "says"):
            continue
        stem = w[:-2] if w.endswith(("ches", "shes", "sses", "xes")) else w[:-1]
        subject = {x.lower().strip("'s.") for x in words[:k] if len(x) >= 3} - STOP
        forms = list(re.finditer(rf"\b{re.escape(stem.lower())}(?:s|es|ed|d|ing)?\b", source))
        if not forms or not subject:
            return None
        for m in forms:
            before = re.findall(r"[a-z'&.-]+", source[max(0, m.start() - 60):m.start()])[-4:]
            if before and before[-1] in ("the", "a", "an", "its", "his", "her", "their"):
                continue   # "ordered the recall": a noun, someone else's action on it
            if subject & {b.strip("'s.") for b in before}:
                return None
        m = forms[0]
        snippet = source[max(0, m.start() - 50):m.end() + 30].strip()
        return f"it says '{' '.join(words[:k + 1])}', but the statements say \"...{snippet}...\": keep who did what"
    return None


WEAK = re.compile(r"(?i)\b(what we know|here(?:'s| is| are)|all you need|explained|explainer|you won'?t believe|"
                  r"shocking|must[- ]see|breaking(?: news|:)|live updates?|everything (?:you|to)|key takeaways?|know about|"
                  r"how to)\b|[?!]")


def known_names() -> tuple[set[str], set[str]]:
    """(full names, surnames that belong to ONE known name) from config/known_names.yaml, lower case. \"Yadav\" or
    \"Gandhi\" alone does not make a name known: several known people share them."""
    try:
        from .config import load_yaml
        full = {str(n).lower() for n in (load_yaml("known_names.yaml") or {}).get("names") or []}
    except Exception:  # noqa: BLE001
        return set(), set()
    last = [n.split()[-1] for n in full if len(n.split()) > 1]
    return full, {x for x in last if last.count(x) == 1}


PERSON_VERBS = (r"(?:was|were|has been|have been|is|are)\s+(?:arrested|detained|found|booked|killed|injured|sentenced|"
                r"charged|produced|rescued|suspended|sacked|appointed|elected|shot|attacked|named|summoned|granted|denied)")


def _persons(facts: str) -> list[str]:
    """People named in the statements: those style.people proves (a title before, a speech verb after) and those
    the statements introduce the way a paper introduces a stranger: \"Sahil Wakode, 21,\" / \"Sahil Wakode, a
    first-year student\" / \"Sahil Wakode was found dead\"."""
    from . import style
    out = list(style.people(facts))
    for name in sorted(style._candidates(facts)):
        e = re.escape(name)
        if name not in out and (re.search(rf"\b{e}\s*,\s*(?:\d{{1,2}}\b|(?:a|an|the)\s)", facts)
                                or re.search(rf"\b{e}\s+{PERSON_VERBS}\b", facts)):
            out.append(name)
    return out


def _opening_name_problem(h: str, facts: str) -> str | None:
    """A headline may not OPEN with the name of a person readers do not know (owner, Oct 12 2026: \"a lot of the
    time the headline is just a person's name and what happened to them, and we do not know that person\").
    Only a name the statements show to be a PERSON counts (a title or role before it, a speech verb after it:
    style.people), and a role written before it in the headline is fine (\"Actor Rajpal Yadav ...\")."""
    if not facts:
        return None
    from . import style
    words = [re.sub(r"(?:'s|\u2019s)$", "", w) for w in re.findall(r"[A-Za-z][\w'\u2019.-]*", h)]
    full_known, surnames = known_names()
    for full in _persons(facts):
        parts = full.split()
        by_surname = bool(words) and words[0] == parts[-1]
        if words[:len(parts)] != parts and not by_surname:
            continue
        if full.lower() in full_known or (by_surname and parts[-1].lower() in surnames):
            continue
        role = ""
        m = re.search(rf"\b([A-Za-z]+)\s+{re.escape(full)}\b", facts)
        if m and m.group(1).lower() in style.ROLES_LOWER:
            role = f" ({m.group(1).lower()})"
        return (f"it opens with '{full}', a name most readers do not know: say who they are first{role}, "
                f"or open with what happened")
    return None


_QUOTED = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d')


def loaded_hit(h: str, banned) -> str | None:
    """The first loaded word the headline uses outside quotation marks (a quoted word is the speaker's, as in the article), or None."""
    low = _QUOTED.sub(" ", h or "").lower()
    for w in sorted(banned):
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low):
            return w
    return None


def freed_words(banned, texts) -> tuple[set[str], list[str]]:
    """(the loaded words still banned, the ones freed): a word the story's own statements use is the story's word, not
    loaded for it (the article writer already does the same, narrative._context). Any fault leaves the full set."""
    try:
        used = " ".join(t for t in texts if t).lower()
        freed = sorted(w for w in banned if re.search(rf"(?<!\w){re.escape(w.lower())}(?!\w)", used))
        return {w for w in banned if w not in freed}, freed
    except Exception:  # noqa: BLE001
        return set(banned), []


def headline_problem(h: str, source: str, banned: set[str], disputed: set[str] = frozenset(),
                     facts: str = "") -> str | None:
    """What is wrong with a headline, or None. `source` is every statement it may draw on (lower case);
    `disputed` the answers (numbers, names) the sources disagree on; `facts` the same statements in their own
    case (to tell a person's name from a place)."""
    low = h.lower()
    if not h or len(h.split()) > 12:
        return "it must be at most 12 words"
    if WEAK.search(h):
        return "say the news plainly: no question, exclamation, 'what we know', 'explained' or 'shocking'"
    if PAST.search(h):
        return "it points to the past ('earlier', 'previously', 'had ...'): headline what is new today"
    if HEDGE.search(h):
        return "no 'reportedly' or 'reports say': state the news, or say whose claim it is"
    m = re.match(r"([A-Z][a-z]+)\s+(was|is|has|had|gets|got|were)\b", h)
    if m and m.group(1).lower() not in ("police", "court", "government", "centre", "parliament", "army"):
        return f"it starts with a bare name ('{m.group(1)}'); introduce the person by who they are"
    unknown = _opening_name_problem(h, facts)
    if unknown:
        return unknown
    hit = loaded_hit(h, banned)
    if hit:
        return f"it uses a loaded word ('{hit}'): say it plainly"
    bad = [l for l in LINKS if re.search(rf"\b{l}\b", low) and l not in source]
    if bad:
        return f"it links events with '{bad[0]}', which no statement does"
    from . import figures
    if not figures.value_set(h, spoken_min=figures.SPOKEN_MIN) <= figures.value_set(source):
        return "it has a number that is not in the statements"
    words = h.split()
    if sum(w[0].isupper() for w in words if w[0].isalpha()) < 0.7 * len(words):   # not Title Case
        stray = [n for n in _names(house_style(h)) if n not in source and len(n) > 2]
        if stray:
            return f"it names '{stray[0]}', which no statement does"
    if disputed and not ATTRIBUTION.search(h):
        hit = [d for d in disputed if re.search(rf"(?<![\w.]){re.escape(d)}(?![\w.])", low)]
        if hit:
            return f"'{hit[0]}' is disputed: say whose version it is, or leave it out"
    return _actor_problem(h, source)


def headline_score(h: str, news: str, latest: str = "", cons: dict | None = None, recent=()) -> float:
    """How good a correct headline is, on what makes one good (owner, Oct 8 2026). `latest`: the newest
    development when the lead carries one besides the news (a headline about it is today's, owner Oct 12 2026).
    `cons` (headlinekit.consensus: the words most outlets' headlines share) and `recent` (the latest published headlines)
    switch on the Oct 30 2026 scorer: the headline is rewarded for carrying what the outlets lead with, not for copying the
    news statement's words, and loses a little for a shape and verb the last 40 headlines already used."""
    score = 0.0
    n = len(h.split())
    score += 1 if 7 <= n <= 12 else 0
    score += {3: 2, 2: 2, 0: 0, -1: -2}[act_score(h)]              # the outcome, not the process
    concrete = bool(re.search(r"\d", h)) or bool(_names(h) & _names(news))
    score += 2 if concrete else 0                                   # one concrete detail
    from .frames import _stem
    nw = {_stem(w) for w in re.findall(r"[a-z]{4,}", news.lower())}
    hw = {_stem(w) for w in re.findall(r"[a-z]{4,}", h.lower())}
    if cons:
        from . import headlinekit as kit
        score += 4.0 * kit.coverage(h, cons)                       # it carries what the outlets lead with
        score += 1.5 if kit.has_figure(h, cons) else 0             # ... above all the figure they headline
        score += 0.5 if re.search(r":\s", h) and len(h.split(":", 1)[1].split()) >= 2 else 0   # label: development
        score -= min(1.0, 0.34 * kit.repetition(h, recent))        # not the shape and verb of the last headlines
    else:
        score += 1 if nw and len(hw & nw) >= 0.5 * len(nw) else 0  # it is about the news
    facts = (1 if act_score(h) >= 2 else 0) + len(re.findall(r"\d+|\b(?:two|three|four|five|six|seven|eight|nine|ten)\b", h))
    score += min(1.0, 0.5 * max(0, facts - 1))                      # more of the news in the same words
    if latest:                                                      # about the newest development
        lw = {_stem(w) for w in re.findall(r"[a-z]{4,}", latest.lower())}
        score += 1.5 if len(hw & lw) >= 2 else 0
    score += 0.5 if re.search(r"(?i):\s|\b(?:but|while|without|yet)\b", h) else 0   # a contrast makes the reader ask
    jargon = [t for t in re.findall(r"\b[A-Z]{3,}\b", h) if t not in KNOWN_ABBR]
    score -= len(jargon)                                            # no unexplained abbreviations
    return score


def _disputed_answers(news: dict, items: dict[int, dict]) -> tuple[set[str], str]:
    """The numbers (and names) on which the news statement and what contradicts it differ, and a line
    for the prompt saying the versions."""
    from .relate import Profile
    rivals = [items[x] for x in news.get("conflicts_with") or [] if x in items]
    answers: set[str] = set()
    for nm in news.get("name_conflict") or []:
        answers.add(str(nm).lower())
    if not rivals and not answers:
        return set(), ""
    mine = Profile(news["text"]).nums
    for r in rivals:
        theirs = Profile(r["text"]).nums
        for x in mine ^ theirs:
            answers.add(f"{x:g}")
    versions = "; ".join([f'"{news["text"]}"'] + [f'"{r["text"]}"' for r in rivals[:2]])
    if news.get("name_conflict"):
        versions += "; the reports name " + " / ".join(news["name_conflict"])
    return answers, versions


HEADLINE_STATS: dict = {}     # what the last write_headline saw and chose (compose records it in the dossier: the data to tune from)


def headline_record() -> dict:
    """The last headline's tuning data, trimmed for the ledger (ids are added by the caller)."""
    h = dict(HEADLINE_STATS)
    h["outlets"] = [{k: v for k, v in o.items() if k != "t"} for o in (h.get("outlets") or [])[:8]]
    h["cands"] = (h.get("cands") or [])[:4]
    return h


def write_headline(router: Router | None, news: dict, items: dict[int, dict], lead: str, banned: set[str],
                   thread: str = "", latest: dict | None = None, taken: list[str] = (),
                   parents: list[str] = (), titles=(), background=()) -> str | None:
    """The best correct headline of six, or None (the article waits as a kept draft). `latest`: the fact of the
    day when the lead carries a second one (`lead_news`); the headline is then about it.
    `taken`: headlines already published (a headline too close to one is not used while a fresh one exists);
    `parents`: the headlines of the stories this one develops (always shown to the model);
    `titles`: the outlets' own English headlines of the story ({"outlet", "title"} or plain strings; headlinekit reads them:
    what they share is what the headline should carry, they are shown to the model, and none may be copied). One model call
    as before; headlinekit is code and any fault in it leaves the old prompt and the old scoring."""
    if router is None or not news:
        return None
    if latest is not None and latest.get("id") == news.get("id"):
        latest = None
    others = [i for i in items.values() if i["id"] != news["id"] and (i.get("role") or "core") == "core"]
    others.sort(key=lambda i: -(i.get("n_sources") or 0))
    others = others[:6]
    texts = [news["text"], lead] + ([latest["text"]] if latest else []) + [i["text"] for i in others]
    facts = " ".join(texts)
    source = facts.lower()
    latest_text = latest["text"] if latest else ""
    disputed, versions = _disputed_answers(news, items)
    banned, freed = freed_words(banned, texts + [i["text"] for i in items.values()] + list(background or ()))
    taken = [t for t in dict.fromkeys(list(parents) + list(taken)) if t]
    shown = closest_taken(taken, f"{news['text']} {lead}", parents)
    taken_note = TAKEN_NOTE.format(lines="\n".join(f"- {t}" for t in shown)) if shown else ""
    ctx = f"\nThis is a new development in an ongoing story ({thread}): headline the NEW development.\n" if thread else ""
    ago = clock.relative(((latest or news).get("time") or {}).get("start"))
    from . import headlinekit as kit
    pool = [news] + ([latest] if latest else []) + others + [i for i in items.values() if i not in others and i is not news]
    market = kit.evaluate(titles, reference=lead or news["text"])     # every outlet headline, both languages, on one scale
    HEADLINE_STATS.clear()
    HEADLINE_STATS.update({"v": 1, "voices": len(market["all"]), "weights": kit.WEIGHTS, "calls": 0, "retried": False,
                           "outlets": [{"o": r["outlet"], "q": round(r["q"], 3), "c": r.get("c"), "hi": bool(re.search("[\u0900-\u097F]", r["title"])),
                                        "t": r["title"][:90]} for r in market["all"][:12]],
                           "seeds": [round(r["q"], 3) for r in market["seeds"]], "cands": [],
                           "loaded": {"banned": sorted(banned)[:20], "freed": freed[:20]}})
    kb = kit.blocks(titles, pool, market["seeds"])   # {} / "" everywhere when it cannot read anything: the old prompt
    cons, quoted = kb["cons"], kb["quoted"]
    prompt = HEADLINE_PROMPT.format(
        now=clock.now_line().split("\n", 1)[0] + "\n\n", news_when=f" (dated: {ago})" if ago else "",
        dispute=DISPUTE_NOTE.format(versions=versions) if versions else "", thread=ctx, taken=taken_note, news=news["text"],
        newest="the one marked LATEST" if latest else "THE NEWS", latest=LATEST_NOTE.format(latest=latest_text) if latest else "",
        lead=lead or news["text"], others="\n".join(f"- {i['text']}" for i in others) or "- (none)",
        outlets=kb["outlets"], quotes=kb["quotes"])
    quote_facts = " ".join(i.get("text") or "" for i in pool)      # a quotation may come from any statement, not only the 8 shown
    tried: list[str] = []
    repeated: list[tuple[float, str]] = []     # correct headlines that repeat an earlier one

    def score(h: str, q: float = 0.0) -> float:
        try:
            return headline_score(h, news["text"], latest_text, cons=cons, recent=list(taken)) + 4.0 * q
        except Exception:  # noqa: BLE001 - a scoring fault never holds an article back: candidates tie, the model's first wins
            return 0.0

    def rank(hs: list[str]) -> list[tuple[float, str]]:
        """(score, headline) best first; q = the same embedding scale the outlets' headlines are on."""
        ev = kit.evaluate(titles, reference=lead or news["text"], candidates=hs) if market["seeds"] else {}
        qs = ev.get("cands") or []
        qs = qs if len(qs) == len(hs) else [0.0] * len(hs)
        cc = ev.get("cand_c") if len(ev.get("cand_c") or []) == len(hs) else [None] * len(hs)
        comps.update({h: c for h, c in zip(hs, cc)})
        return sorted(((score(h, qv), h, qv) for h, qv in zip(hs, qs)), key=lambda r: -r[0]), qs
    comps: dict = {}
    best_ours: list[tuple[float, str, float]] = []
    for attempt in range(2):          # a second call only when all candidates fail
        try:
            HEADLINE_STATS["calls"] += 1
            res = router.call("page", prompt, json_out=True, max_output_tokens=450)
        except (QuotaExhausted, Exception) as e:  # noqa: BLE001
            log.info("headline not written: %s", e)
            return None
        cands = (res.data or {}).get("headlines") if isinstance(res.data, dict) else None
        if isinstance(cands, str):
            cands = [cands]
        good, why = [], []
        for c in cands or []:
            h = house_style(str(c or "").strip().strip('"'))
            problem = headline_problem(h, source, banned, disputed, facts)
            if not problem:
                try:
                    problem = kit.quote_problem(h, quote_facts, quoted) or kit.copy_problem(h, titles)
                except Exception:  # noqa: BLE001 - the kit never blocks a headline by failing
                    problem = None
            if problem:
                why.append(f'"{h}": {problem}')
                continue
            twin = repeats(h, taken)
            if twin:       # correct, but it says what an earlier headline already said
                repeated.append((overlap(h, twin)[1], h))
                why.append(f'"{h}": it repeats the published headline "{twin}"; say what is NEW in this article')
            else:
                good.append(h)
        if good:
            ranked, _ = rank(good)
            best_ours = sorted(best_ours + ranked, key=lambda r: -r[0])
            top = best_ours[0]
            above = sum(1 for r in market["all"] if r["q"] > top[2])      # outlet headlines scoring above ours
            HEADLINE_STATS["cands"] += [{"h": r[1], "score": round(r[0], 2), "q": round(r[2], 3), "c": comps.get(r[1]), "round": attempt + 1}
                                        for r in ranked[:6]]
            HEADLINE_STATS.update({"rank": above + 1, "chosen_q": round(top[2], 3), "best_outlet_q": round(market["best"], 3)
                                   if market["best"] is not None else None})
            # ours is good enough when it is in the top TOP_N with the outlets'; below that one more call (never a third)
            if attempt == 1 or market["best"] is None or above < kit.TOP_N:
                log.info("headline q=%.2f rank %d of %d", top[2], above + 1, len(market["all"]) + 1)
                return top[1]
            HEADLINE_STATS["retried"] = True
            prompt += ("\n\nThese were correct but weaker than several outlets' headlines:\n"
                       + "\n".join(f"- {r[1]}" for r in best_ours[:3])
                       + "\nWrite six better ones: the core the outlets share plus the most specific fact, about THIS article's lead.")
            continue
        if best_ours:
            return best_ours[0][1]
        tried += why
        prompt += "\n\nThese were rejected:\n" + "\n".join(f"- {w}" for w in why[:3]) + "\nWrite new ones."
    if repeated:       # nothing fresh in two tries: the least repeated one beats holding the article back
        h = min(repeated, key=lambda r: (r[0], -score(r[1])))[1]
        log.info("headline repeats an earlier one, used anyway: %s", h)
        return h
    log.info("no headline passed (loaded words kept: %s; freed: %s): %s", sorted(banned)[:12], freed[:12], "; ".join(tried)[:400])
    return None

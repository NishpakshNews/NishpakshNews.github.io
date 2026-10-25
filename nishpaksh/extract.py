"""Stage 3: read each article with Gemma and record what it says, neutrally.

The model does no judging here. It transcribes events, claims, times, stated
relations and the emotive words the article used. Everything else is code.
"""
from __future__ import annotations

import datetime as dt
import collections
import logging
import re
import threading
import time
from zoneinfo import ZoneInfo

from .config import SETTINGS
from .frames import normalize as normalize_frame
from sqlalchemy import func
from .db import Store, articles, claims, delete, insert, select, stories, update, utcnow
from . import heavy
from . import evidence
from .router import CallFailed, QuotaExhausted, Router

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

STANCES = {"asserts", "attributes", "denies"}
POLARITIES = {"pos", "neg"}
CERTAINTIES = {"stated", "possible", "hypothetical"}
SCHEMA = collections.Counter()          # S1/E1: fields the model left out or got outside the allowed values, counted per run


def choice(value, allowed: set, field: str, default: str) -> str:
    """A closed-vocabulary field: the value if it is allowed, else `default` (counted, never silent)."""
    v = str(value).strip().lower() if isinstance(value, str) else value
    if v in allowed:
        return v
    SCHEMA[field + ("_missing" if value in (None, "") else "_invalid")] += 1
    return default
ROUNDUP = re.compile(r"(?i)\blive\b.*\bupdates?\b|\blive\s*(blog|updates?|news)\b|^live[:|\s]|\btop (news|headlines|stories)\b"
                     r"|\bnews (wrap|roundup|highlights|bulletin)\b|\bmorning brief\b|\bevening brief\b|\bnews live\b"
                     r"|लाइव|ताजा खबर|बड़ी खबरें|टॉप न्यूज|न्यूज़ अपडेट")
EVIDENCE = {"fir", "court_record", "official_data", "video", "official_statement",
            "named_witness", "unnamed_source", "none"}
PRECISION = {"exact", "hour", "part_of_day", "day", "week", "month", "year", "unknown"}
REL_TYPES = {"before", "caused"}
CONTEXT_TYPES = {"background", "related", "explanation", "reaction", "next"}

EXTRACT_PROMPT = """You are a careful annotator. You do not judge truth, take sides, or add facts.
You only record what THIS article says, in neutral language.

ARTICLE
Outlet: {outlet}
Published: {published} (India time)
Title: {title}
{part}Text:
\"\"\"{text}\"\"\"
{names}
Return ONE JSON object with exactly these keys:
{{
  "signature": "one neutral English sentence naming the core event: who, what, where",
  "events": [
    {{"id": "e1", "text": "...", "quote": "...", "src": [1], "words": "...", "when_text": "...", "start": "YYYY-MM-DDTHH:MM or null",
      "end": "YYYY-MM-DDTHH:MM or null", "precision": "exact|hour|part_of_day|day|week|month|unknown",
      "stance": "asserts|attributes|denies", "polarity": "pos|neg", "certainty": "stated|possible|hypothetical",
      "attributed_to": "...", "evidence": "...", "loaded_words": ["..."],
      "frame": {{"who": "...", "action": "...", "what": "...", "value": "...", "where": "...", "negated": false}}}}
  ],
  "claims": [
    {{"id": "c1", "text": "...", "quote": "...", "src": [1], "words": "...", "stance": "asserts|attributes|denies",
      "polarity": "pos|neg", "certainty": "stated|possible|hypothetical", "attributed_to": "...",
      "evidence": "...", "loaded_words": ["..."], "frame": {{"who": "...", "action": "...", "what": "...", "value": "...", "where": "...", "negated": false}}}}
  ],
  "relations": [
    {{"from": "e1", "to": "e2", "type": "before|caused", "stance": "asserts|attributes|denies", "attributed_to": "..."}}
  ],
  "context": [
    {{"id": "x1", "type": "background|related|explanation|reaction|next", "text": "...", "quote": "...", "src": [1], "words": "...", "event": "...",
      "when_text": "...", "start": "YYYY-MM-DDTHH:MM or null", "end": "YYYY-MM-DDTHH:MM or null",
      "precision": "exact|hour|part_of_day|day|week|month|unknown",
      "stance": "asserts|attributes|denies", "polarity": "pos|neg", "certainty": "stated|possible|hypothetical",
      "attributed_to": "...", "evidence": "...", "loaded_words": ["..."],
      "frame": {{"who": "...", "action": "...", "what": "...", "value": "...", "where": "...", "negated": false}}}}
  ]
}}

Definitions:
- events: things that happened (an action, an arrest, a statement being made, a death).
- claims: statements that are not events themselves: numbers, identities, motives, accusations,
  causes, official positions, background facts.
- relations: ONLY when the article explicitly says one event came before, or caused / was in
  response to, another. "from" is the earlier or causing event.

Rules:
1. Neutral wording. Describe actions with plain verbs (struck, said, arrested, died). Move every
   emotive or judging word (for example: lynched, mob, brutal, so-called, terrorist, provoked, clashed,
   hate, radical, thug, martyr) out of "text" and into "loaded_words", copied exactly as the article
   wrote it, in the article's own language.
2. Write "text" in English even when the article is in Hindi. Keep names as written, and name people
   in full with the role or title the article gives them ("AAP Delhi chief Saurabh Bharadwaj", not
   "Bharadwaj"), in every item, so each statement can be understood on its own.
   Translate faithfully, and keep each fact's wording tied to what the article says:
   a) A nickname or title the article puts in quotes is translated in FULL and never shortened
   ("प्रधानमंत्री अंबानी" is "Prime Minister Ambani", not "Prime Ambani").
   b) "said" and the speaker's name belong in "attributed_to", never inside the fact: write
   "Three companies have licences in India" (attributed_to "Scindia"), never "...licences in Scindia said".
   A place stays a place and a person stays a person.
   d) Keep every small word that limits a claim, exactly as the article has it: not, never, only (केवल, सिर्फ,
   महज), at least (कम से कम), up to, more than (से अधिक), directly (सीधे), alleged (कथित). Never add one the
   article does not have ("specific", "only", "about").
   c) Resolve "his", "her", "their", "he", "it" to the person or body the article means, by name: when a
   speaker talks about someone else's profit or business, write that person ("Ambani's business will not
   close"), not the speaker, and keep the speaker in "attributed_to".
3. Times: write the article's time words in English in "when_text" ("26 September", "Tuesday night"). Fill start/end ONLY when they follow from the
   text and the publish date (for example "Tuesday night" -> that Tuesday 18:00 to 23:59). Never guess.
   If unclear use null and precision "unknown".
4. stance: "asserts" = the article states it as fact in its own voice; "attributes" = the article reports
   that someone else says it; "denies" = the article says it did not happen or is untrue. For "denies",
   write "text" as the positive statement being denied (text "X insulted deities", stance "denies").
   An allegation, accusation, charge or claim that someone makes is ALWAYS "attributes" with that
   person as attributed_to, even when the article words it in its own voice (an article writing
   "the professor harassed the student" while reporting the family's complaint -> stance "attributes",
   attributed_to "the student's family"). Use "asserts" only for what the article itself establishes.
4a. src: the numbers of the article's numbered sentences ([1], [2] ...) this item was read from, as a list, e.g. [3] or
   [3, 4]. Only the sentences it really comes from; never a number that is not in the text.
4b. polarity: "neg" when "text" says something did NOT happen or is NOT so, else "pos". certainty: "stated" = the
   source gives it as a fact (even when someone else says it); "possible" = it may / might / could / is likely / is
   feared / is expected; "hypothetical" = an if, a plan that is not done, a threat, a prediction. If unsure: "possible".
5. attributed_to: who the article gives as the source ("article", "police", "victim's family", "accused",
   "eyewitness", "minister", "unnamed source", ...). Write it in English.
6. evidence: what the article cites: fir | court_record | official_data | video | official_statement |
   named_witness | unnamed_source | none.
7. Record every factual detail about the article's core event (the "signature") in events/claims,
   including small ones. One fact per item; do not merge. Every sentence of the article that states a fact
   gets an item: a long article gives many items.
8. Record in "context" what the article tells around the core event, so a reader understands it:
   "background" = earlier events that led to this one; "related" = a SEPARATE event the article itself
   connects to this one (put a short name of that event, with its date if given, in "event", e.g.
   "FSSAI finding on Nestle dairy whitener, 4 October"); "explanation" = what a rule, term, number or
   finding means; "reaction" = a person's or body's response not already recorded as a claim;
   "next" = what happens next (deadlines, hearings, required steps). Same rules for wording,
   stance and attribution. If the article is a roundup or live blog of UNRELATED news, ignore the
   unrelated items entirely: context is only what the article connects to the core event. Ignore the
   other stories a page lists around the article (other videos, "also read", "trending", "top stories",
   sidebars): they are not this article. Ignore
   anything the page says about the publication itself (its history, readership, editions, awards).
   Names, posts and numbers come ONLY from the article: never add, correct or update one from your own
   knowledge (it may be out of date), and never comment on the article ("referred to as X in the text").
9. "frame": the same item broken into fields, so items from different articles can be compared:
   who = who acts, or what the item is about ("Police", "India and EFTA", "Prime Minister Narendra Modi");
   action = what is done, as a base verb or verb phrase in English ("arrest", "sign", "take effect",
   "die", "say", "allege", "invest"); for a statement that someone said something, the action is what
   they did ("say", "allege", "deny") and "what" is what it was about; what = to what or whom;
   value = the answer the item gives, if any: a number with its unit ("125.27 million", "47 per cent",
   "at least 40"), a date, a place, or a short word ("corrupt", "guilty"); keep words like "about",
   "at least", "nearly" with the number; where = place if given; negated = true only if the item says
   it did NOT happen. Use the article's facts only; empty string when a field does not apply.
10. "quote": the FIRST SIX WORDS of the article sentence the item is read from, copied exactly as the article
   writes them, in the article's language and script (Hindi stays in Devanagari; do not translate, fix or shorten
   them). When the item comes from two sentences, the first six words of the first one.
11. "words": when the item is what a named person or body said and the article prints their EXACT words in
   quotation marks, copy those words exactly as printed (no quotation marks, no "he said"; at most 40 words; a
   longer quote: its most important sentence). Every such quote is an item of its own: stance "attributes",
   attributed_to the speaker, "text" its point in plain English, "words" the quote. Otherwise "words" is "".
   In a Hindi article "words" is always "" (an English quote there would be our translation, not their words).
12. Reply with the JSON only.
"""


def _fmt_ist(t: dt.datetime | None) -> str:
    if not t:
        return "unknown"
    return t.replace(tzinfo=dt.timezone.utc).astimezone(IST).strftime("%A %d %B %Y, %H:%M")


def _iso_or_none(v) -> str | None:
    if not v or not isinstance(v, str) or v.lower() in {"null", "none", "unknown"}:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(v[:19], fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return None


def _words(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(w).strip() for w in v if str(w).strip()][:12]


def normalize_extraction(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    out = {"signature": str(data.get("signature") or "").strip(), "events": [], "claims": [], "relations": [],
           "context": []}
    ids = set()
    for kind in ("events", "claims", "context"):
        for i, it in enumerate(data.get(kind) or []):
            if not isinstance(it, dict) or not str(it.get("text") or "").strip():
                continue
            if kind == "context" and it.get("type") not in CONTEXT_TYPES:
                continue
            local = str(it.get("id") or f"{kind[0]}{i + 1}")
            ids.add(local)
            item = {
                "id": local,
                "text": str(it["text"]).strip()[:500],
                "quote": str(it.get("quote") or "").strip()[:200],
                "src": evidence.pointers(it.get("src")),
                "words": str(it.get("words") or "").strip().strip('"“”\'‘’ ')[:400],
                "stance": choice(it.get("stance"), STANCES, "stance", "attributes"),   # unknown: NOT the article's own voice
                "attributed_to": str(it.get("attributed_to") or "article")[:200],
                "evidence": it.get("evidence") if it.get("evidence") in EVIDENCE else "none",
                "loaded_words": _words(it.get("loaded_words")),
            }
            item["frame"] = normalize_frame(it.get("frame"))
            item.update(_factuality(item["text"], it))
            item["stance_defaulted"] = kind != "context" and it.get("stance") not in STANCES          # E15: counted, and held back in verify
            if kind == "context":
                item["context"] = it["type"]
                item["event"] = str(it.get("event") or "").strip()[:160] if it["type"] == "related" else ""
            if kind == "events" or (kind == "context" and it.get("type") in ("background", "related")):
                start, end = _iso_or_none(it.get("start")), _iso_or_none(it.get("end"))
                if start and not end:
                    end = start
                if end and not start:
                    start = end
                if start and end and start > end:
                    start, end = end, start
                prec = it.get("precision") if it.get("precision") in PRECISION else "unknown"
                if not start:
                    prec = "unknown"
                item["time"] = {"when_text": str(it.get("when_text") or "")[:120],
                                "start": start, "end": end, "precision": prec}
            out[kind].append(item)
    for r in data.get("relations") or []:
        if (isinstance(r, dict) and r.get("from") in ids and r.get("to") in ids
                and r.get("from") != r.get("to") and r.get("type") in REL_TYPES):
            out["relations"].append({
                "from": r["from"], "to": r["to"], "type": r["type"],
                "stance": choice(r.get("stance"), STANCES, "stance", "attributes"),
                "attributed_to": str(r.get("attributed_to") or "article")[:200],
            })
    if not out["signature"] and out["events"]:
        out["signature"] = out["events"][0]["text"]
    if not out["signature"]:
        return None
    return out


META = re.compile(r"(?i)\([^)]*\b(?:the|this) (?:text|article|report|source)\b[^)]*\)|"
                  r"\b(?:referred to|called|named|written|spelt|spelled) as [^.;]*\bin (?:the|this) (?:text|article|report)\b")


def ground(ex: dict, source: str) -> int:
    """Statements the report itself does not support are dropped, not patched (Oct 9 2026, story 16197: a Hindi
    report names Chief Justice सूर्यकांत; reading wrote "Chief Justice Sanjiv Khanna (referred to as Chief Justice
    Suryakant in the text)", a name from the model's own, out-of-date memory): a titled person the report does
    not name, in any spelling or script (`textmatch.absent_people`), or a note about the text itself."""
    from .textmatch import absent_people
    dropped = set()
    for key in ("events", "claims", "context"):
        keep = []
        for it in ex.get(key) or []:
            bad = absent_people(it["text"], source)
            if bad or META.search(it["text"]):
                dropped.add(it["id"])
                log.info("reading dropped a statement the report does not support (%s): %s",
                         ", ".join(bad) or "a note about the text", it["text"][:120])
                continue
            keep.append(it)
        ex[key] = keep
    ex["relations"] = [r for r in ex.get("relations") or [] if r["from"] not in dropped and r["to"] not in dropped]
    return len(dropped)


def _factuality(text: str, it: dict) -> dict:
    """S1: polarity and certainty from BOTH readers, the model's closed answers and the sentence's parse
    (`factuality.read`). Certainty is the more cautious of the two (a possible / hypothetical reading from either wins);
    a polarity the two disagree on is "unknown". A field neither gives is "unknown", never a guess."""
    from . import factuality
    fp = factuality.read(text)
    pol_m = choice(it.get("polarity"), POLARITIES, "polarity", "unknown")
    cer_m = choice(it.get("certainty"), CERTAINTIES, "certainty", "unknown")
    pol = fp["polarity"] if pol_m == "unknown" else pol_m if fp["polarity"] == "unknown" else (
        pol_m if pol_m == fp["polarity"] else "unknown")
    if cer_m in ("possible", "hypothetical"):
        cer = cer_m
    elif fp["certainty"] == "possible":
        cer = "possible"
    elif cer_m == "stated" and fp["certainty"] in ("stated", "unknown"):
        cer = "stated"
    else:
        cer = "unknown" if cer_m == "unknown" else cer_m
    return {"polarity": pol, "certainty": cer}


def _rel(it: dict) -> dict | None:
    rel = {}
    if it.get("stance_defaulted"):
        rel["stance_defaulted"] = True
    if it.get("polarity") == "neg":
        rel["polarity"] = "neg"                 # only what differs from the plain reading is stored
    if it.get("certainty") in ("possible", "hypothetical"):
        rel["certainty"] = it["certainty"]
    if it.get("frame"):
        rel["frame"] = it["frame"]
    if it.get("refs"):
        rel["refs"] = it["refs"]
    if it.get("refs_open"):
        rel["refs_open"] = it["refs_open"]
    if it.get("src_text"):
        rel["span"] = it["src_text"][:600]          # the report's sentence the model pointed at (newsroom only)
    if it.get("quote"):
        rel["quote"] = it["quote"]          # the source sentence's first words (newsroom only): the audit's coverage
    if it.get("words"):
        rel["words"] = it["words"]          # a speaker's exact words, checked word for word against the report
    return rel or None


def store_extraction(store: Store, article_id: int, story_id: int | None, ex: dict) -> None:
    store.exec(delete(claims).where(claims.c.article_id == article_id))
    rows = []
    for kind, key in (("event", "events"), ("claim", "claims")):
        for it in ex[key]:
            rows.append(dict(story_id=story_id, article_id=article_id, local_id=it["id"], kind=kind,
                             text=it["text"], stance=it["stance"], attributed_to=it["attributed_to"],
                             evidence=it["evidence"], loaded_words=it["loaded_words"],
                             time=it.get("time"), rel=_rel(it)))
    for it in ex.get("context") or []:
        # context is stored like a statement, marked in `rel` (unused for statements): background and
        # related events are events (they have times), the rest are claims
        kind = "event" if it["context"] in ("background", "related") else "claim"
        rows.append(dict(story_id=story_id, article_id=article_id, local_id=it["id"], kind=kind,
                         text=it["text"], stance=it["stance"], attributed_to=it["attributed_to"],
                         evidence=it["evidence"], loaded_words=it["loaded_words"], time=it.get("time"),
                         rel={"context": it["context"], "event": it.get("event") or "",
                              **{k: v for k, v in (_rel(it) or {}).items()}}))
    for i, r in enumerate(ex["relations"]):
        rows.append(dict(story_id=story_id, article_id=article_id, local_id=f"r{i + 1}", kind="relation",
                         text="", stance=r["stance"], attributed_to=r["attributed_to"], evidence="none",
                         loaded_words=[], time=None, rel={"from": r["from"], "to": r["to"], "type": r["type"]}))
    if rows:
        with store.engine.begin() as c:
            c.execute(insert(claims), rows)


# ------------------------------------------------------------------ long reports and exact words (Oct 16 2026, owner)
# A report longer than one reading was cut at `max_article_chars`: the second half of a long feature was never seen.
# It is now read in PIECES of up to PIECE_CHARS, split at paragraph breaks, each piece starting with the last paragraph
# of the one before (a fact on the border is seen whole), each told the article's opening (who "he" is). At most
# MAX_PIECES pieces (a reading call each). The items of all pieces are one reading: ids prefixed by piece, the same
# statement read twice in the overlap kept once.
PIECE_CHARS = 5000
MAX_PIECES = 4
_QUOTE_FOLD = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "\u00a0": " "})


def _dangling(par: str) -> bool:
    """Does the paragraph open with a word that points back (he, she, it, they, this, these ...)? By the parse: the first
    token is a pronoun, or a demonstrative determiner. No parse: no."""
    from . import nlp
    toks = nlp.parse((par or "").strip()[:200])
    return bool(toks) and toks[0].pos in ("PRON",) or bool(toks) and toks[0].lemma.lower() in ("this", "that", "these", "those")


def _overlap(cur: list[str], max_back: int = 3) -> list[str]:
    """The paragraphs a new piece starts with (B23, coreference-first chunking): the last one of the piece before, and
    further back while the earliest of them opens with a pointer to an earlier paragraph, so no piece begins by pointing
    at something it was not given."""
    k = 1
    while k < len(cur) and k < max_back and _dangling(cur[-k]):
        k += 1
    return cur[-k:]


def pieces(text: str, cap: int | None = None, stats: dict | None = None) -> list[str]:
    """The report as one piece (it fits one reading) or as overlapping pieces split at paragraph breaks."""
    cap = cap or SETTINGS.max_article_chars
    t = text or ""
    if len(t) <= cap:
        return [t]
    paras = [p for p in re.split(r"\n+", t) if p.strip()]
    out: list[str] = []
    cur: list[str] = []
    for p in paras:
        while len(p) > PIECE_CHARS:                    # a paragraph longer than a piece is cut at a sentence end
            cut = max(p.rfind(". ", 0, PIECE_CHARS), p.rfind("। ", 0, PIECE_CHARS))
            cut = cut + 1 if cut > 0 else PIECE_CHARS
            paras_head, p = p[:cut], p[cut:].lstrip()
            if cur:
                out.append("\n".join(cur))
                cur = _overlap(cur)
            out.append(paras_head)
        if cur and sum(len(x) + 1 for x in cur) + len(p) > PIECE_CHARS:
            out.append("\n".join(cur))
            cur = _overlap(cur)                        # the overlap: the piece before's last paragraph(s), coreference first
        cur.append(p)
    if cur:
        out.append("\n".join(cur))
    total = len(out)
    if len(out) > MAX_PIECES:
        log.info("extract: a %d-character report read in %d pieces of %d", len(t), MAX_PIECES, len(out))
        full = out
        out = _most_central(out, MAX_PIECES)
        if stats is not None:
            stats["skipped_chars"] = sum(len(x) for x in full if x not in out)      # E10: kept, not only logged
    if stats is not None:
        stats.update(pieces=total, read=len(out), chars=len(t))
    return out


def _most_central(parts: list[str], k: int) -> list[str]:
    """S2: past the reading budget the pieces kept are the first one (who and what) and those nearest the report's centre
    (TextRank / centroid salience: cosine to the mean of all pieces), in their reading order, not simply the first ones."""
    try:
        import numpy as np
        from . import embed
        v, _ = embed.vectors(parts)
        centre = v.mean(axis=0)
        score = v @ centre
        rest = sorted(range(1, len(parts)), key=lambda i: (-float(score[i]), i))[:k - 1]
        return [parts[i] for i in sorted([0] + rest)]
    except Exception:
        return parts[:k]


def slots(text: str, limit: int = 8) -> str:
    """S2, carried entity slots: the people the whole report names (NER over the whole text, one identity each, most
    mentioned first) as one line, given to every piece and to the second reading, so a "he" or a surname in a piece
    that does not hold the introduction is read against the right person. Empty when the parse cannot run."""
    try:
        from .entities import EntityTable
        t = EntityTable()
        t.add_text(text or "")
        people = t.persons()
        people.sort(key=lambda e: -len(e.mentions))
        names = [e.name for e in people[:limit] if e.name]
        return ("People named in this article (a pronoun or surname below may mean one of them): "
                + "; ".join(names) + ".\n") if names else ""
    except Exception:
        return ""


def _norm_words(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").translate(_QUOTE_FOLD)).strip().lower()


def check_words(ex: dict, source: str, lang: str) -> int:
    """Exact words are kept only when they stand word for word in the report (English reports only: in a Hindi
    report they would be our translation). Returns how many were taken away."""
    src = _norm_words(source)
    n = 0
    for kind in ("events", "claims", "context"):
        for it in ex.get(kind) or []:
            w = it.get("words") or ""
            if w and (lang == "hi" or len(w.split()) < 3 or _norm_words(w) not in src):
                it["words"] = ""
                n += 1
    return n


def _merge_pieces(parts: list[dict]) -> dict:
    """One reading from the readings of a report's pieces (S3, E3): the items of all pieces are CLUSTERED as one
    entity-resolution problem. Pairs are code's "same" (`relate`), taken in the order they appear; a union that would
    put a pair code calls "different" into one cluster is refused (`redundancy.constrained`), so A = B, B = C, A != C
    is not settled by the order of the loop. One item stays per cluster (`redundancy.survivor`: the one read most often,
    then the longer); a relation that pointed at a dropped item is pointed at the survivor, and a relation that then
    joins an item to itself, or repeats another, is dropped."""
    from .relate import relate
    from . import redundancy
    out = {"signature": parts[0]["signature"], "events": [], "claims": [], "relations": [], "context": []}
    items: list[tuple[str, dict]] = []                 # (kind, item) in reading order
    key: dict[tuple[int, str], int] = {}               # (piece, original id) -> index
    for k, ex in enumerate(parts):
        for kind in ("events", "claims", "context"):
            for it in ex.get(kind) or []:
                key[(k, it["id"])] = len(items)
                items.append((kind, dict(it, _piece=k)))
    texts = {i: it["text"] for i, (_, it) in enumerate(items)}
    same, cannot = [], set()
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = texts[i], texts[j]
            if a.lower() == b.lower():
                same.append((i, j))
                continue
            r = relate(a, b)
            if r == "same":
                same.append((i, j))
            elif r == "different":
                cannot.add((i, j))
    groups, _ = redundancy.constrained(same, cannot)
    rep = {i: i for i in texts}
    support = {i: 1 for i in texts}
    for g in groups:
        for x in g:
            support[x] = len(g)
        lead, _v = redundancy.survivor(g, support, texts)
        for x in g:
            rep[x] = lead
    for i, (kind, it) in enumerate(items):
        if rep[i] != i:
            continue
        piece = it["_piece"]
        out[kind].append({x: v for x, v in it.items() if x != "_piece"} | {"id": ("" if piece == 0 else f"p{piece + 1}-") + it["id"]})
    def new_id(k: int, old: str) -> str | None:
        i = key.get((k, old))
        if i is None:
            return None
        _kind, it = items[rep[i]]
        piece = it["_piece"]
        return ("" if piece == 0 else f"p{piece + 1}-") + it["id"]
    seen = set()
    for k, ex in enumerate(parts):
        for r in ex.get("relations") or []:
            f, t = new_id(k, r["from"]), new_id(k, r["to"])
            if f is None or t is None or f == t:
                continue
            sig = (f, t, r.get("type"), r.get("kind"))
            if sig in seen:
                continue
            seen.add(sig)
            out["relations"].append(dict(r, **{"from": f, "to": t}))
    return out


def resolve_spans(ex: dict, sents: list[str], lang: str, registry=None) -> None:
    """B3: the sentence numbers the model gave become the report's own sentences (`src_text`); see evidence.py."""
    for kind in ("events", "claims", "context"):
        for it in ex.get(kind) or []:
            it["src_text"] = evidence.span(it.get("src"), sents, it["text"], lang, registry) or ""


def read_report(router: Router, a: dict, names: str = "") -> tuple[dict | None, str | None]:
    """(the reading of one report, the model) in one call, or in one call per piece for a long report. A later piece
    the model cannot read leaves the pieces already read (and is logged); the first piece failing fails the report."""
    stats = a.setdefault("_read_stats", {})
    texts = pieces(a["text"] or "", stats=stats)
    opening = (texts[0] if texts else "")[:400]
    parts, model = [], None
    for k, t in enumerate(texts):
        part = "" if len(texts) == 1 else (
            f"PART {k + 1} of {len(texts)} of a long article: read only the text below. "
            + (f"The article opened with: \"{opening}\" (people named there may be called by surname below).\n"
               if k else "\n") + (slots(a["text"] or "") if k else ""))
        numbered, sents = evidence.number(t)
        prompt = EXTRACT_PROMPT.format(outlet=a["outlet"], published=_fmt_ist(a["published_at"]),
                                       title=a["title"] or "", text=numbered, names=names, part=part)
        try:
            res = router.call("bulk", prompt, json_out=True, max_output_tokens=6000)   # room for each item's frame
        except (QuotaExhausted, CallFailed):
            if not parts:
                raise
            log.info("extract: piece %d of %d of article %s not read", k + 1, len(texts), a["id"])
            break
        ex = normalize_extraction(res.data)
        if ex is None:
            if not parts:
                return None, res.model
            continue
        resolve_spans(ex, sents, a.get("lang") or "en")
        parts.append(ex)
        model = model or res.model
    if not parts:
        return None, model
    return (parts[0] if len(parts) == 1 else _merge_pieces(parts)), model


COVERAGE_STATS: dict[str, float] = {}


def second_pass(router: Router, a: dict, ex: dict, left: list[str], names: str = "") -> dict:
    """The express desk's second reading (coverage.py): only the report's sentences no statement came from, merged
    into the first reading. A failed call leaves the first reading as it was."""
    part = ("THE REST of an article already read once: below are ONLY its sentences that no item came from yet. "
            "Record every fact and every exact quote in them (same rules; \"quote\" is the start of the sentence below "
            "it comes from).\n" + slots(a.get("text") or ""))
    numbered, sents = evidence.number("\n".join(left[:80]))
    prompt = EXTRACT_PROMPT.format(outlet=a["outlet"], published=_fmt_ist(a["published_at"]), title=a["title"] or "",
                                   text=numbered, names=names, part=part)
    try:
        res = router.call("bulk", prompt, json_out=True, max_output_tokens=6000)
    except (QuotaExhausted, CallFailed) as e:
        log.info("extract: second reading of article %s not done (%s)", a["id"], str(e)[:80])
        return ex
    more = normalize_extraction(res.data)
    if more is None:
        return ex
    more["signature"] = ex["signature"]
    resolve_spans(more, sents, a.get("lang") or "en")
    return _merge_pieces([ex, more])


def _read_meta(a: dict, ex: dict) -> dict:
    """E5 / E10: what reading did with this report, kept with the article: size, pieces read and the characters skipped,
    items by kind, and how many fields the model left open or whose pointer to the report failed."""
    items = [it for k in ("events", "claims", "context") for it in ex.get(k) or []]
    return {**{k: v for k, v in (a.get("_read_stats") or {}).items()},
            "items": {k: len(ex.get(k) or []) for k in ("events", "claims", "context", "relations")},
            "open_fields": sum(1 for it in items if it.get("certainty") == "unknown" or it.get("polarity") == "unknown"),
            "with_span": sum(1 for it in items if it.get("src_text")), "with_quote": sum(1 for it in items if it.get("quote"))}


def _extract_one(store: Store, router: Router, a: dict, names: str = "", registry=None) -> str:
    # names: the registry's English spellings of the names this Hindi article uses (namepair.py, Oct 16 2026)
    try:
        ex, model = read_report(router, a, names)
        if ex is None:
            raise ValueError("empty extraction")
        res = type("R", (), {"model": model})()
        ground(ex, f"{a['title'] or ''} {a['text'] or ''}")
        check_words(ex, f"{a['title'] or ''}. {a['text'] or ''}", a.get("lang") or "en")
        # the express desk (owner, Oct 16 2026): one report is all the story has, so it is read for COVERAGE: a first
        # reading under coverage.TARGET of the report's fact sentences gets one more call on the sentences left
        cov = None
        if a.get("express"):
            from . import coverage
            lang = a.get("lang") or "en"
            n, total, left = coverage.report(ex, a["text"] or "", lang, registry)
            first = round(n / total, 2) if total else None
            if total and n / total < coverage.TARGET and left:
                ex = second_pass(router, a, ex, left, names)
                ground(ex, f"{a['title'] or ''} {a['text'] or ''}")
                check_words(ex, f"{a['title'] or ''}. {a['text'] or ''}", lang)
                n, total, left = coverage.report(ex, a["text"] or "", lang, registry)
            cov = {"first": first, "final": round(n / total, 2) if total else None, "sentences": total,
                   "passed": (n / total >= coverage.MINIMUM) if total else None}
            COVERAGE_STATS["express_read"] = COVERAGE_STATS.get("express_read", 0) + 1
            COVERAGE_STATS["under_minimum"] = COVERAGE_STATS.get("under_minimum", 0) + (cov["passed"] is False)
        # the dates are code's (when.py, Oct 16 2026): the model copies the time words, code places them
        from . import when as _when
        for kind in ("events", "context"):
            for it in ex[kind]:
                if it.get("time"):
                    it["time"] = _when.read_time(it["time"], it.get("text"), a["published_at"])
        # each statement against the sentence of the article it came from; a lost or added small word gets one
        # repair on the quality tier (readcheck.py, Oct 16 2026). Never a reason to lose a reading.
        try:
            from . import readcheck
            readcheck.check(ex, f"{a['title'] or ''}. {a['text'] or ''}", a.get("lang") or "en", router, registry)
        except Exception as e:  # noqa: BLE001
            log.warning("readcheck failed for article %s: %s", a["id"], str(e)[:150])
        # what "It" and "the new scheme" point to, from the article itself (refs.py, Oct 15 2026)
        try:
            from . import refs as _refs
            _refs.resolve_extraction(ex, f"{a['title'] or ''}. {a['text'] or ''}", router)
        except QuotaExhausted:
            raise
        except Exception as e:  # noqa: BLE001 - references are an improvement, never a reason to lose a reading
            log.warning("refs failed for article %s: %s", a["id"], str(e)[:150])
    except QuotaExhausted:
        return "quota"
    except CallFailed as e:
        # the model was overloaded: not the article's fault, so it keeps all its tries
        log.info("extract: model unavailable for article %s (%s)", a["id"], str(e)[:120])
        return "failed"
    except Exception as e:  # noqa: BLE001
        log.warning("extract failed for article %s: %s", a["id"], str(e)[:200])
        store.exec(update(articles).where(articles.c.id == a["id"])
                   .values(extract_failures=(a["extract_failures"] or 0) + 1))
        return "failed"
    store_extraction(store, a["id"], a.get("story_id"), ex)
    meta = {"model": res.model, "read": _read_meta(a, ex)}
    if cov:
        meta["coverage"] = cov
    prev = store.one(select(articles.c.extraction).where(articles.c.id == a["id"]))
    if isinstance((prev or {}).get("extraction"), dict) and prev["extraction"].get("express"):
        meta["express"] = prev["extraction"]["express"]       # the express verdict (express.py) stays with the article
    store.exec(update(articles).where(articles.c.id == a["id"]).values(
        extraction=meta, extracted_at=utcnow(), signature=ex["signature"]))
    if a.get("story_id"):
        from . import dossier
        dossier.append(store, a["story_id"], "read", {"article": a["id"], "outlet": a.get("outlet"), **meta["read"]})
        story = store.one(select(stories.c.signature).where(stories.c.id == a["story_id"]))
        values = {"dirty": True, "updated_at": utcnow()}
        if story and (not story["signature"] or story["signature"] == a["title"]):
            values["signature"] = ex["signature"]  # neutral English one-liner beats a headline
        store.exec(update(stories).where(stories.c.id == a["story_id"]).values(**values))
    return "done"


def _diverse(todo: list[dict], arts: list[dict], done: list[dict], groups: dict, room: int) -> list[dict]:
    """S4: of a story's readable, unread pages (one per independent group, newest first) the ones to read: greedy maximum
    coverage (`selection.greedy`) of the story's headline words, weighted by how rare each word is in the story, given the
    pages already read. A page whose headline adds nothing the chosen pages have is read last; the newest wins every tie."""
    from . import idf, selection
    w = idf.Weights([a["title"] or "" for a in arts])
    covered0 = set()
    for a in done:
        covered0 |= idf.tokens(a["title"])

    def gain(a, chosen):
        have = set(covered0)
        for c in chosen:
            have |= idf.tokens(c["title"])
        return 1.0 + sum(w.w(x) for x in idf.tokens(a["title"]) - have)

    # one page per independent group: the first (newest) of a group is its candidate
    cands, seen = [], set()
    for a in todo:
        if groups[a["id"]] not in seen:
            seen.add(groups[a["id"]])
            cands.append(a)
    return selection.greedy(cands, room, lambda a: 1.0, gain)


def select_for_extraction(store: Store, focus: set[int] | None = None, express: set[int] | None = None) -> list[dict]:
    """Which articles are worth an LLM call. A story only one source covers can never be
    published and teaches the perspective model nothing, so it waits until a second
    independent source appears. Within a story only one article per independent source is
    read (a wire copy repeats its original), up to `max_extract_per_story` sources. An express story (express.py,
    `express` ids, already limited by its own reading cap) is read from its first independent source."""
    from .wire import independence_groups, independent
    # the text itself is fetched only for the articles chosen (egress, Oct 8 2026): choosing needs its length
    q = (select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.wire_group,
                articles.c.lang, articles.c.story_id, articles.c.title, func.length(articles.c.text).label("text_len"),
                articles.c.published_at, articles.c.extract_failures, articles.c.extracted_at, articles.c.text_source)
         .where(articles.c.story_id.is_not(None), articles.c.text.is_not(None)))
    if focus is not None:
        q = q.where(articles.c.story_id.in_(sorted(focus) or [-1]))
    rows = store.rows(q)
    from .editions import frozen_ids
    closed = frozen_ids(store)       # a published story is never read again (editions.py)
    by_story: dict[int, list[dict]] = {}
    for r in rows:
        if r["story_id"] in closed or (focus is not None and r["story_id"] not in focus):
            continue    # only the stories being prepared for the writer are read (priority.py)
        if ROUNDUP.search(r["title"] or ""):
            continue   # live blogs and news roundups mix unrelated events into one story
        by_story.setdefault(r["story_id"], []).append(r)
    ranked = []
    for sid, arts in by_story.items():
        groups = independence_groups(arts)
        if sid in (express or ()):
            # an express story is read from every OUTLET with a readable page (owner, Oct 16 2026: two outlets read
            # gave a far better page than one), not one per owner group; a wire copy repeated by two outlets is one
            from . import express as _x
            groups = {a["id"]: _x.outlet_key(a) for a in arts}
        # read in depth (owner, Oct 2026): a story is read only once 3+ independent sources have a
        # readable page. Under 3 it can never be published, and omissions (the main evidence of a
        # perspective) can only be seen when several outlets' versions of one story are read.
        readable = {groups[a["id"]] for a in arts if a["text_source"] != "summary"}
        if sid in (express or ()):
            from . import express as _x
            if len(readable) < _x.min_outlets():
                continue
        elif len(independent(readable)) < SETTINGS.min_sources_to_read:
            continue
        done = [a for a in arts if a["extracted_at"]]
        room = SETTINGS.max_extract_per_story - len(done)
        if room <= 0:
            continue
        seen_groups = {groups[a["id"]] for a in done}
        # one article per independent source: a wire copy or a second piece from the same outlet
        # would only repeat what that source already said
        # option B: a page we could not read (headline and blurb only) is never read for facts
        todo = [a for a in arts if not a["extracted_at"] and (a["extract_failures"] or 0) < 3
                and groups[a["id"]] not in seen_groups and a["text_source"] != "summary"]
        todo.sort(key=lambda a: (-(a["published_at"].timestamp()), -(a["text_len"] or 0)))
        picked = _diverse(todo, arts, done, groups, room)
        if picked:
            newest = max(a["published_at"] for a in arts)
            # finish stories already being read before starting new ones, then the most covered
            ranked.append((len(seen_groups - {groups[a["id"]] for a in picked}) > 0, len(readable), newest, picked))
    ranked.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    chosen = [a for *_, picked in ranked for a in picked]
    texts = {}
    ids = [a["id"] for a in chosen]
    for start in range(0, len(ids), 400):
        texts.update({r["id"]: r["text"] for r in heavy.fill(store, store.rows(
            select(articles.c.id, *heavy.columns(store, "text")).where(articles.c.id.in_(ids[start:start + 400]))), "text")})
    for a in chosen:
        a["text"] = texts.get(a["id"])
    return chosen


def retract_unreadable(store: Store) -> int:
    """Option B, applied to the past: articles read from a headline and blurb only (before this rule
    existed) lose their extracted statements, and their stories are re-analysed without them."""
    rows = store.rows(select(articles.c.id, articles.c.story_id)
                      .where(articles.c.text_source == "summary", articles.c.extracted_at.is_not(None)))
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    sids = sorted({r["story_id"] for r in rows if r["story_id"] is not None})
    for i in range(0, len(ids), 500):
        store.exec(delete(claims).where(claims.c.article_id.in_(ids[i:i + 500])))
        store.exec(update(articles).where(articles.c.id.in_(ids[i:i + 500])).values(extracted_at=None, extraction=None))
    for i in range(0, len(sids), 500):
        store.exec(update(stories).where(stories.c.id.in_(sids[i:i + 500])).values(dirty=True))
    log.info("extract: retracted statements from %d unreadable (headline-only) articles in %d stories", len(ids), len(sids))
    return len(ids)


TAVILY_BACKOFF_HOURS = 12      # after the first empty answer; doubled for each further one
TAVILY_MAX_FAILS = 3


def _tavily_state(a: dict) -> tuple[int, dt.datetime | None]:
    t = (a.get("extraction") or {}).get("tavily") if isinstance(a.get("extraction"), dict) else None
    if isinstance(t, dict):
        try:
            return int(t.get("fails") or 0), dt.datetime.fromisoformat(t["at"])
        except Exception:
            return int(t.get("fails") or 0), None
    if (a.get("extract_failures") or 0):                  # an older permanent mark: one failure, dated by the article
        return 1, a.get("published_at")
    return 0, None


def _tavily_due(a: dict, now: dt.datetime | None = None) -> bool:
    """Is a blocked page worth another credit? Never tried: yes. Tried and empty: again after a growing wait, at most
    TAVILY_MAX_FAILS times in all (a page Tavily cannot read for the third time is given up on)."""
    fails, at = _tavily_state(a)
    if fails == 0:
        return True
    if fails >= TAVILY_MAX_FAILS or at is None:
        return fails < TAVILY_MAX_FAILS and at is None
    now = now or utcnow()
    if at.tzinfo is None and now.tzinfo is not None:
        at = at.replace(tzinfo=now.tzinfo)
    return now - at >= dt.timedelta(hours=TAVILY_BACKOFF_HOURS * 2 ** (fails - 1))


def _tavily_failed(store: Store, a: dict) -> None:
    fails, _ = _tavily_state(a)
    ex = dict(a.get("extraction") or {}) if isinstance(a.get("extraction"), dict) else {}
    ex["tavily"] = {"fails": fails + 1, "at": utcnow().isoformat()}
    store.exec(update(articles).where(articles.c.id == a["id"]).values(extraction=ex))


def read_blocked_pages(store: Store, tavily, max_pages: int = 5, focus: set[int] | None = None, bank=None) -> int:
    """Pages our fetcher could not read, in stories worth reading, fetched through Tavily: at most
    one per independent source per story, stories closest to publishable first. `bank` (carry.Bank): pages the
    earlier hours of the quota day did not read are added to `max_pages`; what is sent now is booked."""
    if tavily is None or not tavily.enabled:
        return 0
    if bank is not None:
        max_pages = bank.left("tavily_pages", max_pages)
    if max_pages <= 0:
        return 0
    from .wire import independence_groups, independent
    rows = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.wire_group,
                             articles.c.story_id, articles.c.text_source, articles.c.extracted_at, articles.c.published_at,
                             articles.c.extract_failures, articles.c.author, articles.c.extraction)
                      .where(articles.c.story_id.is_not(None), articles.c.published_at >= utcnow() - dt.timedelta(hours=48)))
    from .editions import frozen_ids
    closed = frozen_ids(store)       # no credits on a published story (editions.py)
    by_story: dict[int, list[dict]] = {}
    for r in rows:
        if r["story_id"] not in closed and (focus is None or r["story_id"] in focus):
            by_story.setdefault(r["story_id"], []).append(r)
    wanted: list[tuple[int, dt.datetime, dict]] = []
    for sid, arts in by_story.items():
        groups = independence_groups(arts)
        if len(independent(groups)) < 2:
            continue
        readable = {groups[a["id"]] for a in arts if a["text_source"] != "summary"}
        tried = set()
        for a in sorted(arts, key=lambda a: a["published_at"], reverse=True):
            g = groups[a["id"]]
            if a["text_source"] == "summary" and g not in readable and g not in tried and _tavily_due(a):
                tried.add(g)
                wanted.append((sid, len(readable), a))
    # S6: budgeted maximum coverage (selection.greedy), one credit a page: the value of a page is how near its story is to
    # being readable (stories with sources already read first) and falls with every page of that story already chosen
    from . import selection
    pick = selection.greedy(wanted, max_pages, lambda t: 1.0,
                            lambda t, chosen: (1 + t[1]) / (1 + 2 * sum(1 for c in chosen if c[0] == t[0])))
    pick = [a for _, _, a in pick]
    if not pick:
        return 0
    before = tavily.spent_this_run
    got = tavily.extract([a["url"] for a in pick])
    if bank is not None and tavily.spent_this_run > before:    # credits were spent: those pages were sent
        bank.spend("tavily_pages", len(pick))
    n = 0
    for a in pick:
        text = re.sub(r"\n{3,}", "\n\n", (got.get(a["url"]) or "")).strip()
        if len(text) >= SETTINGS.min_full_text_chars:
            from .ingest import detect_agency
            from .wire import minhash
            text = text[: SETTINGS.max_article_chars * 2]
            # the wire fingerprint and agency were computed from the headline; recompute them from
            # the real text, or a PTI copy read this way would pass as an independent outlet
            store.exec(update(articles).where(articles.c.id == a["id"]).values(
                text=text, text_source="tavily", agency=detect_agency(a.get("author"), text),
                minhash=minhash(text), wire_group=None))
            n += 1
        elif a["url"] not in tavily.unasked:     # Tavily answered and had nothing: not a permanent verdict (S6), tried again later
            _tavily_failed(store, a)
    log.info("tavily: %d of %d blocked pages read", n, len(pick))
    return n


def extract_pending(store: Store, router: Router, deadline: float, workers: int = 6,
                    focus: set[int] | None = None, express: set[int] | None = None) -> int:
    """Read the selected articles, several at a time, while the router keeps every model inside
    its limits."""
    pending = select_for_extraction(store, focus, express)
    if not pending:
        return 0
    # a story's names paired across languages before any of its articles is read (namepair.py, Oct 16 2026):
    # the readings run in parallel, so this cannot wait for one of them
    from . import namepair, names as _names, readcheck
    name_hints = namepair.prepare(store, router, pending, deadline)
    readcheck.reset_run()
    try:
        registry = _names.load(store)          # Hindi names that tie a statement to its report sentence
    except Exception:  # noqa: BLE001
        registry = None
    stop = threading.Event()
    counts = {"done": 0, "failed": 0, "quota": 0}
    lock = threading.Lock()
    queue = iter(pending)

    def worker():
        while not stop.is_set():
            if time.time() > deadline:
                stop.set()
                return
            with lock:
                a = next(queue, None)
            if a is None:
                return
            if express and a.get("story_id") in express:
                a = dict(a, express=True)              # read for coverage (coverage.py)
            outcome = _extract_one(store, router, a, name_hints.get(a["id"], ""), registry)
            with lock:
                counts[outcome] += 1
            if outcome == "quota":
                stop.set()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if readcheck.STATS:
        log.info("readcheck: %s", dict(readcheck.STATS))
        log.info("reading schema: %s", dict(SCHEMA))
        log.info("evidence spans: %s", dict(evidence.STATS))
    if COVERAGE_STATS:
        log.info("express coverage: %s", dict(COVERAGE_STATS))
    left = len(pending) - counts["done"] - counts["failed"]
    log.info("extract: %d done, %d failed, %d left for next run%s", counts["done"], counts["failed"], left,
             " (quota exhausted)" if counts["quota"] else "")
    return counts["done"]

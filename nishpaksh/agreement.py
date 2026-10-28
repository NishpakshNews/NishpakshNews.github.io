"""A body of several people is "they", not "it" (owner, Oct 15 2026).

"The Supreme Court said it was examining the plea." is wrong: several judges sit on a case, and the court acts as them.
The grammar rule is COLLECTIVE-NOUN AGREEMENT (notional concord, also "synesis"): when the noun names a group that acts
as its members, the pronoun and the verb are plural. "The Supreme Court said they were examining the plea." The owner's
list of such bodies is `config/collectives.yaml` (court, bench, tribunal, commission, committee, council, cabinet,
board, panel, police ...; a government, ministry, company or party stays "it" until the owner adds it).

By code, on the finished article (no model): every "it / its / itself" whose nearest BODY before it (this sentence, else
the sentence before) is one of those bodies becomes "they / their / themselves", and the verb after a subject "it" agrees
(was -> were, is -> are, has -> have, says -> say: inflected by lemminflect). Conservative: the nearest body decides ("The court asked
the Centre whether it ..." stays "it": the Centre is nearer), a person or a place is not a body, an expletive "it"
("it is not clear that ...") is left, and a pronoun with no body before it is left alone.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT = {
    "words": ["court", "bench", "tribunal", "commission", "committee", "council", "cabinet", "board", "panel", "jury",
              "parliament", "assembly", "collegium", "senate", "police", "politburo"],
    "names": ["Lok Sabha", "Rajya Sabha", "Vidhan Sabha", "Congress Working Committee", "Election Commission of India"],
    "leave": [],
}
_cache: dict | None = None


def _data() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data = dict(DEFAULT)
    try:
        import yaml
        raw = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "collectives.yaml").read_text("utf-8"))
        if isinstance(raw, dict):
            for k in DEFAULT:
                if isinstance(raw.get(k), list):
                    data[k] = [str(x) for x in raw[k] if str(x).strip()]
    except Exception as e:  # noqa: BLE001 - a missing or broken file is the defaults
        log.info("collectives.yaml not read (%s): defaults", str(e)[:80])
    _cache = data
    return data


def reset() -> None:
    global _cache
    _cache = None


def is_collective(name: str | None) -> bool:
    """A body named by `name` (\"Supreme Court\", \"the bench\", \"Election Commission of India\") acts as a group."""
    n = re.sub(r"^(?:the|a|an)\s+", "", (name or "").strip().lower())
    if not n:
        return False
    d = _data()
    if any(n == x.lower() or n.endswith(" " + x.lower()) for x in d["leave"]):
        return False
    if any(n == x.lower() for x in d["names"]):
        return True
    last = re.findall(r"[a-z]+", n)
    if not last:
        return False
    if last[-1] in {w.lower() for w in d["words"]}:
        return True
    # "Court of Appeal", "Commission of Inquiry": the first word names the body
    m = re.match(r"([a-z]+)\s+(?:of|for)\s+", n)
    return bool(m and m.group(1) in {w.lower() for w in d["words"]})


def _bodies() -> re.Pattern:
    from .voice import BODY_WORDS, PLURAL_BODY, SHORT_BODY
    d = _data()
    words = sorted({*(w.lower() for w in d["words"]), *SHORT_BODY, *(b for b in BODY_WORDS if len(b) > 3)}, key=len, reverse=True)
    alt = "|".join(re.escape(w) for w in words)
    names = "|".join(re.escape(n) for n in sorted(d["names"], key=len, reverse=True))
    cap = (rf"(?:(?:[A-Z][\w&.'’-]*\s+){{0,4}}(?:{'|'.join(re.escape(w.capitalize()) for w in words)})"
           rf"|(?:[A-Z][\w&.'’-]*\s+){{1,4}}(?:{alt}))"
           rf"(?:\s+of\s+(?:the\s+)?[A-Z][\w-]*)?")
    low = rf"(?:the|The)\s+(?:{alt})"
    return re.compile(rf"(?<![\w'’-])(?:(?:the|The)\s+)?(?:{names})(?![\w'’-])|(?<![\w'’-]){low}(?![\w'’-])"
                      rf"|(?<![\w'’-])(?:(?:the|The)\s+)?{cap}(?![\w'’-])")


_BODY_RX: re.Pattern | None = None


def body_mentions(text: str) -> list[tuple[int, int, str, bool]]:
    """(start, end, phrase, is_collective) for each body the text names, in order."""
    global _BODY_RX
    if _BODY_RX is None:
        _BODY_RX = _bodies()
    out = []
    for m in _BODY_RX.finditer(text or ""):
        phrase = m.group(0)
        if re.match(r"^(?:The|the)\s+\w+$", phrase) is None and re.match(r"^The\s", phrase):
            pass
        out.append((m.start(), m.end(), phrase, is_collective(phrase)))
    return out


_PRON = re.compile(r"(?<![\w'’-])(?P<w>It|it|Its|its|Itself|itself)(?![\w'’-])")
_QUOTE = re.compile(r'"[^"]*"|“[^”]*”')


def _prev_word(text: str, pos: int) -> str:
    m = re.search(r"([A-Za-z']+)[\s,]*$", text[:pos])
    return m.group(1).lower() if m else ""


def _plural(tok) -> str | None:
    """The plural-subject form of a finite verb, from the inflection library (lemminflect), not a verb table:
    is -> are, was -> were, has -> have, says -> say; any other tense is the same for one or many."""
    from lemminflect import getInflection
    if tok.tag == "VBZ":
        forms = getInflection(tok.lemma, "VBP")
    elif tok.tag == "VBD" and tok.lemma == "be":
        forms = getInflection("be", "VBD")
    else:
        return None
    if not forms:
        return None
    new = forms[-1]
    if tok.text.lower().endswith(("n't", "n’t")):
        new += tok.text[-3:]
    return new[:1].upper() + new[1:] if tok.text[:1].isupper() else new


def _nearest_body(before: str) -> tuple[str, bool] | None:
    """The body the text before a pronoun names last, and whether it acts as a group. A person is no body."""
    found = body_mentions(before)
    if not found:
        return None
    s, e, phrase, coll = found[-1]
    return phrase, coll


_SPEECH = {"said", "says", "stated", "added", "noted", "argued", "claimed", "alleged", "told", "maintained", "contended",
           "submitted", "warned", "stressed", "observed", "clarified", "announced", "confirmed", "denied", "explained",
           "insisted", "that", "whether", "if", "because", "as", "when", "after", "before", "while", "since"}


def _parse_same_clause(toks, pron, body_end: int) -> bool | None:
    """From the dependency parse: is the pronoun in the clause of the body's own verb, or in a clause that verb governs
    as a complement or an adverbial ("The court said it was ...", "The court dismissed it because it was ...")? A clause
    joined by "and" / "but" with a subject of its own, or a relative clause, is another clause. None = the parse does
    not say (no part of speech, no verb found)."""
    if not any(t.pos for t in toks):
        return None
    body = next((t for t in toks if t.start < body_end <= t.end), None)
    if body is None:
        return None

    def verb_of(t):
        for _ in range(len(toks)):
            if t.tag.startswith("VB") or t.pos in ("VERB", "AUX"):
                return t
            if t.head == t.i:
                return None
            t = toks[t.head]
        return None
    bv, pv = verb_of(body), verb_of(toks[pron.head]) if pron.dep in ("nsubj", "nsubjpass") else verb_of(pron)
    if bv is None or pv is None:
        return None
    t = pv
    for _ in range(len(toks)):
        if t.i == bv.i:
            return True
        if t.dep not in ("ccomp", "xcomp", "advcl") or t.head == t.i:
            return False
        t = toks[t.head]
    return False


def _same_clause(here: str, near: tuple[str, bool], full_before: str, context: str, parsed=None) -> bool:
    """Is the pronoun still about that body? Between the body and the pronoun there must be no quotation and no new
    clause (\"and\" / \"but\" / \";\") unless the word right before the pronoun is a speech verb or a joining word
    (\"The court heard the plea and said it ...\" is the court; \"The court said \\\"...\\\" and it was adjourned\" is not)."""
    found = body_mentions(here)
    if not found:
        return True                                # the body is in the sentence before: the pronoun opens the sentence
    gap = here[found[-1][1]:]
    if re.search(r"[\"“”]", gap):
        return False                               # a quotation between the body and the pronoun
    old = (not _QUOTE.search(gap)) if _prev_word(here + " ", len(here) + 1) in _SPEECH else (
        not re.search(r"[\"“”;:]|(?:\s(?:and|but|or|while|whereas|which|who)\s)|[.!?]\s", gap))
    if parsed is not None:                         # the parse says whether it is the body's clause (the old words are the fallback)
        from . import auditcount
        c = auditcount.counter("clause")
        new = _parse_same_clause(parsed[0], parsed[1], found[-1][1])
        if new is not None:
            c["asked"] += 1
            if new != old:
                c["parse_same_list_not" if new else "list_same_parse_not"] += 1
            return new
        c["unread"] += 1
    return old


def fix_text(text: str, context: str = "") -> tuple[str, int]:
    """One sentence (or coloured part) with `it / its / itself` made plural where the nearest body before it acts as a
    group. `context` is what comes before (the sentence before). Returns (text, how many pronouns changed). The
    grammatical role of each pronoun (subject, object, \"it is clear that\", possessive) comes from the dependency
    parse (`nlp.parse`); a sentence that cannot be parsed is left exactly as written."""
    if not re.search(r"(?i)\bits?\b|\bitself\b", text):
        return text, 0
    from . import nlp
    toks = nlp.parse(text)
    if not toks:
        return text, 0
    at = {t.start: t for t in toks}
    quotes = [(m.start(), m.end()) for m in _QUOTE.finditer(text)]
    edits: list[tuple[int, int, str]] = []
    for m in _PRON.finditer(text):
        if any(a <= m.start() < b for a, b in quotes):
            continue
        t = at.get(m.start())
        if t is None:
            continue
        here = text[:m.start()]
        near = _nearest_body(here) or (_nearest_body(context) if not body_mentions(here) else None)
        if not near or not near[1] or not _same_clause(here, near, here, context, (toks, t)):
            continue
        low, cap = m.group("w").lower(), m.group("w")[:1].isupper()
        if low == "its":
            edits.append((m.start(), m.end(), "Their" if cap else "their"))
        elif low == "itself":
            edits.append((m.start(), m.end(), "Themselves" if cap else "themselves"))
        elif t.dep in ("nsubj", "nsubjpass"):
            verb = next((x for x in sorted([toks[t.head]] + [c for c in toks if c.head == t.head and c.dep in ("aux", "auxpass")],
                                           key=lambda x: x.i) if x.i > t.i and x.tag in ("VBZ", "VBD", "MD")), None)
            if verb is None:
                continue
            nv = _plural(verb) if verb.tag != "MD" else verb.text
            if nv is None and verb.tag != "MD" and verb.tag != "VBD":
                continue
            edits.append((m.start(), m.end(), "They" if cap else "they"))
            if nv and nv != verb.text:
                edits.append((verb.start, verb.end, nv))
        elif t.dep in ("dobj", "obj", "pobj", "dative", "iobj"):
            edits.append((m.start(), m.end(), "Them" if cap else "them"))
        # "expl" (it is clear that ...) and anything else: left
    if not edits:
        return text, 0
    for s, e, new in sorted(set(edits), reverse=True):
        text = text[:s] + new + text[e:]
    return text, sum(1 for s, e, new in set(edits) if new.lower() in {"they", "their", "themselves", "them"})


def fix_article(paragraphs: list[list[dict]]) -> int:
    """The whole article, sentence by sentence (and part by part), in reading order. Returns how many pronouns changed."""
    changed = 0
    for para in paragraphs:
        before = ""
        for sent in para:
            if sent.get("parts"):
                ctx = before
                for part in sent["parts"]:
                    part["text"], n = fix_text(part["text"], ctx)
                    changed += n
                    ctx = part["text"]
                sent["text"] = " ".join(p["text"].strip() for p in sent["parts"])
            else:
                sent["text"], n = fix_text(sent["text"], before)
                changed += n
            before = sent["text"]
    return changed

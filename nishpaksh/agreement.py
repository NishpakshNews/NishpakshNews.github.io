"""A body of several people is "they", not "it" (owner, Oct 15 2026).

"The Supreme Court said it was examining the plea." is wrong: several judges sit on a case, and the court acts as them.
The grammar rule is COLLECTIVE-NOUN AGREEMENT (notional concord, also "synesis"): when the noun names a group that acts
as its members, the pronoun and the verb are plural. "The Supreme Court said they were examining the plea." The owner's
list of such bodies is `config/collectives.yaml` (court, bench, tribunal, commission, committee, council, cabinet,
board, panel, police ...; a government, ministry, company or party stays "it" until the owner adds it).

By code, on the finished article (no model): every "it / its / itself" whose nearest BODY before it (this sentence, else
the sentence before) is one of those bodies becomes "they / their / themselves", and the verb after a subject "it" agrees
(was -> were, is -> are, has -> have, does -> do, says -> say). Conservative: the nearest body decides ("The court asked
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


PLURAL_VERB = {"was": "were", "is": "are", "has": "have", "does": "do", "isn't": "aren't", "wasn't": "weren't",
               "hasn't": "haven't", "doesn't": "don't", "isn’t": "aren’t", "wasn’t": "weren’t", "hasn’t": "haven’t",
               "doesn’t": "don’t"}
# present-tense reporting and acting verbs: "it says" -> "they say"
PRESENT_S = {"says", "believes", "wants", "argues", "maintains", "claims", "denies", "seeks", "adds", "notes", "takes",
             "gives", "plans", "expects", "considers", "opposes", "supports", "finds", "holds", "orders", "directs",
             "hears", "rejects", "accepts", "feels", "thinks", "asks", "calls", "needs", "keeps", "makes", "sees",
             "stresses", "warns", "insists", "contends", "submits", "observes", "reserves", "issues", "grants"}
_ADV = {"also", "now", "then", "already", "still", "never", "only", "just", "again", "further", "later", "earlier",
        "not", "even", "yet", "soon", "currently", "reportedly"}
# what stands before a subject "it" (a clause start) and before an object "it"
_SUBJECT_AFTER = {"that", "and", "but", "or", "as", "when", "while", "because", "since", "if", "after", "before", "which",
                  "whereas", "though", "although", "said", "says", "stated", "added", "noted", "argued", "claimed",
                  "alleged", "told", "maintained", "contended", "submitted", "warned", "stressed", "observed",
                  "clarified", "announced", "confirmed", "denied", "explained", "insisted", "whether", "why", "how",
                  "what", "where", "until", "unless", "so", "yet", "then", "once", "now", "than"}
_OBJECT_AFTER = {"asked", "told", "urged", "directed", "ordered", "requested", "moved", "approached", "petitioned",
                 "before", "to", "from", "with", "against", "of", "by", "for", "on", "at", "in", "informed", "wrote",
                 "reminded", "advised", "pressed", "challenged", "appealed", "allowed", "let", "made", "got"}
_EXPLETIVE = re.compile(
    r"(?i)^it\s+(?:is|was|will be|would be|has been|remains|became|seems|appears|looks|may be|might be|could be)\s+"
    r"(?:not\s+|yet\s+|still\s+|also\s+|quite\s+|very\s+)*(?:clear|unclear|known|unknown|likely|unlikely|possible|"
    r"impossible|expected|believed|understood|learnt|learned|time|too|the first|the second|the third|the latest|"
    r"the last|a first|reported|alleged|said|feared|hoped|noted|important|necessary|essential|evident|obvious|"
    r"true|false|wrong|right|fair|just|proper|improper|unfortunate|worrying|concerning|a mistake|a matter|"
    r"raining|snowing|dark|late|early)\b")
_PRON = re.compile(r"(?<![\w'’-])(?P<w>It|it|Its|its|Itself|itself)(?![\w'’-])")
_QUOTE = re.compile(r'"[^"]*"|“[^”]*”')


def _prev_word(text: str, pos: int) -> str:
    m = re.search(r"([A-Za-z']+)[\s,]*$", text[:pos])
    return m.group(1).lower() if m else ""


def _plural_verb(word: str) -> str | None:
    w = word.lower()
    if w in PLURAL_VERB:
        new = PLURAL_VERB[w]
    elif w in PRESENT_S:
        new = w[:-3] + "y" if w.endswith("ies") else w[:-2] if w.endswith(("sses", "shes", "ches")) else w[:-1]
    else:
        return None
    return new[:1].upper() + new[1:] if word[:1].isupper() else new


def _verb_after(text: str, end: int) -> tuple[int, int, str] | None:
    """The first verb after a subject pronoun, past up to two adverbs: (start, end, word)."""
    pos, skipped = end, 0
    while True:
        m = re.match(r"\s+([A-Za-z’']+)", text[pos:])
        if not m:
            return None
        w = m.group(1)
        if w.lower() in _ADV and skipped < 2:
            pos += m.end()
            skipped += 1
            continue
        return pos + m.start(1), pos + m.end(1), w


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


def _same_clause(here: str, near: tuple[str, bool], full_before: str, context: str) -> bool:
    """Is the pronoun still about that body? Between the body and the pronoun there must be no quotation and no new
    clause (\"and\" / \"but\" / \";\") unless the word right before the pronoun is a speech verb or a joining word
    (\"The court heard the plea and said it ...\" is the court; \"The court said \\\"...\\\" and it was adjourned\" is not)."""
    found = body_mentions(here)
    if not found:
        return True                                # the body is in the sentence before: the pronoun opens the sentence
    gap = here[found[-1][1]:]
    if _prev_word(here + " ", len(here) + 1) in _SPEECH:
        return not _QUOTE.search(gap) and '"' not in gap and "“" not in gap
    return not re.search(r"[\"“”;:]|(?:\s(?:and|but|or|while|whereas|which|who)\s)|[.!?]\s", gap)


def fix_text(text: str, context: str = "") -> tuple[str, int]:
    """One sentence (or coloured part) with `it / its / itself` made plural where the nearest body before it acts as a
    group. `context` is what comes before (the sentence before). Returns (text, how many pronouns changed)."""
    if not re.search(r"(?i)\bits?\b|\bitself\b", text):
        return text, 0
    quotes = [(m.start(), m.end()) for m in _QUOTE.finditer(text)]
    edits: list[tuple[int, int, str]] = []
    for m in _PRON.finditer(text):
        if any(a <= m.start() < b for a, b in quotes):
            continue
        w = m.group("w")
        low = w.lower()
        here = text[:m.start()]
        near = _nearest_body(here) or (_nearest_body(context) if not body_mentions(here) else None)
        if not near or not near[1]:
            continue
        if not _same_clause(here, near, text[:m.start()], context):
            continue
        cap = w[:1].isupper()
        if low == "its":
            edits.append((m.start(), m.end(), "Their" if cap else "their"))
        elif low == "itself":
            edits.append((m.start(), m.end(), "Themselves" if cap else "themselves"))
        else:
            if _EXPLETIVE.match(text[m.start():]):
                continue
            prev = _prev_word(text, m.start())
            at_start = not here.strip() or here.rstrip().endswith((".", "!", "?", ":", ";", '"', "”"))
            nxt = _verb_after(text, m.end())
            if at_start or prev in _SUBJECT_AFTER or here.rstrip().endswith(","):
                if nxt is None:
                    continue
                edits.append((m.start(), m.end(), "They" if cap else "they"))
                nv = _plural_verb(nxt[2])
                if nv:
                    edits.append((nxt[0], nxt[1], nv))
            elif prev in _OBJECT_AFTER:
                edits.append((m.start(), m.end(), "Them" if cap else "them"))
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

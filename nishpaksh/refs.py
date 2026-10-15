"""Every sentence knows what came before it: who or what "It" and "the new scheme" are (owner, Oct 15 2026).

Seen on two live articles:
    "It was trying to trace the missing video recording, Election Commission of India said."  (lead; who is "It"?)
    "The new scheme is replacing the Mahatma Gandhi National Rural Employment Guarantee Scheme."  (which scheme?)
The source outlets named both ("The Election Commission of India said it was trying to ..."; "... approved a new rural
employment guarantee scheme, Viksit Bharat-Guarantee for Rozgar and Ajeevika Mission (Gramin)").

Why it happens (three causes, one per layer below):
  1. READING takes a sentence out of its article. The reading prompt moves "said" and the speaker out of the fact
     (rule 2b), so a sentence whose subject WAS the speaker ("ECI said it was trying ...") becomes "It was trying ...".
     And a sentence that pointed back to an earlier sentence of the article ("the new scheme") loses what it pointed
     to. The prompt asks for names (rule 2c); nothing checked that the model did it, and the small models do it half
     the time.
  2. WRITING puts statements in a NEW order. Even a perfect sentence of the source ("the new scheme", fine after the
     sentence that names it) is dangling when the plan puts it first in a paragraph. `gloss.py` knew kin and offices only.
  3. Nothing looked at how a sentence OPENS. "It ..." as the first words of a paragraph points at nothing.

The fix is by code, in three layers (no new prohibition on the writer is the only protection):
  A. `resolve_extraction` (reading, with the source article at hand): a subject pronoun that is the statement's own
     speaker is replaced by the speaker, only when the source says so ("ECI said it was ..."); a generic thing
     ("the new scheme", "the bill", "the video") gets the name the source gives it, stored beside the statement
     (`rel.refs`), never inside its text (matching compares texts). Code finds the name in the source first; for what
     code cannot find, ONE batched model question per article asks for the exact words, and the answer is kept only if
     those words stand in the source (a model can neither invent nor pick a name the article does not have).
  B. `gloss_article` (writing, reading order): the first time a thing is written without the reader having been told
     what it is (nothing earlier in the headline or text carries its name), the name goes in brackets right after it:
     "The new scheme (Viksit Bharat-Guarantee for Rozgar and Ajeevika Mission (Gramin)) is replacing ...". Once.
  C. `opening_problem` / `repair_opening` (writing, checks): a sentence that opens a paragraph with It / They / This /
     These / Those / Its / Their points at nothing. One safe repair: "It was trying ..., X said." becomes
     "X said it was trying ..." (the attribution comes first; the pronoun then has its antecedent). No safe repair:
     the sentence is refused ("opens with a pronoun") and the fill pass rewrites it, like any other fault.
Counted, not enforced: `narrative.refs` = {glossed, unresolved: [...]} on the article, so replay shows what is left.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# ----- what counts as a reference that needs an antecedent -----------------------------------------------------

# things and events (not bodies or offices: "the court", "the minister" are named by names.py / gloss.py)
HEADS = ("scheme", "programme", "program", "policy", "bill", "law", "rule", "rules", "order", "case", "incident",
         "video", "footage", "recording", "report", "move", "decision", "meeting", "project", "plan", "mission",
         "campaign", "initiative", "verdict", "judgment", "judgement", "ruling", "probe", "investigation",
         "notification", "circular", "amendment", "accident", "attack", "protest", "rally", "summit", "deal",
         "agreement", "pact", "treaty", "tender", "study", "survey", "yojana", "drive", "exercise", "process",
         "petition", "complaint", "allegation", "claim", "proposal", "policy", "package", "ordinance")
_HEAD_ALT = "|".join(sorted(set(HEADS), key=len, reverse=True))
# "the new scheme", "this move", "the missing video recording", "said report", "the same case"
DEFINITE = re.compile(
    rf"(?<![\w'’-])(?P<det>the|this|that|these|those|said|such|same|the same)\s+"
    rf"(?P<mods>(?:[a-z][a-z-]*\s+){{0,3}}?)(?P<head>(?:(?:{_HEAD_ALT})\s+)?(?:{_HEAD_ALT}))(?![\w-])", re.I)
_DET_WORDS = {"the", "this", "that", "these", "those", "said", "such", "same"}
# a lower-case modifier that makes it a different phrase: "the case of", "the bill was passed" keep the match;
# but a phrase that is the object of "of" ("the head of the case") is a part of a longer name, not a reference
_GENERIC_NEEDS_NOTHING = re.compile(r"(?i)\b(?:in|under|for|on)\s+the\s+(?:process|meantime|case)\s+of\b")

PRON_OPEN = re.compile(r"^(?P<p>It|They|This|These|Those|Its|Their|He|She|His|Her)\b(?P<rest>.*)$", re.S)
OPEN_PRON = re.compile(r"^(?P<p>It|They|This|These|Those|Its|Their)\b(?P<rest>.*)$", re.S)
# "It is not clear whether ...", "It is the first time ...": nothing to point back to
EXPLETIVE = re.compile(r"(?i)^it\s+(?:is|was|will be|would be|has been|remains|became|seems|appears)\s+"
                       r"(?:not\s+|yet\s+|still\s+)*(?:clear|unclear|known|unknown|likely|unlikely|possible|"
                       r"impossible|expected|believed|understood|learnt|learned|time|too|the first|the second|"
                       r"the third|the latest|the last|a first|reported|alleged|said|feared|hoped|noted|not)\b")
RAIN = re.compile(r"(?i)^it\s+(?:is|was|will be)\s+(?:raining|snowing|dark|late|early)\b")
_QUOTE = re.compile(r'"[^"]*"|“[^”]*”')


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def definite_phrases(text: str) -> list[dict]:
    """The generic references in a text: {start, end, phrase, mods, head}. A phrase with a capital in it is a name
    ("the Waqf Bill") and is not generic."""
    out = []
    quotes = [(m.start(), m.end()) for m in _QUOTE.finditer(text or "")]
    for m in DEFINITE.finditer(text or ""):
        phrase = m.group(0)
        if any(a <= m.start() < b for a, b in quotes):
            continue
        # a capitalised word right after the head ("the order Monday") is not part of it; a capital INSIDE means a name
        if any(w[:1].isupper() for w in phrase.split()[1:]) :
            continue
        before = text[max(0, m.start() - 12):m.start()]
        if _GENERIC_NEEDS_NOTHING.search(before + phrase + " of"):
            continue
        mods = [w.lower() for w in m.group("mods").split()]
        if {"the", "a", "an", "of", "and", "that", "to", "in", "on", "for", "by", "with"} & set(mods):
            continue                                   # "that the video": the phrase starts at "the", not at "that"
        out.append({"start": m.start(), "end": m.end(), "phrase": phrase, "det": m.group("det").lower(),
                    "mods": mods, "head": m.group("head").lower()})
    return out


# ----- A. reading: find what a reference points to in the source article ----------------------------------------

_CONNECT = {"of", "for", "and", "the", "in", "on", "&", "to", "de", "-", "–", "—"}


def _name_at(source: str, pos: int, max_words: int = 14) -> str | None:
    """The capitalised name that starts at `pos` of `source` ("Viksit Bharat–Guarantee for Rozgar and Ajeevika
    Mission (Gramin)"): capitalised words, with of / for / and / the / in between them, brackets with a capitalised
    word inside. Stops at punctuation that ends a name."""
    toks = re.finditer(r"\S+", source[pos:])
    words: list[tuple[str, int]] = []
    for m in toks:
        words.append((m.group(0), pos + m.end()))
        if len(words) >= max_words + 4:
            break
    name: list[str] = []
    end_at = None
    i = 0
    while i < len(words) and len(name) < max_words:
        w, end = words[i]
        bare = w.strip(",;:.")
        core = bare.strip("()")
        is_cap = bool(core[:1].isupper() or core[:1].isdigit()) and not core.lower() in _CONNECT
        if is_cap:
            name.append(bare)
            end_at = end
            if w.endswith((",", ";", ":", ".")):
                break
            i += 1
            continue
        if core.lower() in _CONNECT and not w.endswith((",", ";", ":", ".")) and i + 1 < len(words):
            nxt = words[i + 1][0].strip(",;:.").strip("()")
            if nxt[:1].isupper():
                name.append(bare)
                i += 1
                continue
        break
    if not name or end_at is None:
        return None
    text = source[pos:end_at].rstrip(",;:. ")
    if len(re.findall(r"[A-Za-z]", text)) < 4:
        return None
    return text


_NAMED_AFTER = re.compile(r"(?:\s*[,(–—-]\s*|\s+(?:called|named|titled|dubbed|christened|known as|namely)\s+)")


def find_antecedent(ref: dict, source: str) -> str | None:
    """The name the source gives the thing a generic reference points to, or None. Evidence only: a name standing
    right after the head ("a new rural employment guarantee scheme, Viksit Bharat ...", "scheme called X"), or a
    name ending in the head word ("the Pradhan Mantri Awas Yojana"); the same modifiers as the reference ("new")
    must stand in the description. Two different names: None (never a guess)."""
    src = _norm(source)
    head = ref["head"]
    mods = [m for m in ref.get("mods") or [] if m not in {"said", "same", "such"}]
    found: dict[str, str] = {}
    for m in re.finditer(rf"(?<![\w-])(?P<pre>(?:[A-Za-z][\w-]*\s+){{0,6}}?){re.escape(head)}s?(?![\w-])", src, re.I):
        pre = m.group("pre")
        # a head inside a capitalised name is the "name ending in the head" case, handled below
        if head[:1].upper() + head[1:] == src[m.start("pre") + len(pre):m.start("pre") + len(pre) + len(head)]:
            continue
        desc = (pre + head).lower()
        if any(mod not in desc.split() for mod in mods):
            continue
        tail = src[m.end():]
        sep = _NAMED_AFTER.match(tail)
        if not sep:
            continue
        name = _name_at(src, m.end() + sep.end())
        if name:
            found[name.lower()] = name
    for m in re.finditer(rf"((?:[A-Z][\w–&'’-]*\s+){{1,7}}){head[:1].upper() + head[1:]}(?![\w-])", src):
        found[(m.group(0)).lower()] = m.group(0).strip()
    names = list(found.values())
    # one name, or one that contains all the others ("Viksit Bharat G RAM G" inside the long form)
    if not names:
        return None
    longest = max(names, key=len)
    if all(n.lower() in longest.lower() for n in names):
        return longest
    return None


_DEVA = re.compile(r"[\u0900-\u097F]")


def is_hindi(source: str) -> bool:
    """A source article written (mostly) in Devanagari: its words cannot be matched letter for letter by English names."""
    s = source or ""
    return len(_DEVA.findall(s)) > 0.3 * max(1, len(re.findall(r"[A-Za-z\u0900-\u097F]", s)))


def _like_in_hindi(gloss: str, source: str) -> bool:
    """Every name word and figure of an English gloss has a Devanagari word of the source it can be (the project's
    cross-script name matching, textmatch._roman / _like: \"Rozgar\" ~ \"रोजगार\"). A name the article does not have fails."""
    from .textmatch import DEVA_DIGITS, _like, _roman
    src_words = [_roman(w) for w in re.findall(r"[\u0900-\u097F]+|[A-Za-z]+", source)]
    src_words = [w for w in src_words if w]
    src_digits = set(re.findall(r"\d+", (source or "").translate(DEVA_DIGITS).replace(",", "")))
    names = [t for t in re.findall(r"[A-Z][A-Za-z–'’-]{2,}|\d+", gloss) if t.lower() not in _CONNECT]
    if not names:
        return False
    for t in names:
        if t.isdigit():
            if t not in src_digits:
                return False
            continue
        r = _roman(t)
        if not r or not any(_like(r, w) for w in src_words):
            return False
    return True


def in_source(gloss: str, source: str) -> bool:
    if not gloss:
        return False
    if is_hindi(source):
        return not _DEVA.search(gloss) and _like_in_hindi(gloss, source)    # English letters, the article's own name
    return _norm(gloss) in _norm(source)


def usable_gloss(gloss: str | None, phrase: str, source: str) -> str | None:
    """A gloss is kept only when its words stand in the source, it has a name or a figure in it (a capital or a
    digit), is not the phrase again, and is short enough to sit in a bracket."""
    g = _norm(gloss or "").strip(" .,;:\"'")
    if not g or len(g.split()) > 22 or g.lower() == _norm(phrase).lower():
        return None
    if not in_source(g, source):
        return None
    if not re.search(r"[A-Z0-9]", g[1:] if g[:1].isupper() and len(g.split()) == 1 else g):
        return None
    if re.fullmatch(r"(?i)(?:the|a|an|this|that)?\s*(?:" + _HEAD_ALT + r")s?", g):
        return None
    return g


_SPEECH = r"(?:said|says|told|stated|states|added|noted|informed|announced|clarified|confirmed|explained|asserted|" \
          r"stressed|emphasised|emphasized|alleged|claimed|argued|replied|responded|maintained|mentioned)"


def subject_is_speaker(text: str, speaker: str, source: str) -> str | None:
    """The statement opens with a subject pronoun ("It was trying to ...") and has a named speaker: the speaker, when
    the source itself writes "<speaker> said (that) it was trying to ..." (owner, Oct 15 2026: reading moves the
    speaker out of the sentence, so the speaker-subject became "It"). Returns the sentence with the speaker as
    subject, or None."""
    m = PRON_OPEN.match((text or "").strip())
    sp = _norm(speaker)
    if not m or not sp or not sp[:1].isupper() or re.search(r"(?i)^(article|unknown|unnamed|none)", sp):
        return None
    pron, rest = m.group("p"), m.group("rest")
    if pron.lower() not in {"it", "they", "he", "she"}:
        return None
    lead = " ".join(rest.split()[:3])
    if len(lead) < 6:
        return None
    src = _norm(source)
    key = sp.split()[-1] if len(sp.split()) > 1 and re.match(r"(?i)^(the|mr|mrs|ms|dr|shri)$", sp.split()[0]) is None \
        and len(sp) > 40 else sp
    for hit in re.finditer(rf"(?<![\w'’-])(?:{pron})\s+{re.escape(lead)}", src, re.I):
        window = src[max(0, hit.start() - 220):hit.start()]
        if re.search(rf"{re.escape(key)}[^.]{{0,160}}?\b{_SPEECH}\b[^.]{{0,25}}$", window, re.I):
            subject = re.sub(r"^the\s+", "The ", sp) if sp.lower().startswith("the ") else sp
            return subject + rest
    return None


def resolve_item(item: dict, source: str) -> dict:
    """Layer A for one extracted statement: what changed ({"text": new} / "refs": [...]) and what is still open. A Hindi
    source is not searched by code (the patterns are English: a pronoun is left open and counted, a name is asked for)."""
    text = item.get("text") or ""
    out: dict = {"refs": [], "open": []}
    hindi = is_hindi(source)
    new = None if hindi else subject_is_speaker(text, item.get("attributed_to") or "", source)
    if new:
        out["text"] = new
        text = new
    elif PRON_OPEN.match(text.strip()) and not EXPLETIVE.match(text.strip()):
        out["open"].append({"phrase": PRON_OPEN.match(text.strip()).group("p"), "kind": "pronoun"})
    for ref in definite_phrases(text):
        g = None if hindi else usable_gloss(find_antecedent(ref, source), ref["phrase"], source)
        if g:
            out["refs"].append({"phrase": ref["phrase"], "gloss": g, "how": "code"})
        else:
            out["open"].append({"phrase": ref["phrase"], "kind": "definite", "head": ref["head"],
                                "mods": ref["mods"]})
    return out


ASK_PROMPT_HI = """Below is a news ARTICLE in Hindi, and some PHRASES (in English) copied from sentences that were taken out of
it. Each phrase points back to one particular thing (a scheme, a bill, a video, a case ...) that the article names or
describes somewhere else. For each phrase, find the name the article gives that thing and write it in ENGLISH LETTERS,
spelled the way the article's Hindi words sound ("रोजगार" = "Rozgar"). Write only the name the article uses: never
translate it into other English words, never add words. If the article does not say, or two different things could be
meant, answer null.

ARTICLE:
\"\"\"{article}\"\"\"

PHRASES:
{phrases}

Reply with JSON only: {{"1": "name in English letters or null", "2": "..."}}"""


ASK_PROMPT = """Below is a news ARTICLE, and some PHRASES copied from sentences taken out of it. Each phrase points back to
one particular thing (a scheme, a bill, a video, a case ...) that the article names or describes somewhere else.
For each phrase, copy from the ARTICLE the exact words that name that thing: its own name, or its full description.
Copy only words that stand in the article, letter for letter. Never write words of your own.
If the article does not say, or two different things could be meant, answer null.

Example. Article: "The Cabinet approved a new rural employment guarantee scheme, Viksit Bharat-G RAM G, in December, replacing
the old scheme." Phrase "the new scheme" -> "Viksit Bharat-G RAM G".
Trap. Article names two schemes (a pension scheme and a housing scheme). Phrase "the scheme" -> null.

ARTICLE:
\"\"\"{article}\"\"\"

PHRASES:
{phrases}

Reply with JSON only: {{"1": "exact words or null", "2": "exact words or null"}}"""


def ask_model(router, open_refs: list[tuple[dict, dict]], source: str, max_chars: int = 9000) -> int:
    """Layer A, the part code cannot do: ONE batched call per article for the references still open. `open_refs` is
    [(item resolution, open entry)]. An answer is kept only through `usable_gloss`: its words must stand in the
    source. Returns how many were resolved. A failed call resolves nothing (the references stay open and are
    counted)."""
    todo = [(res, o) for res, o in open_refs if o.get("kind") == "definite"][:8]
    if not todo:
        return 0
    prompt = (ASK_PROMPT_HI if is_hindi(source) else ASK_PROMPT).format(article=_norm(source)[:max_chars],
                               phrases="\n".join(f'{n + 1}. "{o["phrase"]}"' for n, (_, o) in enumerate(todo)))
    try:
        res = router.call("bulk", prompt, json_out=True, max_output_tokens=600)
        data = res.data if isinstance(res.data, dict) else {}
    except Exception as e:  # noqa: BLE001 - a missing answer leaves the reference open, never stops reading
        log.info("refs: model question failed (%s)", str(e)[:100])
        return 0
    got = 0
    for n, (resolution, o) in enumerate(todo):
        g = usable_gloss(data.get(str(n + 1)), o["phrase"], source)
        if g:
            resolution["refs"].append({"phrase": o["phrase"], "gloss": g, "how": "model"})
            resolution["open"].remove(o)
            got += 1
    return got


def resolve_extraction(ex: dict, source: str, router=None) -> dict:
    """Layer A for a whole reading (`extract.normalize_extraction` output): rewrites statement text where the
    pronoun is provably the speaker, adds `refs` to statements with a generic reference the source names, and
    returns the counts. Never drops a statement."""
    stats = {"speaker": 0, "glossed": 0, "asked": 0, "open": 0}
    pending: list[tuple[dict, dict]] = []
    for key in ("events", "claims", "context"):
        for it in ex.get(key) or []:
            res = resolve_item(it, source)
            if res.get("text"):
                it["text"] = res["text"][:500]
                stats["speaker"] += 1
            if res["refs"]:
                it["refs"] = res["refs"]
                stats["glossed"] += len(res["refs"])
            for o in res["open"]:
                pending.append((res, o))
            it["_res"] = res
    if router is not None and pending:
        stats["asked"] = ask_model(router, pending, source)
    for key in ("events", "claims", "context"):
        for it in ex.get(key) or []:
            res = it.pop("_res", None) or {}
            if res.get("refs"):
                it["refs"] = res["refs"]
            if res.get("open"):
                it["refs_open"] = [{k: v for k, v in o.items() if k in ("phrase", "kind")} for o in res["open"]]
                stats["open"] += len(res["open"])
    stats["glossed"] = sum(len(it.get("refs") or []) for k in ("events", "claims", "context") for it in ex.get(k) or [])
    return stats


# ----- B. writing: the bracket, in reading order -----------------------------------------------------------------

_TOKENS = re.compile(r"[A-Z][\w–&'’-]*|\d[\d,.]*")


def _name_tokens(gloss: str) -> set[str]:
    return {t.lower() for t in _TOKENS.findall(gloss) if len(t) > 2 or t.isdigit()}


def _told(gloss: str, told: str) -> bool:
    """Does what the reader has read already carry the name? (all its capitalised words / figures)"""
    toks = _name_tokens(gloss)
    low = told.lower()
    return bool(toks) and all(t in low for t in toks)


def bracket(gloss: str) -> str:
    """Round brackets; square ones when the name has round brackets of its own."""
    return f"[{gloss}]" if "(" in gloss else f"({gloss})"


def gloss_text(text: str, refs: list[dict], told: str, done: set[str]) -> tuple[str, int]:
    """One sentence (or coloured part): the name in brackets after the first written mention of each thing the
    reader has not been told about. `told` is the headline and every sentence before; `done` holds glosses already
    given. Never inside quoted words, never twice."""
    n = 0
    quotes = [(m.start(), m.end()) for m in _QUOTE.finditer(text)]
    for r in refs:
        g, phrase = r.get("gloss"), r.get("phrase")
        if not g or not phrase or g.lower() in done:
            continue
        m = re.search(rf"(?<![\w'’-]){re.escape(phrase)}(?![\w-])", text, re.I)
        if not m or any(a <= m.start() < b for a, b in quotes):
            continue
        if text[m.end():].lstrip().startswith(("(", "[")) or _told(g, told + " " + text[:m.start()] + text[m.end():]):
            done.add(g.lower())
            continue
        text = text[:m.end()] + " " + bracket(g) + text[m.end():]
        done.add(g.lower())
        n += 1
    return text, n


def gloss_article(paragraphs: list[list[dict]], headline: str, refs_of) -> dict:
    """Layer B over a finished article (the paragraphs `style.polish` works on). `refs_of(sentence)` gives the refs of
    the statements a sentence is made of. Counts what it did and what is left: a generic reference nothing before it
    introduces and no statement has a name for (`unresolved`, for replay; not enforced)."""
    told = headline or ""
    done: set[str] = set()
    glossed = 0
    unresolved: list[str] = []
    for para in paragraphs:
        for sent in para:
            refs = refs_of(sent) or []
            pieces = sent.get("parts") or [sent]
            for piece in pieces:
                piece["text"], n = gloss_text(piece["text"], refs, told, done)
                glossed += n
            if sent.get("parts"):
                sent["text"] = " ".join(p["text"].strip() for p in sent["parts"])
            for ref in definite_phrases(sent["text"]):
                words = [w for w in ref["mods"] + [ref["head"]] if w]
                if ref["det"] in {"the", "this", "that", "these", "those"} and not all(
                        re.search(rf"(?<![\w-]){re.escape(w)}", told, re.I) for w in words) \
                        and not any(r.get("phrase", "").lower() == ref["phrase"].lower() for r in refs) \
                        and not re.match(r"\s*[(\[]", sent["text"][ref["end"]:]):
                    unresolved.append(ref["phrase"])
            told += " " + sent["text"]
    return {"glossed": glossed, "unresolved": unresolved[:20]}


# ----- C. writing: how a paragraph opens ----------------------------------------------------------------------------

def opening_problem(text: str) -> str | None:
    """\"opens with a pronoun\" when a sentence that opens a paragraph starts with It / They / This / These / Those /
    Its / Their (nothing in the paragraph is before it to point at). Expletive \"It is not clear whether ...\" is fine."""
    t = (text or "").strip()
    m = OPEN_PRON.match(t)
    if not m or EXPLETIVE.match(t) or RAIN.match(t):
        return None
    return "opens with a pronoun"


def repair_opening(text: str, speaker_names: set[str]) -> str | None:
    """\"It was trying to trace the video, Election Commission of India said.\" -> \"Election Commission of India said it
    was trying to trace the video.\" Only the trailing-attribution shape, only when the trailing speaker is one of the
    statements' own speakers, only It / They (a pronoun with the speaker for antecedent). The caller checks the result
    again with every check."""
    from .voice import SAY_VERB
    t = (text or "").strip()
    m = OPEN_PRON.match(t)
    if not m or m.group("p").lower() not in {"it", "they"}:
        return None
    tail = re.search(rf",\s+(?P<who>[\w.'’ -]{{2,80}}?)\s+(?P<verb>{SAY_VERB})(?P<day>\s+on\s+\w+(?:\s+\d+)?)?\s*(?P<end>[.!?])[\"”]?$", t)
    if not tail:
        return None
    who = tail.group("who").strip()
    if not any(who.lower() == s.lower() or who.lower() in s.lower() or s.lower() in who.lower() for s in speaker_names if s):
        return None
    body = t[:tail.start()].rstrip(" ,")
    pron = m.group("p").lower()
    rest = body[len(m.group("p")):].lstrip()
    return f"{who} {tail.group('verb')}{tail.group('day') or ''} {pron} {rest}{tail.group('end')}"


# ----- C2. writing: a pronoun in the middle of a paragraph --------------------------------------------------------------

_PRON_ANY = re.compile(r"(?<![\w'’-])(?:It|it|They|they|Its|its|Their|their)(?![\w'’-])")
_FUNCTION_CAPS = {"It", "They", "He", "She", "We", "I", "This", "These", "Those", "That", "There", "Here", "However",
                  "Meanwhile", "Later", "Earlier", "Then", "Also", "And", "But", "Or", "So", "On", "In", "At", "After",
                  "Before", "During", "Since", "While", "When", "As", "If", "Following", "According", "Yesterday",
                  "Today", "Tomorrow", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
                  "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                  "November", "December", "Its", "Their", "His", "Her", "Our", "Your", "My", "Both", "Some", "Many",
                  "Most", "All", "One", "Two", "Three", "Another", "Other", "Such", "Not", "No", "Yes", "What",
                  "Why", "How", "Where", "Who", "Which", "For", "From", "With", "By", "To", "Of", "Under", "Over",
                  "Despite", "Although", "Though", "Because", "Until", "Once", "Now", "Still", "Even", "Only", "Just"}
_NP = re.compile(r"(?<![\w'’-])(?:the|The|a|A|an|An)\s+[A-Za-z][a-z-]{2,}")


def _has_candidate(window: str) -> bool:
    """Does the text carry a name or a noun phrase a pronoun could point to?"""
    if _NP.search(window):
        return True
    return any(w not in _FUNCTION_CAPS for w in re.findall(r"(?<![\w'’-])[A-Z][\w&-]+", window))


def antecedent_problem(text: str, near: str | None) -> str | None:
    """\"pronoun without antecedent\": an It / They / Its / Their in a sentence with nothing before it (in the sentence or
    in `near`: the sentence before and the speaker in scope) that it could mean. Narrow on purpose: any name or
    \"the + noun\" before it counts as something to point to (the check refuses only what points at nothing).
    `near` None = position unknown (a changed sentence being re-checked): not asked."""
    if near is None:
        return None
    t = (text or "").strip()
    quotes = [(m.start(), m.end()) for m in _QUOTE.finditer(t)]
    for m in _PRON_ANY.finditer(t):
        if any(a <= m.start() < b for a, b in quotes):
            continue
        if m.start() == 0 and (EXPLETIVE.match(t) or RAIN.match(t)):
            continue
        window = (near or "") + " " + t[:m.start()]
        if not _has_candidate(window):
            return "pronoun without antecedent"
    return None

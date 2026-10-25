"""Who said it, read from the dependency parse (B18; replaces the CHAIN / BODY_LEAD / PRON_ATTRIB regexes of style.py).

A sentence that is only an attribution ("Kabir also stated on Monday that the road is shut." or "The road is shut,
Kabir said.") is read as its parts: the subject (who), the speech verb, an adverb ("also", "further"), the extras that
hang on the verb ("on Monday"), the reported clause (body) and the end mark. Code then writes the form it wants
(`trailing`, `lead`) from the parts instead of matching a pattern over the surface. A sentence that is anything more
than that (a second clause, a quotation, words the parse does not place) is not read at all: `read` returns None and the
caller leaves the sentence alone. Needs the parse; no parse = None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import nlp

ADVERBS = {"also", "further", "then", "later", "additionally"}
QUOTES = re.compile(r"[\"“”]")
# the verb a speech act is written with: neutral ones become "said" when the form is rebuilt
NEUTRAL_LEMMA = {"state", "mention", "remark", "assert", "note"}


@dataclass(frozen=True)
class Speech:
    subject: str
    verb: str                 # as written
    lemma: str
    adverb: str               # "" or the adverb as written
    extras: str               # "on Monday" or ""
    body: str
    end: str
    subject_first: bool
    pronoun: bool
    verb_span: tuple[int, int]
    adverb_span: tuple[int, int] | None


def _subtree(toks, i: int) -> set[int]:
    kids: dict[int, list[int]] = {}
    for t in toks:
        if t.head != t.i:
            kids.setdefault(t.head, []).append(t.i)
    out, stack = set(), [i]
    while stack:
        n = stack.pop()
        if n in out:
            continue
        out.add(n)
        stack.extend(kids.get(n, []))
    return out


def _speech_verb(toks):
    root = next((t for t in toks if t.dep == "ROOT" or t.head == t.i and t.pos == "VERB"), None)
    if root is None or root.lemma not in nlp.SPEECH_LEMMA or not root.tag.startswith("VB"):
        return None
    return root


def has_speech(text: str) -> bool:
    """Does the sentence contain a speech verb that has a subject (an attribution)?"""
    toks = nlp.parse(text)
    if not toks:
        return False
    return any(t.lemma in nlp.SPEECH_LEMMA and t.tag.startswith("VB")
               and any(c.head == t.i and c.dep in ("nsubj", "nsubjpass") for c in toks) for t in toks)


def read(text: str) -> Speech | None:
    toks = nlp.parse(text)
    if not toks or QUOTES.search(text):
        return None
    verb = _speech_verb(toks)
    if verb is None:
        return None
    subj = next((t for t in toks if t.head == verb.i and t.dep == "nsubj"), None)
    comp = next((t for t in toks if t.head == verb.i and t.dep == "ccomp"), None)
    if subj is None or comp is None:
        return None
    s_idx, b_idx = _subtree(toks, subj.i), _subtree(toks, comp.i)
    extras_idx: set[int] = set()
    for t in toks:
        if t.head == verb.i and t.dep == "prep":
            extras_idx |= _subtree(toks, t.i)
    used = s_idx | b_idx | {verb.i} | extras_idx
    adverb, end = None, ""
    for t in toks:
        if t.i in used:
            continue
        if t.dep == "punct" and t.text in ".!?" and t.i == toks[-1].i:
            end = t.text
        elif t.dep == "punct" and t.text == ",":
            continue
        elif t.head == verb.i and t.dep == "advmod" and t.text.lower() in ADVERBS and adverb is None:
            adverb = t
        else:
            return None                       # a word the parse does not place in an attribution: leave the sentence alone
    body_toks = sorted(b_idx)
    while body_toks and toks[body_toks[0]].dep == "mark":
        body_toks = body_toks[1:]
    if not body_toks:
        return None
    first, last = toks[body_toks[0]], toks[body_toks[-1]]
    body = text[first.start:last.end].strip(" ,;:")
    st = sorted(s_idx)
    subject = text[toks[st[0]].start:toks[st[-1]].end]
    ex = sorted(extras_idx)
    extras = text[toks[ex[0]].start:toks[ex[-1]].end] if ex else ""
    return Speech(subject=subject, verb=verb.text, lemma=verb.lemma, adverb=adverb.text if adverb else "",
                  extras=extras, body=body, end=end or ".", subject_first=subj.i < comp.i,
                  pronoun=subject.lower() in ("he", "she", "they"),
                  verb_span=(verb.start, verb.end), adverb_span=(adverb.start, adverb.end) if adverb else None)


def written_verb(sp: Speech, plain_added: bool = False) -> str:
    """The verb to write: the outlets' own for an act ("alleged", "claimed"), "said" for the neutral ones."""
    if sp.lemma in NEUTRAL_LEMMA:
        return "said"
    if plain_added and sp.lemma == "add":
        return "said"
    return sp.verb


def trailing(sp: Speech, ref: str, plain_added: bool = False) -> str:
    """The attribution moved to the end: "Body, ref said on Monday."."""
    body = sp.body.rstrip(",;: ")
    extras = f" {sp.extras}" if sp.extras else ""
    return f"{body[:1].upper()}{body[1:]}, {ref} {written_verb(sp, plain_added)}{extras}{sp.end}"


def without_adverb(text: str, sp: Speech, plain_added: bool = True) -> str:
    """"Kabir also stated that ..." -> "Kabir said that ...": the adverb goes, a neutral verb becomes "said"."""
    edits = [(sp.verb_span, written_verb(sp, plain_added))]
    if sp.adverb_span:
        a, b = sp.adverb_span
        edits.append(((a, b + 1 if text[b:b + 1] == " " else b), ""))
    for (a, b), rep in sorted(edits, reverse=True):
        text = text[:a] + rep + text[b:]
    return text


def pronoun_subjects(text: str) -> list[tuple[int, int, str]]:
    """Every he / she that is the subject of a speech verb: (start, end, word) in the text."""
    toks = nlp.parse(text)
    if not toks:
        return []
    out = []
    for t in toks:
        if t.dep == "nsubj" and t.text.lower() in ("he", "she") and toks[t.head].lemma in nlp.SPEECH_LEMMA:
            out.append((t.start, t.end, t.text))
    return out

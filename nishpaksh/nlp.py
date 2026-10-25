"""The linguistic analyser (B1, B2, B9, B27): spaCy, loaded once, used by entities, references and claim splitting.

Named-entity recognition and the dependency parse come from an established English pipeline (en_core_web_lg; the small
model labelled "Mamata Banerjee" an organisation in a first trial and the large one does not), not from word lists.
Anything that cannot load returns None / [] and the caller treats the text as "not analysed", never as "nothing there".
`set_backend(fn)` replaces the analyser in tests: fn(text) -> list of Ent.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass

log = logging.getLogger("nishpaksh.nlp")

MODELS = (os.getenv("NISHPAKSH_SPACY_MODEL") or "en_core_web_lg", "en_core_web_sm")
PERSON = "PERSON"
NOT_PERSON_LABELS = {"ORG", "GPE", "LOC", "NORP", "FAC", "EVENT", "LAW", "PRODUCT", "WORK_OF_ART", "LANGUAGE"}

_backend = None
_nlp = None
_lock = threading.Lock()
_cache: dict[str, list] = {}


@dataclass(frozen=True)
class Ent:
    text: str
    label: str
    start: int
    end: int


def set_backend(fn) -> None:
    global _backend
    _backend = fn
    _cache.clear()


def pipeline():
    """The loaded spaCy pipeline, or None when no model can be loaded."""
    global _nlp
    with _lock:
        if _nlp is None:
            _nlp = False
            try:
                import spacy
                for name in MODELS:
                    try:
                        _nlp = spacy.load(name)
                        break
                    except Exception as e:  # noqa: BLE001
                        log.warning("spaCy model %s unavailable: %s", name, str(e)[:120])
            except Exception as e:  # noqa: BLE001
                log.warning("spaCy unavailable: %s", str(e)[:120])
        return _nlp or None


def available() -> bool:
    return _backend is not None or pipeline() is not None


def ents(text: str) -> list[Ent]:
    """Named entities of a text (cached)."""
    if not text:
        return []
    if text in _cache:
        return _cache[text]
    if _backend is not None:
        out = list(_backend(text))
    else:
        nlp = pipeline()
        if nlp is None:
            return []
        doc = nlp(text[:100_000])
        out = [Ent(e.text, e.label_, e.start_char, e.end_char) for e in doc.ents]
    if len(_cache) > 2000:
        _cache.clear()
    _cache[text] = out
    return out


# ------------------------------------------------------------------ the parse, as plain tokens (agreement, references)
@dataclass(frozen=True)
class Tok:
    i: int
    text: str
    start: int
    end: int
    lemma: str
    tag: str
    pos: str
    dep: str
    head: int


_parser = None
_parse_cache: dict[str, list] = {}


def set_parser(fn) -> None:
    """Tests: fn(text) -> list[Tok] (or None)."""
    global _parser
    _parser = fn
    _parse_cache.clear()


def parse(text: str) -> list[Tok] | None:
    """The tokens of ONE sentence with tag, part of speech, dependency label and head; None when not analysed."""
    if not text:
        return None
    if text in _parse_cache:
        return _parse_cache[text]
    if _parser is not None:
        out = _parser(text)
    else:
        nlp = pipeline()
        if nlp is None:
            return None
        doc = nlp(text[:5_000])
        out = [Tok(t.i, t.text, t.idx, t.idx + len(t.text), t.lemma_.lower(), t.tag_, t.pos_, t.dep_, t.head.i) for t in doc]
    if len(_parse_cache) > 2000:
        _parse_cache.clear()
    _parse_cache[text] = out
    return out


def noun_chunks(text: str) -> list[tuple[int, int, str, str, str, str]] | None:
    """(start, end, text, head lemma, head tag, head entity label) of each noun phrase; None when not analysed.
    Tests: set_chunker."""
    if not text:
        return None
    if _chunker is not None:
        return _chunker(text)
    nlp = pipeline()
    if nlp is None:
        return None
    doc = nlp(text[:5_000])
    return [(c.start_char, c.end_char, c.text, c.root.lemma_.lower(), c.root.tag_, c.root.ent_type_) for c in doc.noun_chunks]


_chunker = None


def set_chunker(fn) -> None:
    global _chunker
    _chunker = fn


# ------------------------------------------------------------------ clauses (B27): a dependency parse, not a word list
SPEECH_LEMMA = {"say", "tell", "state", "claim", "allege", "add", "note", "announce", "confirm", "deny", "warn",
                "argue", "report", "assert", "insist", "explain", "mention", "remark", "stress", "reveal"}


def _text(tokens) -> str:
    toks = sorted(tokens, key=lambda t: t.i)
    while toks and (toks[0].dep_ in ("cc", "punct") or toks[0].lower_ in ("and", "but", "while", "as")):
        toks = toks[1:]
    while toks and toks[-1].dep_ == "punct" and toks[-1].text not in ")\"'”":
        toks = toks[:-1]
    s = " ".join(t.text for t in toks)
    s = re.sub(r"\s+([,.;:!?)%\]”])", r"\1", s)
    s = re.sub(r"([(\[“])\s+", r"\1", s)
    s = re.sub(r"\s+(['’]s|n['’]t|['’])\b", r"\1", s)
    s = re.sub(r"\s+-\s+", "-", s).strip().rstrip(",;")
    return (s[:1].upper() + s[1:] + ".") if s else ""


def clauses(text: str) -> list[str] | None:
    """The separate clauses of ONE sentence as full sentences, or None when it is one fact (or cannot be parsed).
    Coordinated verbs become separate clauses, each with the subject it needs; a reported clause ("X said A and B")
    keeps its speaker in every piece; a relative clause is a clause of its own with the noun it describes."""
    nlp = pipeline()
    if nlp is None or not text:
        return None
    doc = nlp(text)
    sents = list(doc.sents)
    if len(sents) != 1:
        return None
    root = sents[0].root

    def subj(v):
        for c in v.children:
            if c.dep_ in ("nsubj", "nsubjpass"):
                return c
        return None

    def own(v, others):
        """v's subtree without the subtrees of the other verbs of the same coordination (and their conjunctions)."""
        drop = set()
        inside = {t.i for t in v.subtree}
        for o in others:
            if o is not v and o.i in inside:                  # a coordinated verb hangs under the first one
                drop |= {t.i for t in o.subtree}
                drop |= {c.i for c in o.head.children if c.dep_ in ("cc", "punct") and v.i < c.i < o.i}
        return [t for t in v.subtree if t.i not in drop]

    # find the verb whose coordination to split: the root, or the clause a speech verb reports
    prefix: list = []
    core = root
    if root.lemma_ in SPEECH_LEMMA or root.lemma_.lower() in SPEECH_LEMMA:
        rep = next((c for c in root.children if c.dep_ in ("ccomp", "xcomp")), None)
        if rep is not None:
            core = rep
            prefix = [t for t in root.subtree if t.i not in {x.i for x in rep.subtree} and t.dep_ != "punct"]
            if rep.i > root.i:
                prefix = [t for t in prefix if t.lower_ != "that"]
    verbs = [core] + [c for c in core.conjuncts if c.pos_ in ("VERB", "AUX") and c.i > core.i]
    pieces: list[str] = []
    if len(verbs) >= 2:
        s0 = subj(core)
        for v in verbs:
            toks = own(v, verbs)
            if subj(v) is None and s0 is not None and v is not core:
                have = {x.i for x in s0.subtree}
                aux = [c for c in core.children if c.dep_ in ("auxpass", "aux") and not any(
                    k.dep_ in ("auxpass", "aux") for k in v.children)] if v.tag_ in ("VBN", "VBD") else []
                toks = sorted(list(s0.subtree) + aux, key=lambda t: t.i) + [t for t in toks if t.i not in have]
            piece = _text(prefix + toks) if prefix else _text(toks)
            pieces.append(piece)
    else:
        rel = [t for t in doc if t.dep_ == "relcl" and any(c.tag_ in ("WDT", "WP") for c in t.children)]
        if rel:
            v = rel[0]
            noun = [t for t in sorted(v.head.subtree, key=lambda t: t.i) if t.i < v.left_edge.i and t.dep_ != "punct"]
            noun = [t for t in noun if t.i >= v.head.left_edge.i]
            inner = [t for t in sorted(v.subtree, key=lambda t: t.i) if t.tag_ not in ("WDT", "WP")]
            main = [t for t in doc if t.i not in {x.i for x in v.subtree} and t.dep_ != "punct" or t.i == v.head.i]
            pieces = [_text(main), _text(noun + inner) if noun else ""]
    pieces = [p for p in pieces if len(p.split()) >= 3]
    return pieces if len(pieces) >= 2 else None

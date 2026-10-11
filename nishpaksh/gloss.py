"""Context in brackets for someone who appears before the reader knows who they are (owner, Oct 11 2026).

"Dipke urged the mother not to cry" came before anything said whose mother. The fix is by code, in reading order:

    relations   "the mother", "the wife": the first time one is written WITHOUT saying whose (no "Dipke's mother",
                "mother of Dipke") the article adds the descriptor the outlets gave in brackets: "the mother
                (Abhijeet Dipke's mother)". Once linked or glossed, later mentions stay bare.
    roles       a speaker the outlets give only by an office ("Delhi Chief Minister", "Delhi Police spokesperson"):
                the first time the sentence writes the office WITHOUT its scope ("the chief minister"), the
                scoped form is added in brackets. A title that carries its own scope ("Delhi CM", "Union Home
                Minister", "Chief Minister of Delhi") needs nothing: titles.is_scoped decides.

Named people are not handled here: style.shorten_names introduces them with title and full name.
Evidence only: the descriptor is a speaker or a statement the outlets wrote. When two different people fill the same
relation ("the mother" of Dipke and of someone else), or no outlet says whose, nothing is added: never a guess.
Quoted words are never touched. Pure code, no model.
"""
from __future__ import annotations

import re

from . import titles as _titles

# relations a story's people are named by; add a word here to cover more ("the nephew")
KIN = ("mother", "father", "wife", "husband", "son", "daughter", "brother", "sister", "parents", "family", "relatives",
       "lawyer", "aide")
_KIN = "|".join(KIN)
_OPEN = {"The", "A", "An", "While", "Meanwhile", "When", "After", "Before", "On", "In", "At", "By", "For", "From",
         "According", "However", "But", "And", "Also", "Later", "Earlier", "Then", "Since", "As", "If", "With",
         "Expressing", "Speaking", "Addressing", "Reacting", "Dr", "Mr", "Mrs", "Ms", "Shri", "Smt"}
_POSS = re.compile(rf"((?:[A-Z][\w.-]*\s+){{0,3}}[A-Z][\w.-]*)['’]s\s+({_KIN})\b")
_BARE = re.compile(rf"(?<![\w'’-])([Tt]he\s+({_KIN}))\b(?!\s+of\b)(?!['’]s\b)")
_OF = re.compile(rf"\b({_KIN})\s+of\s+(?:the\s+)?[A-Z]")
_PRON = re.compile(rf"\b(?:[Hh]is|[Hh]er|[Tt]heir)\s+({_KIN})\b")
_QUOTE = re.compile(r'"[^"]*"|“[^”]*”')


def _clean_poss(poss: str) -> str:
    words = poss.split()
    while words and words[0] in _OPEN:
        words = words[1:]
    return " ".join(words)


def descriptors(speakers: list[str], texts: list[str], names: dict[str, str] | None = None) -> dict[str, str]:
    """{relation noun: "Abhijeet Dipke's mother"}: whose relation each is, from what the outlets wrote (a speaker or
    a statement). Left out when the outlets name two different people for the same relation."""
    names = names or {}
    by_sur = {short.lower(): full for full, short in names.items()}
    found: dict[str, dict[str, str]] = {}
    for t in [*speakers, *texts]:
        for m in _POSS.finditer(t or ""):
            poss = _clean_poss(m.group(1))
            if not poss:
                continue
            key = poss.split()[-1].lower()
            noun = m.group(2).lower()
            have = found.setdefault(noun, {})
            if len(poss) > len(have.get(key, "")):
                have[key] = poss
    out = {}
    for noun, who in found.items():
        if len(who) != 1:
            continue                                       # two different people: no guess
        (key, poss), = who.items()
        if " " not in poss and key in by_sur:
            poss = by_sur[key]                             # a surname the article knows in full
        out[noun] = f"{poss}'s {noun}"
    return out


def _linked(descriptor: str, sentence: str, upto: int) -> bool:
    """Does the sentence, before position `upto`, name the possessor of this descriptor?"""
    key = descriptor.split("'")[0].split()[-1]
    return bool(re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", sentence[:upto]))


def _role_of_speaker(speaker: str, context: str) -> str | None:
    words = speaker.split()
    for i in range(len(words)):
        r = _titles.role_of(" ".join(words[i:]), context)
        if r:
            return r
    return None


def _role_entities(speakers: list[str], names: dict[str, str], context: str) -> dict[str, str]:
    """{speaker string: role id} for speakers the outlets give only by an office, with a scope of their own."""
    from .style import _candidates
    out = {}
    for s in dict.fromkeys(x for x in speakers if x):
        if "'" in s or "’" in s or _candidates(s) or any(full in s or short in s.split() for full, short in names.items()):
            continue                                       # a named person or a relation: not an office alone
        rid = _role_of_speaker(s, context)
        if rid and _titles.is_scoped(s):
            out[s] = rid
    return out


def _mentions(sentence: str, forms: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, phrase) of each written form of a role, the phrase widened to the capitalised words before it
    (\"Delhi\" in \"Delhi chief minister\"). A form followed by a capitalised word is a titled name: not a mention."""
    out = []
    pat = re.compile(r"(?<![\w'’-])(?:" + "|".join(re.escape(f) for f in forms) + r")(?![\w-])", re.I)
    for m in pat.finditer(sentence):
        if re.match(r"\s+[A-Z][a-z]", sentence[m.end():]):
            continue
        start = m.start()
        head = sentence[:start]
        take = []
        for w in reversed(head.rstrip(" ").split(" ")):
            bare = w.strip(",;:()")
            if bare[:1].isupper() and bare not in _OPEN and not w.endswith((",", ";", ":")) and len(take) < 3:
                take.append(bare)
            else:
                break
        phrase = " ".join(list(reversed(take)) + [sentence[start:m.end()]])
        tail = re.match(r"\s+of\s+(?:the\s+)?[A-Z][\w-]*", sentence[m.end():])      # \"Chief Minister of Delhi\"
        end = m.end() + (tail.end() if tail else 0)
        out.append((start - sum(len(t) + 1 for t in take), end, (phrase + (tail.group(0) if tail else "")).strip()))
    return out


def gloss_sentence(text: str, speakers: list[str], rel: dict[str, str], roles: dict[str, str], done: set[str]) -> str:
    """One sentence, or one coloured part of it: brackets added where the context is missing. `done` is what the
    reader has already been told (relations and offices), updated here."""
    quotes = [(m.start(), m.end()) for m in _QUOTE.finditer(text)]
    inside = lambda pos: any(a <= pos < b for a, b in quotes)           # noqa: E731
    events: list[tuple[int, int, str, str, str]] = []                    # (start, end, kind, key, extra)
    for m in _POSS.finditer(text):
        noun = m.group(2).lower()
        d = rel.get(noun)
        if d and _linked(d, m.group(0), len(m.group(0))):
            events.append((m.start(), m.end(), "linked", "rel:" + noun, ""))
    for m in _OF.finditer(text):
        if rel.get(m.group(1).lower()):
            events.append((m.start(), m.end(), "linked", "rel:" + m.group(1).lower(), ""))
    for m in _PRON.finditer(text):
        d = rel.get(m.group(1).lower())
        if d and _linked(d, text, m.start()):
            events.append((m.start(), m.end(), "linked", "rel:" + m.group(1).lower(), ""))
    for m in _BARE.finditer(text):
        d = rel.get(m.group(2).lower())
        if d and not inside(m.start()) and not text[m.end():].lstrip().startswith("("):
            events.append((m.start(), m.end(), "bare", "rel:" + m.group(2).lower(), d))
    for s, rid in roles.items():
        for a, b, phrase in _mentions(text, _titles.forms_of(rid)):
            if inside(a):
                continue
            if _titles.is_scoped(phrase) or text[b:].lstrip().startswith("("):
                events.append((a, b, "linked", "role:" + s, ""))
            elif len(s.split()) > len(phrase.split()):
                events.append((a, b, "bare", "role:" + s, s))
    inserts = []
    for a, b, kind, key, extra in sorted(events):
        if key in done:
            continue
        done.add(key)
        if kind == "bare":
            inserts.append((b, f" ({extra})"))
    for pos, add in sorted(inserts, reverse=True):
        text = text[:pos] + add + text[pos:]
    return text


def gloss(paragraphs: list[list[dict]], speakers_of, texts: list[str] = (), names: dict[str, str] | None = None) -> int:
    """Add the missing context in brackets, in reading order, to a finished article (the same paragraphs as
    style.shorten_names: sentences, or sentences in coloured `parts`). `speakers_of(sentence)` gives the speakers of
    the statements a sentence is made of; `texts` are the statements, the evidence for whose relation someone is.
    Returns how many brackets were added."""
    every = [s for p in paragraphs for sent in p for s in (speakers_of(sent) or []) if s]
    context = " ".join([*(sent["text"] for p in paragraphs for sent in p), *texts])
    rel = descriptors(every, list(texts), names)
    roles = _role_entities(every, names or {}, context)
    if not rel and not roles:
        return 0
    done: set[str] = set()
    added = 0
    for para in paragraphs:
        for sent in para:
            sp = [s for s in (speakers_of(sent) or []) if s]
            mine = {s: r for s, r in roles.items() if s in sp}      # only the offices this sentence's speakers hold
            before = sent["text"]
            if sent.get("parts"):
                for part in sent["parts"]:
                    part["text"] = gloss_sentence(part["text"], sp, rel, mine, done)
                sent["text"] = " ".join(p["text"].strip() for p in sent["parts"])
            else:
                sent["text"] = gloss_sentence(sent["text"], sp, rel, mine, done)
            added += sent["text"].count(" (") - before.count(" (")
    return added

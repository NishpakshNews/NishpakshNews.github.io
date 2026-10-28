"""Titles and roles: one registry (config/titles.yaml) instead of three private lists (owner, Oct 10 2026).

style.py, people.py and voice.py each kept their own idea of what a title is, and names went wrong in both
directions (a surname where the person had not been introduced; a full name or a title repeated). This module
is the single place they ask:

    role_of(phrase, context)     which role a written title is: "CJI" and "Chief Justice of India" are one role,
                                 "Chief Justice" alone is the CJI only in an article about the Supreme Court / India
    relation(a, b, context)      "same" (synonyms), "a_is_b" (a CJI is a Supreme Court judge), "b_is_a", or None
    ref_for(role)                how the article may point back at the person without a name ("the minister")
    title_before(text, name)     the title phrase written right before a name: "Assam Chief Minister"
    strip(phrase)                a name without its titles

Pure code, no model. The derived word sets (TITLE_WORDS, PERSON_TITLE_WORDS, ROLE_NOUNS, ROLE_ACRONYMS) are what the
other modules union into their own lists, so adding a title is one line in titles.yaml.
"""
from __future__ import annotations

import functools
import re

from .config import load_yaml


@functools.lru_cache(maxsize=1)
def _data() -> dict:
    d = load_yaml("titles.yaml")
    roles = {r["id"]: r for r in d.get("roles") or []}
    # form (lower case) -> role ids, in file order
    forms: dict[str, list[str]] = {}
    for rid, r in roles.items():
        for f in r.get("forms") or []:
            forms.setdefault(f.lower(), []).append(rid)
    return {"honorifics": list(d.get("honorifics") or []), "qualifiers": list(d.get("qualifiers") or []),
            "scope_words": list(d.get("scope_words") or []), "roles": roles, "forms": forms}


def honorifics() -> set[str]:
    return set(_data()["honorifics"])


def _words(form: str) -> list[str]:
    return [w for w in re.split(r"[\s]+", form) if w]


@functools.lru_cache(maxsize=1)
def title_words() -> frozenset[str]:
    """Every word that may sit in a title (honorifics, qualifiers, every word of every form), original case."""
    d = _data()
    out = set(d["honorifics"]) | set(d["qualifiers"])
    for r in d["roles"].values():
        for f in r.get("forms") or []:
            out.update(w.strip(".") for w in _words(f) if w.lower() not in ("of", "the", "and"))
    return frozenset(out)


@functools.lru_cache(maxsize=1)
def person_title_words() -> frozenset[str]:
    """Words whose presence before a name is EVIDENCE of a person: honorifics and the words of role forms,
    not the bare qualifiers (\"Union\", \"Deputy\", \"Air\", \"Chief\" alone prove nothing: Oct 7 2026, \"Commission for
    Air Quality Management\" became \"Commission for Management\")."""
    d = _data()
    out = set(d["honorifics"])
    quals = set(d["qualifiers"])
    for r in d["roles"].values():
        for f in r.get("forms") or []:
            for w in _words(f):
                w = w.strip(".")
                if w.lower() not in ("of", "the", "and") and (w not in quals or len(_words(f)) == 1):
                    out.add(w)
    return frozenset(out)


@functools.lru_cache(maxsize=1)
def role_nouns() -> frozenset[str]:
    """Single lower-case role words (\"minister\", \"mla\", \"collector\"): a role named after a person."""
    d = _data()
    out = set()
    for r in d["roles"].values():
        for f in r.get("forms") or []:
            if len(_words(f)) == 1 and f.lower() not in {h.lower() for h in d["honorifics"]}:
                out.add(f.lower())
    return frozenset(out)


@functools.lru_cache(maxsize=1)
def role_acronyms() -> frozenset[str]:
    return frozenset(f for r in _data()["roles"].values() for f in r.get("forms") or []
                     if f.isupper() and 2 <= len(f) <= 5)


# ---------------------------------------------------------------------------------------- roles

def _norm(phrase: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.,]", "", phrase or "")).strip().lower()


def role_of(phrase: str, context: str = "") -> str | None:
    """The role a written title is (its id), or None. A form with a condition (`requires_any`) counts only when the
    context mentions one of its words; an unconditional entry for the same form is the fallback."""
    cands = _data()["forms"].get(_norm(phrase)) or []
    ctx = f"{context or ''} {phrase or ''}"      # the title itself counts as context (\"Chief Justice of India\")
    best = None
    for rid in cands:
        r = _data()["roles"][rid]
        need = r.get("requires_any") or []
        if not need:
            best = best or rid
        elif any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", ctx) for n in need):
            return rid
    return best


def _ancestors(rid: str) -> list[str]:
    out, seen = [], {rid}
    cur = _data()["roles"].get(rid, {}).get("is_a")
    while cur and cur not in seen:
        out.append(cur)
        seen.add(cur)
        cur = _data()["roles"].get(cur, {}).get("is_a")
    return out


def relation(a: str, b: str, context: str = "") -> str | None:
    """How two written titles relate: \"same\" (synonyms of one role), \"a_is_b\" (a is a kind of b: a CJI is a
    Supreme Court judge), \"b_is_a\", or None. Never \"same\" for a kind-of pair: \"Supreme Court judge\" does not
    name the CJI."""
    ra, rb = role_of(a, context), role_of(b, context)
    if not ra or not rb:
        return None
    if ra == rb:
        return "same"
    if rb in _ancestors(ra):
        return "a_is_b"
    if ra in _ancestors(rb):
        return "b_is_a"
    return None


def forms_of(role_id: str | None) -> list[str]:
    """Every way outlets write a role (its `forms`), longest first."""
    r = _data()["roles"].get(role_id or "") or {}
    return sorted(r.get("forms") or [], key=len, reverse=True)


def is_scoped(phrase: str) -> bool:
    """Does a written title say WHICH office it is on its own? (owner, Oct 11 2026: \"CM of Delhi\" gives the context, a bare
    \"the chief minister\" does not.) True when the phrase has a portfolio word (\"Home\" in \"Union Home Minister\"), a
    place or body name (\"Delhi Chief Minister\", \"Delhi Police spokesperson\") or an \"of ...\" (\"Chief Minister of Delhi\").
    Only capitalised words count, so \"the\" and \"a\" never do; a title word, an honorific or a qualifier is no scope."""
    words = [w.strip(".,;:()") for w in (phrase or "").split()]
    scope = set(_data()["scope_words"])
    tw = title_words()
    for k, w in enumerate(words):
        if not w:
            continue
        if w in scope:
            return True
        if w.lower() == "of" and any(x[:1].isupper() for x in words[k + 1:]):
            return True
        if w[:1].isupper() and w not in tw and w.lower() not in _OPENERS:
            return True
    return False


def ref_for(role_id: str | None) -> str | None:
    r = _data()["roles"].get(role_id or "")
    return (r or {}).get("ref")


# ---------------------------------------------------------------------------------------- phrases

_CAP = re.compile(r"^[A-Z0-9]")


def title_start(prefix: str, max_words: int = 7, extra: frozenset | set = frozenset(),
                extra_person: frozenset | set = frozenset()) -> int:
    """Where the title phrase that ENDS `prefix` begins (an index into `prefix`; len(prefix) when there is none).
    `prefix` is the text right before a name. Words are taken backwards while they are title words, or capitalised
    qualifiers that sit right before a title word ("Assam", "Lok Sabha", "AAP Delhi"); "of" and "the" bridge title
    words ("Leader of Opposition", "Chief Justice of India", "Leader of the Opposition") so a title is taken whole or
    not at all (owner, Oct 12 2026: \"Lok Sabha Leader of Gandhi\", because only \"Opposition Rahul\" was cut). The
    phrase must hold at least one person-title word and never starts with a sentence opener (\"The\", \"While\").
    `extra` / `extra_person` add words the caller also knows as title words."""
    toks = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[\w.&'()-]+", prefix)]
    if prefix[len(prefix.rstrip()):] == "" and toks:
        return len(prefix)                      # no space before the name: it is a part of a word, not a title
    toks = toks[-max_words:]
    tw = title_words() | set(extra)
    pw = person_title_words() | set(extra_person) | set(extra)
    take: list[tuple[str, int, int]] = []
    for tok in reversed(toks):
        w = tok[0]
        bare = w.strip(".,;:\"'\u2018\u2019\u201c\u201d")   # a quote mark glued to a word ("'Prime") is not part of it
        if bare in tw or bare.lower() in ("of", "the") and take:
            take.append(tok)
        elif (_CAP.match(bare) and any(t[0].strip(".,;:") in tw for t in take) and bare.lower() not in _OPENERS
              and not re.search(r"[.,;:!?]$", w)):      # a word ending a sentence or clause is not part of the title
            take.append(tok)
        else:
            break
    take.reverse()
    while take and (take[0][0].strip(".,;:").lower() in _OPENERS | {"of", "the"}):
        take = take[1:]
    # "of" at the end can not happen (a name follows the title), and a qualifier-only phrase ("Union") is no title
    if not any(t[0].strip(".,;:") in pw for t in take):
        return len(prefix)
    return take[0][1]


def title_start_in(text: str, a: int, max_words: int = 7, extra: frozenset | set = frozenset(),
                   extra_person: frozenset | set = frozenset()) -> int:
    """`title_start` for the name that starts at `a` in `text`: the analyser answers first (titlesys.py), the title list when it
    cannot, and every disagreement is counted (owner, Oct 28 2026)."""
    from . import titlesys
    listed = title_start(text[:a], max_words, extra, extra_person)
    return titlesys.compare_title(titlesys.title_start(text, a), listed, text, a)


def title_before(text: str, name: str, max_words: int = 7) -> str:
    """The title phrase written directly before `name` in `text` ("Assam Chief Minister" before "Himanta Biswa
    Sarma"), or "". See `title_start` for how the phrase is found."""
    m = re.search(rf"((?:[\w.&'()-]+\s+){{1,{max_words}}}){re.escape(name)}(?![\w-])", text)
    if not m:
        return ""
    prefix = m.group(1)
    a = m.end(1)
    start = title_start_in(text, a, max_words)
    return text[start:a].strip()


_OPENERS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february",
            "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
            "the", "a", "an", "while", "meanwhile", "when", "after", "before", "on", "in", "at", "by", "for", "from",
            "according", "however", "but", "and", "also", "later", "earlier", "then", "since", "as", "if", "with"}


def strip(phrase: str) -> str:
    """A name without the titles in front of it: \"Assam Chief Minister Himanta Biswa Sarma\" -> \"Himanta Biswa
    Sarma\". Left alone when stripping would leave fewer than two words and the phrase holds no title."""
    words = [w for w in (phrase or "").split() if w]
    tw = title_words()
    last = max((k for k, w in enumerate(words) if w.strip(".,;:") in tw), default=-1)
    if last >= 0 and len(words) - last - 1 >= 1:
        return " ".join(words[last + 1:])
    return " ".join(words)

"""Who is a person and what is the title in front of the name? Asked of the analyser, not of a title list (owner, Oct 28 2026).

`people.TITLES` (an inline set of ~130 words) and the recognition parts of `config/titles.yaml` (honorifics, qualifiers, the words
of every role form) answer two questions by listing words: (1) where does the title phrase in front of a name start
(`titles.title_start`), (2) which words of a capitalised phrase are the name (`people._clean`). The analyser answers both from the
sentence itself:
  * a PERSON entity is the name (its boundaries are the model's, so "Chief Minister" is outside it when the model puts it there);
  * the title is the run of noun / proper-noun modifiers (compound / nmod) right before the name that hang on the name's head word:
    "Assam Chief Minister Himanta Biswa Sarma", "Delhi Police Commissioner Sanjay Arora", "BJP leader Rahul". The run is taken whole.
Not decided (no analyser, no part of speech, an adjective or a bridge word such as "Former", "of" touching the run, a name the
analyser does not call a person) = the caller's OLD LIST answers. It stays as the fallback (owner: "keep them as fallback for
audit"); every time both answered and differ is counted in `auditcount` section "titles", with the words, for `tools/evaluate.py`.
What stays hand-written: the KNOWLEDGE in config/titles.yaml (synonyms, `is_a`, `requires_any`, `ref`): what a CJI is, not how a
title looks. News house style (PM / CM / CJI, news.py) is not touched.
"""
from __future__ import annotations

from collections import Counter

from . import auditcount, nlp

STATS: Counter = auditcount.counter("titles")
MODIFIER_DEPS = {"compound", "nmod"}
RUN_POS = {"NOUN", "PROPN"}
EXAMPLES: dict[str, Counter] = {"title": Counter(), "name": Counter()}
MAX_EXAMPLES = 200


def reset() -> None:
    STATS.clear()
    for c in EXAMPLES.values():
        c.clear()


def _note(kind: str, what: str) -> None:
    if len(EXAMPLES[kind]) < MAX_EXAMPLES or what in EXAMPLES[kind]:
        EXAMPLES[kind][what] += 1


def _readable(text: str):
    toks = nlp.parse(text)
    if not toks or not all(t.pos for t in toks if t.text.strip()):
        return None                                         # a word without part of speech: the analyser cannot say
    return toks


def title_start(text: str, a: int) -> int | None:
    """Where the title phrase right before the name that starts at `a` begins (an index into `text`), `a` when the analyser
    finds no title there, None when it cannot say (then the title list answers)."""
    toks = _readable(text)
    if toks is None:
        return None
    first = next((k for k, t in enumerate(toks) if t.start == a), None)
    if first is None:
        return None
    ent = next((e for e in nlp.ents(text) if e.start <= a < e.end and e.label == nlp.PERSON), None)
    if ent is None or ent.start != a:
        return None                                         # not a person, or its entity swallows the title: not decided
    inside = {k for k, t in enumerate(toks) if ent.start <= t.start < ent.end}
    head = next((k for k in inside if toks[k].head not in inside or toks[k].head == k), None)
    if head is None:
        return None
    if toks[head].dep in ("pobj", "appos"):
        return None             # a name that is the object of a preposition ("Leader of the Opposition in the Lok Sabha Rahul Gandhi"): the title is a phrase with "of" / "in" in it, not a run
    k, taken = first - 1, []
    while k >= 0:
        t = toks[k]
        hang = toks[t.head] if 0 <= t.head < len(toks) else None
        on_chain = t.head == head or t.head in taken or (t.head in inside and t.head != k)
        if t.dep in MODIFIER_DEPS and t.pos in RUN_POS and on_chain and text[t.end:toks[k + 1].start].strip() == "":
            taken.append(k)
            k -= 1
            continue
        break
    if taken and k >= 0:
        edge = min(taken)
        touching = text[toks[k].end:toks[edge].start].strip() == ""
        if touching and (toks[k].pos in ("ADJ", "ADP", "DET") or toks[k].text.lower() in ("of", "the")):
            return None                                     # "Former ...", "Leader of ...": a bridge or adjective touches the run
    return toks[min(taken)].start if taken else a


def person_name(phrase: str, text: str, at: int) -> str | None:
    """The person's name inside a capitalised phrase that stands at `at` in `text`: the PERSON entity the analyser finds there,
    None when it finds none inside the phrase (then the title list strips the phrase)."""
    if not text or not phrase or _readable(text) is None:
        return None
    end = at + len(phrase)
    ents = [e for e in nlp.ents(text) if e.label == nlp.PERSON and e.start >= at and e.end <= end + 1]
    if not ents:
        return None
    best = max(ents, key=lambda e: e.end - e.start)
    return best.text.strip(".,;:\"'")


def compare_title(system: int | None, listed: int, text: str, a: int) -> int:
    """Use the system's start when it decided; count a disagreement with the list; else the list's."""
    if system is None:
        STATS["title:undecided"] += 1
        return listed
    STATS["title:asked"] += 1
    if system != listed:
        STATS["title:differ"] += 1
        sys_t, list_t = text[system:a].strip(), text[listed:a].strip()
        _note("title", f"system:{sys_t or '-'} | list:{list_t or '-'}")
    # the LONGER title wins (owner, Oct 29 2026: the system's run "Lok Sabha" was cut from "Leader of the Opposition in the Lok Sabha
    # Rahul Gandhi" and the rest stayed in front of a bare surname): a title is taken whole or not at all, so a title either
    # side found in full must never be shortened by the other; the system alone may add a title the list does not know.
    return min(system, listed)


def compare_name(system: str | None, listed: str) -> str:
    if system is None:
        STATS["name:undecided"] += 1
        return listed
    STATS["name:asked"] += 1
    if system.lower() != listed.lower():
        STATS["name:differ"] += 1
        _note("name", f"system:{system} | list:{listed or '-'}")
    return system


def snapshot_examples(n: int = 25) -> dict[str, list]:
    return {k: [[w, c] for w, c in v.most_common(n)] for k, v in EXAMPLES.items()}

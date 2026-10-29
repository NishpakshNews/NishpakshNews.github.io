"""Is a typed conflict between two lines a real disagreement? code -> one model question -> code -> (one other question).

Owner, Oct 29 2026: not code alone, not the same model question twice; a staged route where each stage is used for what it is good at.
  1. CODE (`reconcile.difference`) finds that the two lines answer one question with answers that cannot both stand (a figure, a
     date, a negation). Arithmetic on intervals, dates and names is code's job and is exact.
  2. ONE model question about the thing code cannot read: is it the same question (same event, same scope, same thing measured)?
     "four vs one year" (two events), "opened on 6 Nov vs closes on 16 Nov" (two acts), "in Punjab vs in India" (two scopes) are
     all the model's to name. A closed answer: SAME | EVENT | SCOPE | THING | UNSURE.
  3. CODE checks the answer. SAME stands as a real candidate (the dispute step still asks its own cannot-both-be-true question).
     A "different" answer is believed only if the lines really differ in something besides the conflicting answer (each has a
     content word the other lacks); if they are identical but for the answer it is implausible, so it counts as UNSURE.
  4. Only for UNSURE or an implausible answer: ONE different, extractive question: "copy the words of each line that make them
     different". Code checks each copied phrase is really in its line and is not the conflicting figure or date itself. Two
     verified phrases = different. Anything else = unresolved: kept as a candidate, never shown as a dispute, never dropped.
Outcomes: real | different (with what differs) | unresolved. No model = unresolved (never a guess either way).
`ask(prompt) -> str | None`: the router's call (a fake in tests).
"""
from __future__ import annotations

import re

from . import tidy
from .relate import Profile

Q1 = """Two lines from news reports each give an answer. Do they answer the SAME question about the SAME event?

Answer with exactly one word:
SAME    - one event, one place, one thing measured or done; only the answer differs.
EVENT   - two different events (another match, another year, another incident, another time).
SCOPE   - the same kind of thing but a different place, group or part (one state vs the country, one team vs all).
THING   - a different thing measured or done (opened vs closes, applied vs approved, cost vs value).
UNSURE  - you cannot tell.

Examples
LINE 1: Four people were killed in the 2024 blast.
LINE 2: One person was killed in the 2023 blast.
ANSWER: EVENT
LINE 1: The portal opened on 6 November.
LINE 2: The portal closes on 16 November.
ANSWER: THING
LINE 1: Rain will continue in Punjab for 3 days.
LINE 2: Rain will continue in north India for 5 days.
ANSWER: SCOPE
LINE 1: Police said 12 people were arrested in the raid.
LINE 2: Police said 14 people were arrested in the raid.
ANSWER: SAME

LINE 1: {a}
LINE 2: {b}
ANSWER:"""

Q2 = """Two news lines look alike but may be about different things. Copy, word for word, the short phrase of EACH line
that makes it a different event, place, group or thing from the other line. Do not copy the numbers or dates they disagree
about. If they are really the same event and only the answer differs, answer exactly: SAME

LINE 1: {a}
LINE 2: {b}
Reply in two lines:
1: <phrase copied from LINE 1>
2: <phrase copied from LINE 2>"""

KINDS = {"SAME", "EVENT", "SCOPE", "THING", "UNSURE"}


def _first_word(answer: str | None) -> str | None:
    if not answer:
        return None
    m = re.match(r"\W*(?:ANSWER:\s*)?([A-Za-z]+)", answer.strip())
    w = m.group(1).upper() if m else ""
    return w if w in KINDS else None


def differ_in_something_else(a: str, b: str) -> bool:
    """Each line has a content word the other lacks that is not a figure: the lines can be about different things."""
    pa, pb = Profile(a), Profile(b)
    return bool(pa.roots - pb.roots) and bool(pb.roots - pa.roots)


def _phrases(answer: str | None) -> tuple[str, str] | None:
    if not answer:
        return None
    m1 = re.search(r"(?m)^\s*1\s*[:.)-]\s*(.+)$", answer)
    m2 = re.search(r"(?m)^\s*2\s*[:.)-]\s*(.+)$", answer)
    if not (m1 and m2):
        return None
    return m1.group(1).strip().strip('"“”'), m2.group(1).strip().strip('"“”')


def _in(phrase: str, text: str) -> bool:
    return len(phrase.split()) >= 1 and phrase.lower() in text.lower()


def _is_the_answer(phrase: str) -> bool:
    """The copied phrase is only a figure or date: the very thing they disagree about, so it shows nothing else differs."""
    return not re.search(r"[A-Za-z]", re.sub(r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|lakh|crore|million|billion|per|cent|percent)\b", "", phrase))


def judge(a: str, b: str, ask=None, d=None) -> dict:
    """{"outcome": real | different | unresolved, "stage": ..., "why": ...}"""
    from . import reconcile
    d = d or reconcile.difference(a, b, Profile(a), Profile(b))
    if not d.conflicts:
        return {"outcome": "different", "stage": "code", "why": "no conflict between the answers"}
    if ask is None:
        return {"outcome": "unresolved", "stage": "code", "why": "no model to read the question"}
    plausible_different = differ_in_something_else(a, b)
    q1 = _first_word(ask(Q1.format(a=a, b=b)))
    if q1 == "SAME":
        return {"outcome": "real", "stage": "model", "why": "same question, other answer"}
    if q1 in ("EVENT", "SCOPE", "THING") and plausible_different:
        return {"outcome": "different", "stage": "model+code", "why": q1.lower()}
    # unsure, no answer, or "different" for lines that differ in nothing but the answer: one other, checkable question
    ph = _phrases(ask(Q2.format(a=a, b=b)))
    if ph and _in(ph[0], a) and _in(ph[1], b) and not _is_the_answer(ph[0]) and not _is_the_answer(ph[1]) \
            and ph[0].lower() != ph[1].lower():
        return {"outcome": "different", "stage": "extract", "why": f"{ph[0]} / {ph[1]}", "phrases": list(ph)}
    return {"outcome": "unresolved", "stage": "extract", "why": "the model could not show a difference"}

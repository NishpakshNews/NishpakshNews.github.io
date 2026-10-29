"""The writer for a merge of two overlapping lines (B9 step 2c). NOT connected: `tidy.tidy(..., rewrite=)` takes it.

One small, concrete question for a simple model: "Write ONE sentence that says everything both lines say, nothing else."
The model proposes; `tidy.verify_merge` decides (every figure, name, date, clock time and quotation of both lines in it,
nothing new, one sentence, the same negation, no longer than both together). Following the charter, an answer that could
merge facts is asked TWICE with the two lines in swapped order and kept only if BOTH answers pass the check; the first one
is used. `ask(prompt) -> str | None` is the router's quality-tier call (a fake in tests); None = could not ask = no merge.
"""
from __future__ import annotations

from . import tidy

PROMPT = """Two lines from one news paragraph tell the same event. Write ONE sentence that says everything both lines say.

Rules:
- Keep EVERY number, name, date and time of both lines, exactly as written. If the two lines give the same number at
  different precision (48 lakh / 48.54 lakh), use the more precise one.
- Add nothing. Do not explain. Do not add a word of your own except joining words.
- If one line says "not", the sentence says "not" too.
- Quotations stay word for word.
- If you cannot do this in one sentence, answer exactly: NO

Example
LINE 1: The 3% DA hike is effective from 1 July 2026.
LINE 2: Since the DA hike is effective from 1 July 2026, central government employees will get a higher salary this month.
ANSWER: The 3% DA hike, effective from 1 July 2026, gives central government employees a higher salary this month.

Example (different facts: answer NO)
LINE 1: Protesters set fire to an office of the power corporation.
LINE 2: Protesters blocked the highway for six hours.
ANSWER: NO

LINE 1: {a}
LINE 2: {b}
ANSWER:"""


def _clean(answer: str | None) -> str | None:
    if not answer:
        return None
    a = answer.strip().splitlines()[0].strip().strip('"').strip()
    if a.upper().startswith("ANSWER:"):
        a = a[7:].strip()
    return None if not a or a.upper() == "NO" else a


def make_rewrite(ask):
    """A `rewrite(a, b)` for `tidy.tidy`: asked twice (order swapped), both answers must pass the code check."""
    def rewrite(a: str, b: str) -> str | None:
        first = _clean(ask(PROMPT.format(a=a, b=b)))
        if not first or not tidy.verify_merge(a, b, first)[0]:
            return None
        second = _clean(ask(PROMPT.format(a=b, b=a)))
        if not second or not tidy.verify_merge(a, b, second)[0]:
            return None
        return first
    return rewrite

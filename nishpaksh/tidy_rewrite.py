"""The writer for a merge of two overlapping lines (B9 step 2c). NOT connected: `tidy.tidy(..., rewrite=)` takes it.

The FALLBACK only: `tidy.tidy` first merges by code (`fusion.fuse`); this is asked for the pairs fusion cannot edit together.
One small, concrete question, ASKED ONCE (owner, Oct 29 2026: asking a weak model twice only doubles its errors; what protects
the article is the check, not the second ask). `tidy.verify_merge` decides (every figure, name, date, clock time and quotation
of both lines in it, nothing new, one sentence, the same negation, the same claim strength, no longer than both together).
`ask(prompt) -> str | None` is the router's quality-tier call (a fake in tests); None = could not ask = no merge.
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
    """A `rewrite(a, b)` for `tidy.tidy`: asked once; the caller checks the answer with `verify_merge`."""
    def rewrite(a: str, b: str) -> str | None:
        return _clean(ask(PROMPT.format(a=a, b=b)))
    return rewrite

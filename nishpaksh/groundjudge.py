"""The evidence gate for "false" and "confirmed" (B26): a verdict needs a PASSAGE and a meaning check, not two opinions.

The two-model agreement of verify.verify_story stays, and this is added after it: the statement is compared, by the local NLI
cross-encoder, with each line of the evidence the grounded search returned. "false" needs a line that CONTRADICTS the statement
(P >= nli.CONTRA) read in the passage->statement direction, no line that entails it, and at least one source address; "confirmed"
needs lines that ENTAIL it and none that contradict. Evidence with no source address, or an NLI that cannot run (None), holds the
verdict back: the answer is "no change", never "false". It can only make a verdict rarer.
"""
from __future__ import annotations

import re

from . import nli


def _lines(evidence: str) -> list[str]:
    out = []
    for ln in re.split(r"\n+", evidence or ""):
        ln = re.sub(r"^[\s\-*•\d.)]+", "", ln).strip()
        if len(ln.split()) >= 5:
            out.append(ln)
    return out[:12]


def holds(statement: str, evidence: str, urls: list[str], want: str) -> bool:
    """want = "contradicted" or "supported". True only when the passage lines settle it by meaning."""
    lines = _lines(evidence)
    if not statement or not lines or not urls:
        return False
    res = nli.predict([(ln, statement) for ln in lines])
    if any(r is None for r in res):
        return False
    entails = [r[0] >= nli.ENTAIL for r in res]
    contras = [r[2] >= nli.CONTRA for r in res]
    if want == "contradicted":
        return any(contras) and not any(entails)
    if want == "supported":
        return any(entails) and not any(contras)
    return False

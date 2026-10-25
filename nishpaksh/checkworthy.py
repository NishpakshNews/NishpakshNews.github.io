"""Is this statement a checkable fact or a characterisation? (B29) A natural-language-inference zero-shot classifier, with a
reject option, instead of a model asked in a prompt.

The statement is the premise; two fixed hypotheses are tried against it with the local NLI cross-encoder (nli.py):
  FACT:     "This sentence reports something that happened, or a figure, that could be checked."
  OPINION:  "This sentence gives an opinion, a judgement or an evaluation."
A statement is a FACT only when the first is entailed and the second is not; an OPINION (characterisation) when the second is
entailed and the first is not; anything else, or an NLI model that cannot run, is None = could not tell, and the caller treats
it as a characterisation (never green): a missing answer can only make the page more cautious.
"""
from __future__ import annotations

from . import nli

FACT = "This sentence reports something that happened, or a figure, that could be checked."
OPINION = "This sentence gives an opinion, a judgement or an evaluation."
SURE = 0.60              # P(entailment) a hypothesis needs; the other must stay under NOT_SURE
NOT_SURE = 0.40


def classify(texts: list[str]) -> list[bool | None]:
    """True = checkable fact, False = characterisation, None = could not tell."""
    if not texts:
        return []
    res = nli.predict([(t, h) for t in texts for h in (FACT, OPINION)])
    out: list[bool | None] = []
    for k in range(len(texts)):
        f, o = res[2 * k], res[2 * k + 1]
        if f is None or o is None:
            out.append(None)
        elif f[0] >= SURE and o[0] < NOT_SURE:
            out.append(True)
        elif o[0] >= SURE and f[0] < NOT_SURE:
            out.append(False)
        else:
            out.append(None)
    return out

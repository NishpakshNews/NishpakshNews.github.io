"""B9: a coreference model as a COUNTED check on the finished article, never enforced.

`discourse.py`, `refs.py` and `agreement.py` count dangling pronouns by rules. A trained coreference model (fastcoref)
reads the whole article and gives chains of mentions; a pronoun whose chain has no earlier non-pronoun mention is
dangling in the model's eyes. The audit compares the two counts (`tools/evaluate.py`, section "coreference"); the
rules stay the enforcement until the numbers say otherwise. No model installed or any error: None (unknown), never 0.
Test backend: `set_backend(fn)` where fn(text) -> list of chains, each chain a list of (start, end) character spans."""
from __future__ import annotations

import re
import threading

PRONOUN = re.compile(r"(?i)^(he|she|it|they|him|her|them|his|its|their|hers|theirs)$")
_backend = None
_model = None
_failed = False
_lock = threading.Lock()


def set_backend(fn) -> None:
    global _backend
    _backend = fn


def _chains(text: str):
    if _backend is not None:
        return _backend(text)
    global _model, _failed
    with _lock:
        if _failed:
            return None
        if _model is None:
            try:
                from fastcoref import FCoref
                _model = FCoref(device="cpu")
            except Exception:  # noqa: BLE001
                _failed = True
                return None
    try:
        pred = _model.predict(texts=[text])[0]
        return pred.get_clusters(as_strings=False)
    except Exception:  # noqa: BLE001
        return None


def dangling(text: str) -> dict | None:
    """{'pronouns': n in chains, 'dangling': n whose chain has no earlier non-pronoun mention} or None if unknown."""
    chains = _chains(text)
    if chains is None:
        return None
    pron = dang = 0
    for ch in chains:
        spans = sorted(tuple(s) for s in ch)
        seen_name = False
        for a, b in spans:
            word = text[a:b].strip()
            if PRONOUN.match(word):
                pron += 1
                if not seen_name:
                    dang += 1
            else:
                seen_name = True
    return {"pronouns": pron, "dangling": dang}

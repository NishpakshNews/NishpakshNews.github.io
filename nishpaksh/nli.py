"""Natural-language inference, run locally (B21, B7, B26, B27): does sentence A entail B, contradict it, or neither?

An established multilingual cross-encoder (mDeBERTa-v3 trained on XNLI + multilingual NLI) replaces the Gemini
"same fact? / says it all? / can both be true?" questions: no quota, the same answer every time, English and Hindi
in one model. The two directions of a pair are always both read, which is the "asked twice, swapped" rule built into
the method. A pair the model could not read is None (never "different"), as everywhere else.

`set_backend(fn)` swaps the model for tests: fn(pairs) -> [(entail, neutral, contradiction) | None].
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable

log = logging.getLogger("nishpaksh.nli")

MODEL = os.getenv("NISHPAKSH_NLI_MODEL", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")
ENTAIL = 0.80         # P(entailment) a sentence needs to count as saying the other
CONTRA = 0.80         # P(contradiction) for "cannot both be true"
UNSURE = 0.40         # contradiction between this and CONTRA is "unsure"
BATCH = 16
MAX_LEN = 256

Probs = tuple[float, float, float]
_backend: Callable[[list[tuple[str, str]]], list[Probs | None]] | None = None
_lock = threading.Lock()
_model = None            # (tokenizer, model, order) | False once loading failed
_cache: dict[tuple[str, str], Probs] = {}


def set_backend(fn) -> None:
    global _backend
    _backend = fn
    _cache.clear()


def _load():
    global _model
    with _lock:
        if _model is None:
            try:
                import torch  # noqa: F401
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                tok = AutoTokenizer.from_pretrained(MODEL)
                mod = AutoModelForSequenceClassification.from_pretrained(MODEL).eval()
                labels = {int(i): str(n).lower() for i, n in mod.config.id2label.items()}
                order = (next(i for i, n in labels.items() if n.startswith("entail")),
                         next(i for i, n in labels.items() if n.startswith("neutral")),
                         next(i for i, n in labels.items() if n.startswith("contra")))
                _model = (tok, mod, order)
            except Exception as e:  # noqa: BLE001
                log.warning("NLI model unavailable: %s", str(e)[:200])
                _model = False
        return _model or None


def available() -> bool:
    return _backend is not None or _load() is not None


def _run(pairs: list[tuple[str, str]]) -> list[Probs | None]:
    m = _load()
    if not m:
        return [None] * len(pairs)
    import torch
    tok, mod, (ie, inn, ic) = m
    out: list[Probs | None] = []
    for s in range(0, len(pairs), BATCH):
        chunk = pairs[s:s + BATCH]
        try:
            enc = tok([a for a, _ in chunk], [b for _, b in chunk], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors="pt")
            with torch.no_grad():
                p = torch.softmax(mod(**enc).logits, dim=-1)
            out += [(float(r[ie]), float(r[inn]), float(r[ic])) for r in p]
        except Exception as e:  # noqa: BLE001
            log.warning("NLI batch failed: %s", str(e)[:200])
            out += [None] * len(chunk)
    return out


def predict(pairs: list[tuple[str, str]]) -> list[Probs | None]:
    """(premise, hypothesis) -> (entailment, neutral, contradiction), cached; None where it could not be read."""
    res: list[Probs | None] = [None] * len(pairs)
    todo = [i for i, p in enumerate(pairs) if p not in _cache]
    for i, p in enumerate(pairs):
        if p in _cache:
            res[i] = _cache[p]
    if todo:
        got = (_backend or _run)([pairs[i] for i in todo])
        for i, g in zip(todo, got):
            if g is not None:
                _cache[pairs[i]] = g
                res[i] = g
    return res


def both(pairs: list[tuple[str, str]]) -> list[tuple[Probs, Probs] | None]:
    """Each pair read in both directions: (a->b, b->a). None if either direction could not be read."""
    fwd = predict(pairs)
    bwd = predict([(b, a) for a, b in pairs])
    return [(f, b) if f is not None and b is not None else None for f, b in zip(fwd, bwd)]


# decisions ------------------------------------------------------------------------------------------------
def same(pairs: list[tuple[str, str]]) -> list[bool | None]:
    """Same fact in other words: each says the other, and neither contradicts."""
    return [None if r is None else (r[0][0] >= ENTAIL and r[1][0] >= ENTAIL) for r in both(pairs)]


def covers(pairs: list[tuple[str, str]]) -> list[bool | None]:
    """(detailed, short): does the detailed line say everything the short one says?"""
    return [None if r is None else r[0] >= ENTAIL for r in predict(pairs)]


def conflict(pairs: list[tuple[str, str]]) -> list[str | None]:
    """'cannot_both_be_true' / 'both_true' / 'unsure': contradiction read in both directions, the stronger counts."""
    out: list[str | None] = []
    for r in both(pairs):
        if r is None:
            out.append(None)
            continue
        c = max(r[0][2], r[1][2])
        out.append("cannot_both_be_true" if c >= CONTRA else "unsure" if c >= UNSURE else "both_true")
    return out

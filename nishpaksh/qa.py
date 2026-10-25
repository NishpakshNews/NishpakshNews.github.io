"""A second, independent detector of "the statement says something the report does not" (S13): question answering.

QAGS (Wang et al. 2020) and QuestEval (Scialom et al. 2021): ask questions of the STATEMENT whose answers are its figures and
names, ask the same questions of the REPORT's sentence, and compare the answers. An NLI model reads the two sentences whole and
can be fooled by an overlap in words; an extractive question-answering model reads for one slot at a time, so a changed figure or
a swapped name shows as two different answers. It is a second opinion, never the only one: the arithmetic `tells` check and the
NLI check are unchanged, and a mismatch adds a problem to the reading check (`fidelity.check_reading`), which the repair pass already
handles; a question the model could not answer, or answered without confidence, adds nothing.

    slots       the statement's figures (by value, `figures`) and person / place / organisation names (`nlp.ents`), at most MAX_SLOTS
    question    the statement with the slot blanked out ("Police arrested ___ men near the bridge.") and what kind of answer it needs
    mismatch    the answer from the report, compared with the slot: figures by value, names by spelling key or close letters
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

MODEL = "deepset/xlm-roberta-base-squad2"
MAX_SLOTS = 3
MIN_SCORE = 0.5            # the QA model's own confidence an answer needs to count (untuned)
NAME_CLOSE = 85            # letters (rapidfuzz ratio) two spellings of one name must share

_backend = None
_model = None
_lock = threading.Lock()


def set_backend(fn) -> None:
    """fn(list[(question, context)]) -> list[(answer, score) | None]. For tests; None restores the real model."""
    global _backend
    _backend = fn


def _load():
    global _model
    with _lock:
        if _model is None:
            try:
                from transformers import pipeline
                _model = pipeline("question-answering", model=MODEL, tokenizer=MODEL)
            except Exception as e:  # noqa: BLE001
                log.warning("QA model unavailable: %s", str(e)[:200])
                _model = False
        return _model or None


def ask(pairs: list[tuple[str, str]]) -> list[tuple[str, float] | None]:
    if not pairs:
        return []
    if _backend is not None:
        return list(_backend(pairs))
    m = _load()
    if m is None:
        return [None] * len(pairs)
    out = []
    for q, c in pairs:
        try:
            r = m(question=q, context=c)
            out.append((str(r["answer"]), float(r["score"])))
        except Exception:  # noqa: BLE001
            out.append(None)
    return out


def slots(statement: str) -> list[dict]:
    """[{kind: number|name, text, value}] with the blanked-out sentence as `cloze`."""
    from . import figures, nlp
    out = []
    for f in figures.find(statement):
        out.append({"kind": "number", "text": statement[f.start:f.end], "value": round(f.value, 6),
                    "cloze": statement[:f.start] + "___" + statement[f.end:]})
    for e in nlp.ents(statement):
        if e.label in (nlp.PERSON, "GPE", "ORG", "LOC", "FAC"):
            out.append({"kind": "name", "text": e.text, "value": e.text,
                        "cloze": statement[:e.start] + "___" + statement[e.end:]})
    return out[:MAX_SLOTS]


def question(slot: dict) -> str:
    what = "the number or amount" if slot["kind"] == "number" else "the name"
    return f"In this sentence, what is {what} that fills the blank ___ ? {slot['cloze']}"


def _agree(slot: dict, answer: str) -> bool:
    from . import figures, spelling
    if slot["kind"] == "number":
        vals = figures.value_set(answer)
        return (not vals) or slot["value"] in vals           # an answer with no figure in it is not a disagreement
    a, b = spelling.key(answer), spelling.key(slot["text"])
    if a == b or a in b or b in a:
        return True
    try:
        from rapidfuzz import fuzz
        return fuzz.ratio(a, b) >= NAME_CLOSE
    except Exception:  # noqa: BLE001
        return False


def mismatches(statement: str, window: str) -> list[str]:
    """The slots of `statement` whose answer from `window` (the report's sentence) disagrees, as short descriptions."""
    sl = slots(statement)
    if not sl or not window:
        return []
    got = ask([(question(s), window) for s in sl])
    return [s["text"] for s, g in zip(sl, got) if g is not None and g[1] >= MIN_SCORE and not _agree(s, g[0])]

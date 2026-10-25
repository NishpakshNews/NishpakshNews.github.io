"""The linguistic analyser (B1, B2, B9, B27): spaCy, loaded once, used by entities, references and claim splitting.

Named-entity recognition and the dependency parse come from an established English pipeline (en_core_web_lg; the small
model labelled "Mamata Banerjee" an organisation in a first trial and the large one does not), not from word lists.
Anything that cannot load returns None / [] and the caller treats the text as "not analysed", never as "nothing there".
`set_backend(fn)` replaces the analyser in tests: fn(text) -> list of Ent.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

log = logging.getLogger("nishpaksh.nlp")

MODELS = (os.getenv("NISHPAKSH_SPACY_MODEL") or "en_core_web_lg", "en_core_web_sm")
PERSON = "PERSON"
NOT_PERSON_LABELS = {"ORG", "GPE", "LOC", "NORP", "FAC", "EVENT", "LAW", "PRODUCT", "WORK_OF_ART", "LANGUAGE"}

_backend = None
_nlp = None
_lock = threading.Lock()
_cache: dict[str, list] = {}


@dataclass(frozen=True)
class Ent:
    text: str
    label: str
    start: int
    end: int


def set_backend(fn) -> None:
    global _backend
    _backend = fn
    _cache.clear()


def pipeline():
    """The loaded spaCy pipeline, or None when no model can be loaded."""
    global _nlp
    with _lock:
        if _nlp is None:
            _nlp = False
            try:
                import spacy
                for name in MODELS:
                    try:
                        _nlp = spacy.load(name, disable=["lemmatizer"])
                        break
                    except Exception as e:  # noqa: BLE001
                        log.warning("spaCy model %s unavailable: %s", name, str(e)[:120])
            except Exception as e:  # noqa: BLE001
                log.warning("spaCy unavailable: %s", str(e)[:120])
        return _nlp or None


def available() -> bool:
    return _backend is not None or pipeline() is not None


def ents(text: str) -> list[Ent]:
    """Named entities of a text (cached)."""
    if not text:
        return []
    if text in _cache:
        return _cache[text]
    if _backend is not None:
        out = list(_backend(text))
    else:
        nlp = pipeline()
        if nlp is None:
            return []
        doc = nlp(text[:100_000])
        out = [Ent(e.text, e.label_, e.start_char, e.end_char) for e in doc.ents]
    if len(_cache) > 2000:
        _cache.clear()
    _cache[text] = out
    return out

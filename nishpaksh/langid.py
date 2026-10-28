"""Which language is this text? Asked of a language-identification model, not of word lists (owner, Oct 28 2026).

`videoquery.video_language` kept three word lists (English function words, Hindi function words, romanised-Hindi words)
to be SURE a video's title is English or Hindi. A language-identification model (lingua, n-gram statistics over 75
languages; installed from requirements-nlp.txt, no download) gives each language a probability; romanised Hindi is not
English to it (it reads as Swahili, Tagalog ...), which is what the romanised-Hindi list was for.
`identify(text)` -> (language, probability, margin over the second) or None (not installed, or no text). The caller keeps its
old list as the fallback when this returns None or is unsure; `auditcount` "language" counts where the two differ.
`set_backend(fn)` replaces the model in tests: fn(text) -> (language, probability, margin) | None.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("nishpaksh.langid")
_backend = None
_use_backend = False
_detector = None
_lock = threading.Lock()
EN_MARGIN = 0.1         # English is "sure" when it leads the next language by this much (untuned; short titles score low)
OTHER_SURE = 0.5        # another language at this probability: the text is not English (untuned)
HI_MARGIN = 0.3


def set_backend(fn) -> None:
    global _backend, _use_backend
    _backend, _use_backend = fn, fn is not None


def _load():
    global _detector
    with _lock:
        if _detector is None:
            _detector = False
            try:
                from lingua import LanguageDetectorBuilder
                _detector = LanguageDetectorBuilder.from_all_languages().build()
            except Exception as e:  # noqa: BLE001
                log.warning("language identification unavailable: %s", str(e)[:120])
        return _detector or None


def identify(text: str) -> tuple[str, float, float] | None:
    if not (text or "").strip():
        return None
    if _use_backend:
        return _backend(text)
    det = _load()
    if det is None:
        return None
    try:
        conf = det.compute_language_confidence_values(text)
    except Exception:  # noqa: BLE001
        return None
    if not conf:
        return None
    second = conf[1].value if len(conf) > 1 else 0.0
    return conf[0].language.name.lower(), float(conf[0].value), float(conf[0].value - second)

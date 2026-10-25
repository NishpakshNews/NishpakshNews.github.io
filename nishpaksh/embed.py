"""Sentence similarity, local (B6, B14, B16, B32): a multilingual bi-encoder, with TF-IDF when it cannot load.

paraphrase-multilingual-MiniLM-L12-v2 puts a sentence in any of 50 languages (Hindi included) near its paraphrases.
It runs on the CPU, uses no Gemini quota and answers the same every time; this module only PROPOSES pairs and
topics, the NLI model (nli.py) and the code gates decide. `set_backend(fn)` replaces it in tests: fn(texts) -> matrix.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache

import numpy as np

log = logging.getLogger("nishpaksh.embed")

MODEL = os.getenv("NISHPAKSH_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
_backend = None
_model = None
_lock = threading.Lock()


def set_backend(fn) -> None:
    global _backend
    _backend = fn


def _load():
    global _model
    with _lock:
        if _model is None:
            try:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(MODEL, device="cpu")
            except Exception as e:  # noqa: BLE001
                log.warning("embedding model unavailable (TF-IDF used instead): %s", str(e)[:160])
                _model = False
        return _model or None


@lru_cache(maxsize=1)
def _stemmer():
    import snowballstemmer
    return snowballstemmer.stemmer("english")


def _analyzer(text: str) -> list[str]:
    """Word stems, so "arrested" and "arrest" are one term (the bi-encoder does this by itself)."""
    import re

    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    return _stemmer().stemWords([w for w in re.findall(r"\w+", text.lower()) if w not in ENGLISH_STOP_WORDS and len(w) > 1])


def _tfidf(texts: list[str]) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer
    try:
        m = TfidfVectorizer(sublinear_tf=True, analyzer=_analyzer).fit_transform(texts)
    except ValueError:
        return np.zeros((len(texts), 1))
    return m.toarray()


def vectors(texts: list[str]) -> tuple[np.ndarray, str]:
    """(unit vectors, which method made them: "bi-encoder" | "tfidf")."""
    if _backend is not None:
        v, how = np.asarray(_backend(texts), dtype=float), "bi-encoder"
    else:
        m = _load()
        if m:
            v, how = np.asarray(m.encode(texts, batch_size=32, show_progress_bar=False), dtype=float), "bi-encoder"
        else:
            v, how = _tfidf(texts), "tfidf"
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n == 0, 1, n), how


# A pair this similar is worth asking the NLI model about; the bi-encoder is generous, TF-IDF cosine is lower.
PROPOSE = {"bi-encoder": 0.55, "tfidf": 0.25}


def similarity(texts: list[str]) -> tuple[np.ndarray, float]:
    """(cosine matrix, the proposal threshold for the method used)."""
    v, how = vectors(texts)
    return v @ v.T, PROPOSE[how]

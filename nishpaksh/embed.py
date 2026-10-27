"""Sentence similarity, local (B6, B14, B16, B32): a multilingual bi-encoder, with TF-IDF when it cannot load.

paraphrase-multilingual-MiniLM-L12-v2 puts a sentence in any of 50 languages (Hindi included) near its paraphrases.
It runs on the CPU, uses no Gemini quota and answers the same every time; this module only PROPOSES pairs and
topics, the NLI model (nli.py) and the code gates decide. `set_backend(fn)` replaces it in tests: fn(texts) -> matrix.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from functools import lru_cache

import numpy as np

log = logging.getLogger("nishpaksh.embed")

MODEL = os.getenv("NISHPAKSH_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
_backend = None
_model = None
_lock = threading.Lock()

# A vector cache (Oct 27 2026). The bi-encoder answers the same for the same text, so a text is encoded ONCE per process and
# remembered: `threads.find_parents` embeds the headline and opening of every published page of the last 60 days for each
# story the desk looks at (and again after every publication), which on the runner's two CPUs was the same ~1,500 texts
# encoded over and over. Keyed by the model name and the text, so a changed model or text never hits. Only the
# bi-encoder is cached: a test backend is a plain function of the texts, and TF-IDF vectors depend on the WHOLE list
# (idf is fitted on it), so a cached row would not equal the row the same call would make. Least recently used rows go
# first. Nothing is written to disk: a new process starts empty and fills it on its first look.
CACHE_MAX = 8000
_cache: "OrderedDict[str, np.ndarray]" = OrderedDict()
_cache_lock = threading.Lock()
STATS = {"hit": 0, "miss": 0, "encode_seconds": 0.0}


def cache_stats() -> dict:
    """What the cache did in this process (hits, misses, seconds spent encoding, rows held): for the run's record."""
    return {"hit": STATS["hit"], "miss": STATS["miss"], "encode_seconds": round(STATS["encode_seconds"], 1),
            "held": len(_cache)}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
    STATS.update(hit=0, miss=0, encode_seconds=0.0)


def _key(text: str) -> str:
    return hashlib.sha1(f"{MODEL}\x00{text}".encode("utf-8", "replace")).hexdigest()


def _encode_cached(model, texts: list[str]) -> np.ndarray:
    """The model's vectors for `texts` (what `model.encode(texts)` returns), encoding only the texts not seen before.
    Equal texts in one call are encoded once. Rows come back as the model made them (float32 held, float64 returned)."""
    keys = [_key(t) for t in texts]
    got: dict[str, np.ndarray] = {}
    with _cache_lock:
        for k in set(keys):
            v = _cache.get(k)
            if v is not None:
                _cache.move_to_end(k)
                got[k] = v
    todo: dict[str, str] = {}
    for k, t in zip(keys, texts):
        if k not in got and k not in todo:
            todo[k] = t
    if todo:
        t0 = time.time()
        enc = np.asarray(model.encode(list(todo.values()), batch_size=32, show_progress_bar=False))
        STATS["encode_seconds"] += time.time() - t0
        if enc.ndim != 2 or len(enc) != len(todo):
            return np.asarray(model.encode(texts, batch_size=32, show_progress_bar=False), dtype=float)    # unexpected shape: no cache
        with _cache_lock:
            for k, row in zip(todo, enc):
                row = np.array(row, dtype=np.float32)
                _cache[k] = row
                _cache.move_to_end(k)
                got[k] = row
            while len(_cache) > CACHE_MAX:
                _cache.popitem(last=False)
    STATS["hit"] += len(keys) - sum(1 for k in keys if k in todo)
    STATS["miss"] += len(todo)
    return np.asarray([got[k] for k in keys], dtype=float)


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
        if m and texts:
            v, how = _encode_cached(m, texts), "bi-encoder"
        elif m:
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

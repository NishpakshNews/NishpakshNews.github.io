"""The vector cache in embed.py (Oct 27 2026): a text is encoded once per process; the answers do not change."""
import threading

import numpy as np
import pytest

from nishpaksh import embed


class FakeModel:
    """Stands in for the sentence-transformers model: a vector is a function of the text alone; counts what it was asked."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, texts, batch_size=32, show_progress_bar=False):
        self.calls.append(list(texts))
        return np.array([[float(len(t)), float(sum(map(ord, t)) % 97), 1.0] for t in texts], dtype=np.float32)


@pytest.fixture
def model(monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(embed, "_backend", None)
    monkeypatch.setattr(embed, "_model", m)
    embed.clear_cache()
    yield m
    embed.clear_cache()


def _plain(m, texts):
    """What the old code returned: the model's rows as floats, then unit length."""
    v = np.asarray(m.encode(texts), dtype=float)
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n == 0, 1, n)


def test_same_numbers_as_without_the_cache(model):
    texts = ["Police arrested him.", "Rain flooded the city.", "Police arrested him.", "A third text"]
    got, how = embed.vectors(texts)
    assert how == "bi-encoder"
    assert np.array_equal(got, _plain(FakeModel(), texts))        # exactly, rows in the order asked, a repeat included


def test_a_text_is_encoded_once(model):
    embed.vectors(["a one", "a two", "a one"])
    assert model.calls == [["a one", "a two"]]                     # the repeat inside the call is not encoded twice
    embed.vectors(["a two", "a one"])
    assert len(model.calls) == 1                                   # all in the cache: the model is not asked
    embed.vectors(["a one", "a new one", "a two"])
    assert model.calls[-1] == ["a new one"]                        # only the unseen text
    s = embed.cache_stats()
    assert s["miss"] == 3 and s["held"] == 3 and s["hit"] == 4


def test_order_and_values_when_cached_and_new_are_mixed(model):
    embed.vectors(["old text"])
    mixed = ["fresh text", "old text", "another fresh text"]
    got, _ = embed.vectors(mixed)
    assert np.array_equal(got, _plain(FakeModel(), mixed))


def test_the_model_name_is_part_of_the_key(model, monkeypatch):
    embed.vectors(["same text"])
    monkeypatch.setattr(embed, "MODEL", "another-model")
    embed.vectors(["same text"])
    assert len(model.calls) == 2                                   # a different model never reads the other's rows


def test_least_recently_used_rows_go_first(model, monkeypatch):
    monkeypatch.setattr(embed, "CACHE_MAX", 3)
    embed.vectors(["t1", "t2", "t3"])
    embed.vectors(["t1"])                                          # t1 is used again: t2 is now the oldest
    embed.vectors(["t4"])
    assert embed.cache_stats()["held"] == 3
    model.calls.clear()
    embed.vectors(["t1", "t3", "t4"])
    assert model.calls == []
    embed.vectors(["t2"])
    assert model.calls == [["t2"]]


def test_a_call_bigger_than_the_cache_still_answers_every_row(model, monkeypatch):
    monkeypatch.setattr(embed, "CACHE_MAX", 2)
    texts = [f"text number {i}" for i in range(7)]
    got, _ = embed.vectors(texts)
    assert np.array_equal(got, _plain(FakeModel(), texts))
    assert embed.cache_stats()["held"] == 2


def test_a_test_backend_is_never_cached(monkeypatch):
    calls = []

    def backend(texts):
        calls.append(list(texts))
        return np.tile(np.array([[0.6, 0.8]]), (len(texts), 1))
    monkeypatch.setattr(embed, "_backend", backend)
    embed.clear_cache()
    embed.vectors(["x", "y"])
    embed.vectors(["x", "y"])
    assert len(calls) == 2 and embed.cache_stats()["held"] == 0


def test_tfidf_is_not_cached(monkeypatch):
    """TF-IDF rows depend on the whole list, so the same text in two lists has two different vectors."""
    monkeypatch.setattr(embed, "_backend", None)
    monkeypatch.setattr(embed, "_model", False)                    # the model cannot load
    embed.clear_cache()
    a, how = embed.vectors(["alpha beta gamma", "delta epsilon"])
    assert how == "tfidf" and embed.cache_stats()["held"] == 0


def test_an_empty_list_behaves_as_before(model):
    class Empty(FakeModel):
        def encode(self, texts, **kw):
            return np.zeros((0, 3), dtype=np.float32)
    embed._model = Empty()
    v, how = embed.vectors([])
    assert v.shape == (0, 3) and how == "bi-encoder"


def test_threads_may_ask_at_once(model):
    texts = [f"story {i}" for i in range(40)]
    out = []

    def go():
        out.append(embed.vectors(texts)[0])
    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    want = _plain(FakeModel(), texts)
    assert len(out) == 4 and all(np.array_equal(o, want) for o in out)
    assert embed.cache_stats()["held"] == 40

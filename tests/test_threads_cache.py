"""The thread check and the vector cache (Oct 27 2026): each published page is embedded once per process, and the parents
found are the same with a warm cache as with none."""
import datetime as dt

import numpy as np
import pytest

from nishpaksh import embed, threads
from nishpaksh.db import Store, insert, published, select, stories, update

from .fixtures import NOW


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 'c.db'}")
    s.init()
    return s


class Model:
    """A vector from the words of the text: texts with the same words are close."""
    VOCAB = ["flyover", "collapse", "bail", "engineer", "monsoon", "assembly", "kesarganj", "lucknow", "court"]

    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, texts, batch_size=32, show_progress_bar=False):
        self.calls.append(list(texts))
        return np.array([[float(t.lower().count(w)) for w in self.VOCAB] + [0.1] for t in texts], dtype=np.float32)


@pytest.fixture
def model(monkeypatch):
    m = Model()
    monkeypatch.setattr(embed, "_backend", None)
    monkeypatch.setattr(embed, "_model", m)
    embed.clear_cache()
    yield m
    embed.clear_cache()


def _page(store, sid, headline, lead, age_hours):
    at = NOW - dt.timedelta(hours=age_hours)
    page = {"headline": headline, "narrative": {"paragraphs": [[{"text": lead}, {"text": "A second sentence."}]]}}
    store.exec(insert(published).values(story_id=sid, version=1, updated_at=at, headline_en=headline, headline_hi="h",
                                        payload_en=page, payload_hi={}))


def _child(store, sid=10):
    store.exec(insert(stories).values(id=sid, created_at=NOW, updated_at=NOW, dirty=False, qualifies=True, analysis={}))


def _encoded(model):
    return [t for call in model.calls for t in call]


def test_each_page_is_embedded_once_and_a_new_page_costs_only_itself(store, model):
    _page(store, 1, "Kesarganj flyover collapses", "A flyover collapse in Kesarganj killed four", 30)
    _page(store, 2, "Lucknow assembly adjourned", "The monsoon session of the Lucknow assembly ended", 28)
    _child(store)
    head, summary = "Court grants bail to Kesarganj flyover engineer", "The engineer held after the Kesarganj flyover collapse got bail"
    first = threads.find_parents(store, None, 10, head, summary)
    assert first == [1]
    n_first = len(_encoded(model))
    assert n_first == 3                                   # the story and the two pages, once each
    _page(store, 3, "Monsoon session ends", "The monsoon session ended in Lucknow", 1)          # something is published
    second = threads.find_parents(store, None, 10, head, summary)       # checked again (a page was published since)
    assert second == [1]
    assert len(_encoded(model)) == n_first + 1            # only the new page was encoded; the rest came from the cache
    assert embed.cache_stats()["hit"] >= 3


def test_the_parents_found_do_not_depend_on_a_warm_cache(store, model):
    _page(store, 1, "Kesarganj flyover collapses", "A flyover collapse in Kesarganj killed four", 30)
    _page(store, 2, "Lucknow assembly adjourned", "The monsoon session of the Lucknow assembly ended", 28)
    _page(store, 3, "Kesarganj flyover rescue ends", "Rescue work at the Kesarganj flyover collapse ended", 20)
    _child(store)
    head, summary = "Court grants bail to Kesarganj flyover engineer", "The engineer held after the Kesarganj flyover collapse got bail"

    def parents_with_cache(warm: bool):
        row = store.one(select(stories.c.analysis).where(stories.c.id == 10))["analysis"]
        for k in ("thread_checked", "thread_checked_at", "thread_cand_key"):
            row.pop(k, None)
        store.exec(update(stories).where(stories.c.id == 10).values(analysis=row))
        store.exec(threads.delete(threads.story_links))
        if not warm:
            embed.clear_cache()
        return threads.find_parents(store, None, 10, head, summary)
    cold = parents_with_cache(False)
    warm = parents_with_cache(True)
    assert cold == warm and 1 in cold and 2 not in cold

import pytest
from sqlalchemy import select

from nishpaksh import dossier
from nishpaksh.db import dossiers


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 'newsroom.db'}")
    s.init()
    return s


def test_each_stage_replaces_only_its_own_key(store):
    assert dossier.record(store, 7, "statements", {"items": [{"id": 1, "verdict": "unverified"}]})
    assert dossier.record(store, 7, "writer", {"essay_good": True, "text": "x" * 500})
    assert dossier.record(store, 7, "writer", {"essay_good": False})
    data = store.one(select(dossiers.c.data).where(dossiers.c.story_id == 7))["data"]
    assert set(data) == {"statements", "writer"} and data["writer"]["essay_good"] is False
    assert data["statements"]["items"][0]["verdict"] == "unverified"


def test_a_broken_store_never_stops_a_stage():
    assert dossier.record(object(), 1, "x", {"a": 1}) is False

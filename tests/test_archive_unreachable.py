"""An archive that cannot be asked is "unreachable", never "no such page" (Group A, H95: a follow-up lost its parent).

Before: one network blip made fetch_page return None and REMEMBERED it for the run; build_payload then dropped the
parent from the follow-up, follow_up_ok saw no parents and said yes, and the finished article was closed with no
thread. A month index that failed was cached as empty, so find_parents marked the story "checked" with no archived
candidate seen. Now a failure to ask raises Unreachable where it matters, is never cached, and the story waits."""
import gzip
import json

import pytest
import requests

from nishpaksh import editions, pagearchive


class Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


@pytest.fixture
def store(tmp_path):
    from nishpaksh.db import Store
    s = Store(f"sqlite:///{tmp_path / 't.db'}")
    s.init()
    return s


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("NISHPAKSH_ARCHIVE_URL", "https://archive.test/x")
    monkeypatch.setattr(pagearchive, "_down_until", 0.0)
    pagearchive._page_cache.clear()
    pagearchive._index_cache.clear()
    yield
    pagearchive._page_cache.clear()
    pagearchive._index_cache.clear()
    pagearchive._down_until = 0.0


def _serve(monkeypatch, *replies):
    """requests.get answers from `replies` in turn: a Resp, or an exception to raise."""
    seq = list(replies)
    calls = []

    def get(url, timeout=None):
        calls.append(url)
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(requests, "get", get)
    return calls


PAGE = {"headline_en": "Parent", "payload_en": {"headline": "Parent"}, "written_at": "2026-10-10T00:00:00"}


def _gz(obj):
    return gzip.compress(json.dumps(obj).encode())


def test_a_failed_request_is_unreachable_when_strict_and_none_otherwise(monkeypatch):
    _serve(monkeypatch, requests.ConnectionError("down"))
    with pytest.raises(pagearchive.Unreachable):
        pagearchive.fetch_page(7, strict=True)
    assert pagearchive.fetch_page(7) is None            # not strict: as before, None (and no new request: it just failed)


def test_a_failure_is_not_remembered_the_page_is_found_when_the_archive_comes_back(monkeypatch):
    _serve(monkeypatch, requests.ConnectionError("down"), Resp(200, _gz(PAGE)))
    assert pagearchive.fetch_page(7) is None
    pagearchive._down_until = 0.0                         # the archive is asked again after the short pause
    assert pagearchive.fetch_page(7)["headline_en"] == "Parent"
    assert pagearchive.fetch_page(7)["headline_en"] == "Parent"     # a page that was read is remembered


def test_no_such_page_is_an_answer_and_a_server_error_is_not(monkeypatch):
    _serve(monkeypatch, Resp(404))
    assert pagearchive.fetch_page(7, strict=True) is None            # the archive said: no such page
    pagearchive._down_until = 0.0
    _serve(monkeypatch, Resp(503))
    with pytest.raises(pagearchive.Unreachable):
        pagearchive.fetch_page(8, strict=True)


def test_after_a_failure_the_archive_is_not_asked_again_at_once(monkeypatch):
    calls = _serve(monkeypatch, requests.Timeout("slow"))
    with pytest.raises(pagearchive.Unreachable):
        pagearchive.fetch_page(1, strict=True)
    with pytest.raises(pagearchive.Unreachable):
        pagearchive.fetch_page(2, strict=True)
    assert len(calls) == 1                                           # one 15 s wait, not one per story


def test_an_index_month_that_failed_is_not_cached_as_empty(monkeypatch):
    import datetime as dt
    now = dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc)
    _serve(monkeypatch, requests.ConnectionError("down"))
    with pytest.raises(pagearchive.Unreachable):
        pagearchive.recent_index(1, now, strict=True)
    assert pagearchive._index_cache == {}
    pagearchive._down_until = 0.0
    line = json.dumps({"story_id": 5, "headline_en": "H", "written_at": "2026-10-19T10:00:00"})
    _serve(monkeypatch, Resp(200, line.encode()))
    assert [x["story_id"] for x in pagearchive.recent_index(1, now, strict=True)] == [5]


def test_parent_pages_raises_for_an_unreachable_parent_and_is_quiet_for_a_missing_one(store, monkeypatch):
    _serve(monkeypatch, requests.ConnectionError("down"))
    with pytest.raises(pagearchive.Unreachable):
        editions.parent_pages(store, [123456], strict=True)
    pagearchive._down_until = 0.0
    _serve(monkeypatch, Resp(404))
    assert editions.parent_pages(store, [123456], strict=True) == {}

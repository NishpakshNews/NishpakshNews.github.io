"""The picture of an archived article (Oct 29 2026): link, credit, faces and a tiny blur; never a stopped archive step."""
import base64

import cv2
import numpy as np

from nishpaksh import archivepic, feed


def _jpeg():
    img = np.zeros((90, 160, 3), np.uint8)
    img[:, :80] = (200, 80, 40)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def test_blur_is_tiny_and_not_a_copy():
    out = {"blur": archivepic.tiny(_jpeg())}
    head, b64 = out["blur"].split(",", 1)
    assert head.startswith("data:image/")
    assert len(base64.b64decode(b64)) < 1500
    small = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
    assert small.shape[1] == archivepic.BLUR_WIDTH


def test_unreadable_picture_gives_no_blur():
    assert archivepic.tiny(b"not a picture") is None


def test_blur_survives_a_crashing_face_finder(monkeypatch):
    real = archivepic._child
    def child(mode, data):
        if mode == "look":
            raise RuntimeError("picture look exited -11")
        return real(mode, data)
    monkeypatch.setattr(archivepic, "_child", child)
    out = archivepic.make_safe(_jpeg())
    assert out["blur"].startswith("data:image/")


def test_for_story_keeps_link_even_when_the_look_fails(monkeypatch):
    monkeypatch.setattr(feed, "pictures", lambda store, m: {"7": {"src": "https://i.x/1.jpg", "by": "X", "href": "https://x/1"}})
    got = archivepic.for_story(None, 7, {}, fetcher=lambda u: b"data", maker=lambda d: (_ for _ in ()).throw(RuntimeError("boom")))
    assert got == {"src": "https://i.x/1.jpg", "by": "X", "href": "https://x/1"}
    got = archivepic.for_story(None, 7, {}, fetcher=lambda u: b"data", maker=lambda d: {"blur": "data:x"})
    assert got["blur"] == "data:x" and got["by"] == "X"
    assert archivepic.for_story(None, 7, {}, look=False) == {"src": "https://i.x/1.jpg", "by": "X", "href": "https://x/1"}


def test_story_without_picture_gives_none(monkeypatch):
    monkeypatch.setattr(feed, "pictures", lambda store, m: {})
    assert archivepic.for_story(None, 7, {}) is None

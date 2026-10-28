"""Pictures framed on their faces (focus.py). No network, no database; the detector tests need OpenCV."""
import json
import pathlib

import pytest

from nishpaksh import focus

HERE = pathlib.Path(__file__).resolve().parent


def test_summarise_keeps_the_subject_and_drops_the_crowd():
    # a big face, a second subject, a tiny background face
    boxes = [(100, 50, 80, 100, 90), (400, 60, 60, 80, 90), (700, 300, 8, 10, 304)]
    f = focus.summarise(focus.foreground(boxes), 1000, 800, "face")
    assert f["fk"] == "face" and f["ar"] == 1.25
    assert len(f["fc"]) == 2                          # the 10 px face is crowd
    assert f["fc"][0] == [0.14, 0.125, 0.125, 0.113]  # largest first: centre x, centre y, height, eyes y as fractions


def test_foreground_drops_small_and_blurred_faces():
    boxes = [(0, 0, 100, 120), (300, 0, 90, 110), (600, 0, 40, 50)]
    # the second face is as big but out of focus: background
    assert focus.foreground(boxes, [100.0, 12.0, 90.0]) == [boxes[0]]
    # all sharp: the small one is still background
    assert focus.foreground(boxes, [100.0, 95.0, 100.0]) == boxes[:2]


def test_summarise_nothing():
    assert focus.summarise([], 100, 100, "face") == {}
    assert focus.summarise([(0, 0, 1, 1)], 1000, 1000, "face") == {}


def test_head_of_a_person_is_at_the_top_centre():
    x, y, w, h, ey = focus.head_of((100, 100, 100, 300))
    assert abs((x + w / 2) - 150) < 1 and y < 130


def test_attach_uses_the_cache_and_caps_new_pictures(tmp_path):
    (tmp_path / focus.CACHE).write_text(json.dumps({"http://a/1.jpg": {"f": {"fc": [[0.5, 0.3, 0.1]], "ar": 1.5, "fk": "face"}, "t": 10**10, "v": focus.VERSION}}))
    pics = {"1": {"src": "http://a/1.jpg"}, "2": {"src": "http://a/2.jpg"}, "3": {"src": "http://a/3.jpg"}, "4": {"src": "http://a/4.jpg"}}
    seen = []
    st = focus.attach(pics, tmp_path, max_new=2, fetcher=lambda u: seen.append(u) or (None if u.endswith("3.jpg") else b"x"),
                      looker=lambda d: {"fc": [[0.4, 0.2, 0.1]], "ar": 1.0, "fk": "face"})
    assert pics["1"]["fc"] == [[0.5, 0.3, 0.1]]       # from the cache, not looked at again
    assert pics["2"]["fk"] == "face"
    assert "fc" not in pics["3"] and "fc" not in pics["4"]
    assert st == {"cached": 1, "looked": 2, "found": 1, "waiting": 1, "failed": 1}
    cache = json.loads((tmp_path / focus.CACHE).read_text())
    assert "http://a/2.jpg" in cache and "http://a/3.jpg" not in cache   # a failed download is tried again next time


def test_attach_never_raises_on_a_bad_picture(tmp_path):
    pics = {"1": {"src": "http://a/1.jpg"}}
    def boom(_):
        raise ValueError("broken jpeg")
    st = focus.attach(pics, tmp_path, fetcher=lambda u: b"x", looker=boom)
    assert st["looked"] == 1 and "fc" not in pics["1"]


def test_a_real_face_is_found():
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    img = np.full((600, 800, 3), 200, np.uint8)       # a plain picture: no face
    ok, buf = cv2.imencode(".jpg", img)
    got = focus.look(buf.tobytes())
    assert "fc" not in got and got["col"][1] == 0 and 0.77 < got["col"][3] < 0.8      # no face; the corner colour is still read


def test_the_corner_colour_is_read():
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    img = np.zeros((600, 800, 3), np.uint8)
    img[:, :] = (30, 60, 200)                          # BGR: a strong red-orange
    ok, buf = cv2.imencode(".png", img)
    h, s, l, lum = focus.look(buf.tobytes())["col"]
    assert h < 20 and s > 0.7 and lum < 0.5


def test_an_older_cache_entry_is_looked_at_again(tmp_path):
    (tmp_path / focus.CACHE).write_text(json.dumps({"http://a/1.jpg": {"f": {}, "t": 10**10}}))
    pics = {"1": {"src": "http://a/1.jpg"}}
    st = focus.attach(pics, tmp_path, fetcher=lambda u: b"x", looker=lambda d: {"fc": [[0.4, 0.2, 0.1, 0.18]], "ar": 1.0, "fk": "face"})
    assert st["looked"] == 1 and pics["1"]["fc"][0][3] == 0.18

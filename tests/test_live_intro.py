"""The intro recordings of "Talk to the article" (nishpaksh/live_intro.py, live/intro.json)."""
import json

import pytest

from nishpaksh import live_intro


def test_the_shipped_intro_words_are_valid_and_say_what_they_must():
    d = live_intro.load()
    assert set(d) >= {"en", "hi", "pause_seconds"}
    assert "interrupt" in d["en"][0].lower()          # tells them they can interrupt at any time
    assert d["en"][1].rstrip().endswith("?")          # then asks what they would like to know
    assert d["hi"][1].rstrip().endswith("?")


def test_a_pause_sits_between_the_two_parts_and_only_there():
    heard = []
    pcm = live_intro.build_pcm(["a", "b"], 0.5, lambda t: heard.append(t) or b"\x01\x01" * 100)
    assert heard == ["a", "b"]
    assert len(pcm) == 200 + 2 * int(live_intro.RATE * 0.5) + 200
    assert pcm.startswith(b"\x01\x01") and pcm.endswith(b"\x01\x01")
    assert pcm[200:200 + 2 * int(live_intro.RATE * 0.5)] == b"\x00" * (2 * int(live_intro.RATE * 0.5))


def test_a_part_that_cannot_be_spoken_fails_loudly_instead_of_giving_half_an_intro():
    with pytest.raises(RuntimeError):
        live_intro.build_pcm(["a", "b"], 0.5, lambda t: None if t == "b" else b"\x01\x01")


@pytest.mark.parametrize("bad", [
    {"en": ["one"], "hi": ["a", "b"], "pause_seconds": 1},
    {"en": ["a", "b"], "hi": ["a", ""], "pause_seconds": 1},
    {"en": ["a", "b"], "hi": ["a", "b"], "pause_seconds": 9},
    {"en": ["a", "b"], "hi": ["a", "b"]},
])
def test_a_broken_intro_file_is_refused(tmp_path, bad):
    p = tmp_path / "intro.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        live_intro.load(p)

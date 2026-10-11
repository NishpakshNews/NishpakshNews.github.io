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


def test_the_voices_are_the_ones_the_reader_can_pick_and_the_file_names_are_what_the_browser_asks_for():
    import pathlib
    import re
    ts = (pathlib.Path(live_intro.__file__).resolve().parent.parent / "supabase" / "functions" / "live-token" / "voice.ts").read_text(encoding="utf-8")
    listed = re.search(r"export const VOICES = \[(.*?)\] as const", ts, re.S).group(1)
    assert live_intro.VOICES == re.findall(r'"([A-Za-z]+)"', listed)
    assert live_intro.VOICES[0] == "Kore"
    assert live_intro.clip_name("Kore", "en") == "intro-Kore-en.m4a"
    assert live_intro.clip_name("Sadachbia", "hi") == "intro-Sadachbia-hi.m4a"


def test_the_intro_job_uses_its_own_key_when_there_is_one(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY_INTRO", raising=False)
    assert live_intro.intro_keys(["a", "b"]) == ["a", "b"]          # not set: the pipeline's keys, as before
    monkeypatch.setenv("GEMINI_API_KEY_INTRO", "  own  ")
    assert live_intro.intro_keys(["a", "b"]) == ["own"]             # set: only that one, so the pipeline's quota is not touched
    monkeypatch.setenv("GEMINI_API_KEY_INTRO", "   ")
    assert live_intro.intro_keys(["a"]) == ["a"]                    # blank counts as not set


def test_the_workflow_hands_the_job_the_intro_secret():
    import pathlib
    yml = (pathlib.Path(live_intro.__file__).resolve().parent.parent / ".github" / "workflows" / "live-intro.yml").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY_INTRO: ${{ secrets.GEMINI_API_KEY_INTRO }}" in yml


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_a_slot_is_not_called_more_than_three_times_a_minute_and_the_next_model_takes_the_overflow():
    c = _Clock()
    pool = live_intro.SlotPool([(None, "m1", 0), (None, "m2", 0)], rpm=3, now=c.now, sleep=c.sleep)
    calls = []
    for _ in range(8):
        pool.speak(lambda slot: calls.append((slot[1], c.t)) or b"\x01\x01")
    for m in ("m1", "m2"):
        times = [t for name, t in calls if name == m]
        assert all(b - a >= 20 for a, b in zip(times, times[1:]))      # 3 a minute: at least 20 s between calls of one model
    assert {name for name, _ in calls} == {"m1", "m2"}                 # the second model was used while the first was cooling down


def test_a_slot_that_keeps_failing_is_dropped_and_no_slot_left_means_none():
    c = _Clock()
    pool = live_intro.SlotPool([(None, "m1", 0)], rpm=3, now=c.now, sleep=c.sleep, max_fail=3)
    n = []

    def boom(slot):
        n.append(1)
        raise RuntimeError("429 RESOURCE_EXHAUSTED")
    assert pool.speak(boom) is None
    assert len(n) == 3                                                 # tried three times, then left alone
    assert pool.speak(boom) is None and len(n) == 3                    # and not tried again on the next call


def test_one_failure_does_not_end_the_run_and_a_success_resets_the_count():
    c = _Clock()
    pool = live_intro.SlotPool([(None, "m1", 0), (None, "m2", 0)], rpm=3, now=c.now, sleep=c.sleep)
    seen = []

    def call(slot):
        seen.append(slot[1])
        if slot[1] == "m1":
            raise RuntimeError("429")
        return b"\x01\x01"
    assert pool.speak(call) == b"\x01\x01"
    assert seen == ["m1", "m2"]


def _speech_then_glitch(speech_s=2.0, quiet_s=0.2, burst_s=0.13):
    """What Gemini TTS sometimes returns: the words, a short silence, then a burst of hard-clipped noise (Oct 12 2026)."""
    import numpy as np
    R = live_intro.RATE
    speech = (np.sin(2 * np.pi * 200 * np.arange(int(R * speech_s)) / R) * 6000).astype("<i2")
    burst = np.random.RandomState(0).choice([-32768, 32767], int(R * burst_s)).astype("<i2")
    quiet = np.zeros(int(R * quiet_s), dtype="<i2")
    return speech.tobytes() + quiet.tobytes() + burst.tobytes()


def test_clean_part_cuts_the_noise_burst_and_keeps_the_words():
    raw = _speech_then_glitch()
    assert live_intro.has_burst(raw)
    out = live_intro.clean_part(raw)
    assert not live_intro.has_burst(out)
    secs = len(out) / 2 / live_intro.RATE
    assert 2.0 <= secs <= 2.2                       # the words plus ~100 ms of silence, nothing else


def test_clean_part_leaves_clean_speech_alone_apart_from_the_trim_and_fades():
    raw = _speech_then_glitch(burst_s=0)            # no glitch this time
    out = live_intro.clean_part(raw)
    assert not live_intro.has_burst(out)
    assert abs(len(out) - len(raw)) / 2 / live_intro.RATE < 0.2


def test_build_pcm_never_joins_a_burst_into_the_intro():
    pcm = live_intro.build_pcm(["one two", "three four"], 0.9, lambda t: _speech_then_glitch())
    assert not live_intro.has_burst(pcm)

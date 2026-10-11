"""The intro recordings of "Talk to the article" (owner, Oct 11 2026).

When a reader taps the button, a recording tells them the conversation is live and they can interrupt any time, waits a
moment, then asks what they would like to know (`live/intro.json`: the words, in English and Hindi). It is a recording,
not the live model speaking: it is the same every time, costs no Live tokens, and starts AT ONCE on the tap while the
connection opens behind it (owner, Oct 11 2026 night: the guide used to say the intro itself, which took several seconds).

There is one recording per VOICE and language (`intro-<Voice>-<lang>.m4a`, for example `intro-Kore-en.m4a`) so that it sounds
like the guide the reader picked. A reader whose voice has no recording yet hears the guide say the intro itself, as before.
Made with Gemini TTS using the same voice names as the Live guide, by hand when the words change:

    python -m nishpaksh.live_intro                    # every voice, both languages, into live/ (needs ffmpeg and a Gemini key)
    python -m nishpaksh.live_intro --voice Kore       # only one voice (repeat the flag for more)

With GEMINI_API_KEY_INTRO set (a key from a separate Google Cloud project; GitHub secret of the same name) only that key is used, so the
hourly pipeline and audio.yml cannot take the day's quota first (Oct 11 2026). Without it the pipeline's keys are used, as before.

2 TTS calls a recording (the two sentences), 40 for all ten voices in both languages, out of the 10 a day each model has: the
run SKIPS files that already exist and stops cleanly when the quota is gone, so run it again the next day until it says
nothing is left. Commit the files in `live/`: the site workflow copies `live/intro-*.m4a` next to the page.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import time

log = logging.getLogger(__name__)

RATE = 24000                          # Gemini TTS: 16-bit mono PCM at 24 kHz (audio.RATE)
LIVE_DIR = pathlib.Path(__file__).resolve().parent.parent / "live"
INTRO_FILE = LIVE_DIR / "intro.json"
# the voices the reader can pick: the same list as VOICES in supabase/functions/live-token/voice.ts (a test keeps them equal), the default first
VOICES = ["Kore", "Orus", "Zephyr", "Autonoe", "Umbriel", "Erinome", "Laomedeia", "Schedar", "Achird", "Sadachbia"]


INTRO_KEY_ENV = "GEMINI_API_KEY_INTRO"


def intro_keys(fallback: list[str]) -> list[str]:
    """The key(s) this job spends. GEMINI_API_KEY_INTRO (a key from its OWN Google Cloud project) when it is set, so the hourly run
    and the audio job cannot use up the day's text-to-speech quota first; else the pipeline's keys, as before."""
    own = os.environ.get(INTRO_KEY_ENV, "").strip()
    return [own] if own else fallback


class SlotPool:
    """Every TTS model on every key, used in turn WITHOUT breaking the per-minute limit (Oct 11 2026: the log showed 429 after four quick
    calls; the free tier allows 3 requests a minute a model, audio.TTS_RPM, and this job used to fire the next call as soon as the last
    one returned, trying the first model again each time and only then the next). Each slot is used at most `rpm` times a minute; a call
    goes to the first slot that is ready, and when none is, the pool waits for the soonest. A slot that fails `max_fail` times in a row
    (the day's quota gone, a model down) is left alone for the rest of the run. `speak` returns None when no slot is left."""

    def __init__(self, slots: list, rpm: int, now=time.time, sleep=time.sleep, max_fail: int = 3):
        self.slots, self.gap, self.now, self.sleep, self.max_fail = list(slots), 60 / rpm + 1, now, sleep, max_fail
        self.ready_at: dict = {}
        self.fails: dict = {}

    def speak(self, call) -> bytes | None:
        """`call(slot) -> pcm bytes or None`; it may raise."""
        while True:
            live = [s for s in self.slots if self.fails.get((s[1], s[2]), 0) < self.max_fail]
            if not live:
                return None
            t = self.now()
            free = [s for s in live if self.ready_at.get((s[1], s[2]), 0) <= t]
            if not free:
                self.sleep(max(0.5, min(self.ready_at[(s[1], s[2])] for s in live) - t))
                continue
            slot = free[0]
            key = (slot[1], slot[2])
            self.ready_at[key] = t + self.gap
            try:
                pcm = call(slot)
            except Exception as e:  # noqa: BLE001
                self.fails[key] = self.fails.get(key, 0) + 1
                log.info("tts %s key %d: %s", slot[1], slot[2] + 1, str(e)[:400])
                continue
            if pcm:
                self.fails[key] = 0
                return pcm
            self.fails[key] = self.fails.get(key, 0) + 1


def clip_name(voice: str, lang: str) -> str:
    """The file the browser asks for (live/talk.js: intro-<voice>-<lang>.m4a)."""
    return f"intro-{voice}-{lang}.m4a"
STYLE = {"en": "Say this warmly and calmly, like a friendly news reader inviting a conversation, exactly as written:",
         "hi": "इसे गर्मजोशी और शांति से, एक मित्रवत समाचार-वाचक की तरह, जैसा लिखा है वैसा ही बोलें:"}


def load(path: pathlib.Path = INTRO_FILE) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    for lang in ("en", "hi"):
        if not (isinstance(d.get(lang), list) and len(d[lang]) == 2 and all(isinstance(x, str) and x.strip() for x in d[lang])):
            raise ValueError(f"intro.json: {lang} needs two non-empty sentences (the welcome, then the question)")
    if not 0.2 <= float(d.get("pause_seconds", 0)) <= 3:
        raise ValueError("intro.json: pause_seconds must be between 0.2 and 3")
    return d


def build_pcm(parts: list[str], pause_seconds: float, speak) -> bytes:
    """The spoken parts one after another with a pause between them. `speak(text) -> pcm bytes` (None = failed)."""
    gap = b"\x00\x00" * int(RATE * pause_seconds)
    out = []
    for text in parts:
        pcm = speak(text)
        if not pcm:
            raise RuntimeError(f"no speech for: {text[:40]}")
        out.append(pcm)
    return gap.join(out)


def main() -> None:
    from . import audio                              # imported here: the pure parts above need nothing installed
    from .config import gemini_api_keys

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=str(LIVE_DIR), help="default: live/ (what the site workflow publishes)")
    ap.add_argument("--lang", choices=["en", "hi"], action="append", help="default: both")
    ap.add_argument("--voice", choices=VOICES, action="append", help="default: all ten")
    ap.add_argument("--force", action="store_true", help="make the file again even when it exists")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    intro = load()
    keys = intro_keys(gemini_api_keys())
    if not keys:
        raise SystemExit(f"no Gemini key ({INTRO_KEY_ENV} or GEMINI_API_KEY)")
    log.info("using %s", f"{INTRO_KEY_ENV} (its own quota)" if os.environ.get(INTRO_KEY_ENV, "").strip() else f"the pipeline's {len(keys)} key(s) (shared quota)")
    slots = []                                       # every TTS model on every key, in audio.py's order
    for k, key in enumerate(keys):
        cl = audio._client(key)
        for m in sorted((m for m in cl.list_tts() if "pro" not in m), key=audio._model_rank):
            slots.append((cl, m, k))
    if not slots:
        raise SystemExit("no TTS model on any key")
    pool = SlotPool(slots, audio.TTS_RPM)
    out = pathlib.Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    made = 0
    for voice in args.voice or VOICES:
        for lang in args.lang or ["en", "hi"]:
            path = out / clip_name(voice, lang)
            if path.exists() and not args.force:
                continue

            def speak(text: str, lang=lang, voice=voice):
                return pool.speak(lambda slot: slot[0].tts(slot[1], f"{STYLE[lang]}\n\n{text}", voice))
            try:
                pcm = build_pcm(intro[lang], float(intro["pause_seconds"]), speak)
            except RuntimeError as e:                # the quota is gone (or the model is down): stop here, the next run carries on from this file
                log.info("stopped at %s: %s", path.name, e)
                break
            audio.encode(pcm, path)
            made += 1
            log.info("%s %s: %.1f s -> %s", voice, lang, len(pcm) / 2 / RATE, path)
        else:
            continue
        break                                        # (the inner loop stopped: do not try the other voices either)
    todo = [clip_name(v, l) for v in (args.voice or VOICES) for l in (args.lang or ["en", "hi"]) if not (out / clip_name(v, l)).exists()]
    log.info("made %d; %s", made, f"{len(todo)} still to make (run again later): {', '.join(todo[:6])}{' ...' if len(todo) > 6 else ''}" if todo else "nothing left to make")


if __name__ == "__main__":
    main()

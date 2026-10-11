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

2 TTS calls a recording (the two sentences), 40 for all ten voices in both languages, out of the 10 a day each model has: the
run SKIPS files that already exist and stops cleanly when the quota is gone, so run it again the next day until it says
nothing is left. Commit the files in `live/`: the site workflow copies `live/intro-*.m4a` next to the page.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import time

log = logging.getLogger(__name__)

RATE = 24000                          # Gemini TTS: 16-bit mono PCM at 24 kHz (audio.RATE)
LIVE_DIR = pathlib.Path(__file__).resolve().parent.parent / "live"
INTRO_FILE = LIVE_DIR / "intro.json"
# the voices the reader can pick: the same list as VOICES in supabase/functions/live-token/voice.ts (a test keeps them equal), the default first
VOICES = ["Kore", "Orus", "Zephyr", "Autonoe", "Umbriel", "Erinome", "Laomedeia", "Schedar", "Achird", "Sadachbia"]


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
    keys = gemini_api_keys()
    if not keys:
        raise SystemExit("no Gemini key (GEMINI_API_KEY)")
    slots = []                                       # every TTS model on every key, in audio.py's order
    for k, key in enumerate(keys):
        cl = audio._client(key)
        for m in sorted((m for m in cl.list_tts() if "pro" not in m), key=audio._model_rank):
            slots.append((cl, m, k))
    if not slots:
        raise SystemExit("no TTS model on any key")
    out = pathlib.Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    made = 0
    for voice in args.voice or VOICES:
        for lang in args.lang or ["en", "hi"]:
            path = out / clip_name(voice, lang)
            if path.exists() and not args.force:
                continue

            def speak(text: str, lang=lang, voice=voice):
                for cl, model, k in slots:
                    try:
                        pcm = cl.tts(model, f"{STYLE[lang]}\n\n{text}", voice)
                        if pcm:
                            return pcm
                    except Exception as e:  # noqa: BLE001
                        log.info("tts %s key %d: %s", model, k + 1, str(e)[:160])
                    time.sleep(2)
                return None
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

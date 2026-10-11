"""The two fixed intro recordings of "Talk to the article" (owner, Oct 11 2026).

When a reader taps the button, a recording tells them the conversation is live and they can interrupt any time, waits a
moment, then asks what they would like to know (`live/intro.json`: the words, in English and Hindi). It is a recording,
not the live model speaking: it is the same every time, costs no Live tokens, and plays while the connection opens.

Made once with the same TTS models and voice as the article audio (audio.py), run by hand when the words change:

    python -m nishpaksh.live_intro --dir live-out          # intro-en.m4a, intro-hi.m4a (needs ffmpeg and a Gemini key)

4 TTS calls in all (2 a language), out of the 10 a day each model has. Put the files where the site's audio is served
(the `audio` branch) or next to the page; `createTalk({introBase})` says where. Until they exist the browser reads the
same words with its own voice.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import time

log = logging.getLogger(__name__)

RATE = 24000                          # Gemini TTS: 16-bit mono PCM at 24 kHz (audio.RATE)
INTRO_FILE = pathlib.Path(__file__).resolve().parent.parent / "live" / "intro.json"
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
    ap.add_argument("--dir", default="live-out")
    ap.add_argument("--lang", choices=["en", "hi"], action="append", help="default: both")
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
    for lang in args.lang or ["en", "hi"]:
        def speak(text: str, lang=lang):
            for cl, model, k in slots:
                try:
                    pcm = cl.tts(model, f"{STYLE[lang]}\n\n{text}", audio.VOICE)
                    if pcm:
                        return pcm
                except Exception as e:  # noqa: BLE001
                    log.info("tts %s key %d: %s", model, k + 1, str(e)[:160])
                time.sleep(2)
            return None
        pcm = build_pcm(intro[lang], float(intro["pause_seconds"]), speak)
        path = out / f"intro-{lang}.m4a"
        audio.encode(pcm, path)
        log.info("%s: %.1f s -> %s", lang, len(pcm) / 2 / RATE, path)


if __name__ == "__main__":
    main()

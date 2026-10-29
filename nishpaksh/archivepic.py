"""The picture of an archived article (owner, Oct 29 2026: "save the thumbnails of the old articles ... the app coherent").

A live card's picture is the outlet's own share picture, LINKED, credited, never copied (owner, Oct 9 2026). The article page
did not keep it: the link lives on `articles.image`, which leaves the database with the story, so an article opened from the
archive had no picture at all. When a page is archived it now carries `img`:

    {"src", "by", "href"}            the link and the credit, as on the card (`feed.pictures`)
    {"fc", "ar", "fk", "col"}        where the faces are and the corner colour (`focus.look`), so the crop is the card's
    {"blur"}                         a 24-pixel WebP as a data link (a few hundred bytes), shown blurred: when the outlet's
                                     link no longer answers, the article keeps its colours and its place, never a hole

The outlet's picture itself is still never copied: the blur is too small to be one. Looking at a picture can crash OpenCV
(see `focus.look_safe`), so it runs in a child process, and a failure of any kind gives a link-only picture, never a stopped
archive step. Run by hand on a picture: `python -m nishpaksh.archivepic blur|look < picture.jpg`.
"""
from __future__ import annotations

import base64
import json
import logging
import subprocess
import sys

log = logging.getLogger(__name__)

BLUR_WIDTH = 24        # pixels wide; the browser blurs it up (a sharper copy would be a copy of the outlet's picture)
BLUR_QUALITY = 40
MAX_PER_RUN = 12       # pictures looked at in one archive step (the rest of the day's pages get the link only)
CHILD_SECONDS = 30


def tiny(data: bytes) -> str | None:
    """The picture as a tiny WebP data link, or None when it cannot be read (needs OpenCV; used in the child process)."""
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        if w < 2 or h < 2:
            return None
        small = cv2.resize(img, (BLUR_WIDTH, max(2, round(h * BLUR_WIDTH / w))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".webp", small, [cv2.IMWRITE_WEBP_QUALITY, BLUR_QUALITY])
        mime = "image/webp"
        if not ok:
            ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 50])
            mime = "image/jpeg"
        if not ok:
            return None
        return f"data:{mime};base64," + base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:  # noqa: BLE001 - a nicety, never a reason to stop
        return None


def _child(mode: str, data: bytes) -> dict:
    r = subprocess.run([sys.executable, "-m", "nishpaksh.archivepic", mode], input=data, capture_output=True,
                       timeout=CHILD_SECONDS, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"picture {mode} exited {r.returncode}")
    out = json.loads(r.stdout.decode("utf-8") or "{}")
    return out if isinstance(out, dict) else {}


def make_safe(data: bytes) -> dict:
    """Blur and faces, each in its own child process: OpenCV's native code can crash on a picture (the face finder did in
    the sandbox) and a crash cannot be caught in-process. A crash in one never costs the other."""
    out: dict = {}
    for mode in ("blur", "look"):
        try:
            out.update(_child(mode, data))
        except Exception as e:  # noqa: BLE001
            log.info("archive picture %s skipped: %s", mode, e)
    return out


def for_story(store, story_id: int, payload_en: dict | None, fetcher=None, maker=make_safe, look: bool = True) -> dict | None:
    """The `img` record to keep in the archived page of a story, or None when the story never had a picture.
    The link and credit are chosen exactly as on the card (`feed.pictures`: the lead's report first, a logo never).
    `look` False (a run past its budget) keeps the link and credit only."""
    from . import feed, focus
    pics = feed.pictures(store, {str(story_id): {"lead": feed._lead_urls(payload_en)}})
    pic = pics.get(str(story_id))
    if not pic:
        return None
    out = dict(pic)
    if not look:
        return out
    data = (fetcher or focus.fetch)(pic["src"])
    if data:
        try:
            out.update(maker(data))
        except Exception as e:  # noqa: BLE001 - link and credit still stand
            log.info("archive picture of %s not looked at: %s", story_id, e)
    return out


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "blur"
    data = sys.stdin.buffer.read()
    if mode == "look":
        from . import focus
        out = focus.look(data)
    else:
        blur = tiny(data)
        out = {"blur": blur} if blur else {}
    sys.stdout.write(json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()

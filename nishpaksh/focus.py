"""Where a card's picture should be looked at: its faces (owner, Oct 15 2026).

A card's picture is the outlet's own share picture, LINKED, never copied (owner, Oct 9 2026). Filled into the card
from its centre, the faces of most news pictures (portraits, people high in the frame) were cut. So at every feed
export each picture the cards show is downloaded ONCE, looked at, and thrown away; only where its faces are is kept,
as a few numbers on the card (`img.fc`, `img.ar`, `img.fk`), and the site crops to them.

- Faces: OpenCV's YuNet detector (config/models/face_detection_yunet_2023mar.onnx, MIT licence, 230 KB, CPU only,
  no API quota).
- No face (a helmet, a face turned away): OpenCV's people detector; the head is guessed at the top of the body,
  centred (owner: "yes, guess the head"). It can be wrong; the alternative was the centre crop, which is wrong more.
- Nothing found: no focus; the card keeps the centre crop as before.

Kept per picture link in `focus.json` on the feed branch (next to manifest.json), so a picture is looked at once;
at most MAX_NEW new pictures a run (the rest the next run). A failure of any kind gives no focus and never stops
the export; without OpenCV the feed goes out exactly as before.

A focus is {"fc": [[cx, cy, s], ...], "ar": w/h, "fk": "face"|"person"}: centres and sizes (a face's height) as
fractions of the picture, largest first, at most MAX_FACES; {} = looked, nothing found.
"""
from __future__ import annotations

import json
import logging
import pathlib
import time
import urllib.request

log = logging.getLogger(__name__)

MODEL = pathlib.Path(__file__).resolve().parent.parent / "config" / "models" / "face_detection_yunet_2023mar.onnx"
CACHE = "focus.json"
MAX_NEW = 30            # new pictures looked at per export
MAX_FACES = 6
MAX_BYTES = 4_000_000
TIMEOUT = 6
BUDGET = 60             # seconds an export may spend looking (the notifications wait for the feed step)
SIDE = 960              # the picture is shrunk to this longest side before looking (at 640 two people side by side were missed)
FACE_SCORE = 0.6        # YuNet's own score; a helmeted batsman scored 0.70, patterns stay well below
MIN_FACE = 0.035        # a face smaller than this share of the picture's shorter side is crowd, not subject
MIN_SHARE = 0.45        # faces much smaller than the largest are background people: left out (owner, Oct 15 2026: "the ones in
                        # the foreground matter")
MIN_SHARP = 0.3         # a face far blurrier than the sharpest large face is out of focus, i.e. background
VERSION = 3             # cache entries of another version are looked at again (2: eyes, foreground by size and sharpness; 3: corner colour)
CACHE_DAYS = 10
UA = "Mozilla/5.0 (compatible; NishpakshBot/1.0; +https://nishpakshnews.github.io)"


def _cv():
    try:
        import cv2  # noqa: PLC0415 - optional dependency, loaded only here
        import numpy  # noqa: F401, PLC0415
        return cv2
    except Exception:  # noqa: BLE001
        return None


def fetch(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - http(s) links only (feed.pictures)
            data = r.read(MAX_BYTES + 1)
        return data if 0 < len(data) <= MAX_BYTES else None
    except Exception:  # noqa: BLE001
        return None


def _decode(cv2, data: bytes):
    import numpy as np  # noqa: PLC0415
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 40 or img.shape[1] < 40:
        return None, 0, 0
    h, w = img.shape[:2]
    k = SIDE / max(h, w)
    if k < 1:
        img = cv2.resize(img, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
    return img, w, h


def faces(cv2, img) -> list[tuple[float, float, float, float, float]]:
    """(x, y, w, h, eyes_y) in pixels of `img`; eyes_y from YuNet's two eye landmarks."""
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), FACE_SCORE, 0.3, 50)
    _, found = det.detect(img)
    if found is None:
        return []
    return [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[5] + f[7]) / 2) for f in found]


def sharpness(cv2, img, box) -> float:
    """How in focus a face is: the variance of the Laplacian over it (a blurred background face scores far lower)."""
    x, y, bw, bh = (int(round(v)) for v in box[:4])
    h, w = img.shape[:2]
    crop = img[max(0, y):min(h, y + bh), max(0, x):min(w, x + bw)]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)   # the same scale for every face
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def foreground(boxes, sharp: list[float] | None = None):
    """The faces that are the picture's subject: near the largest in size and not far blurrier than the sharpest of those;
    ordered by size (and sharpness), the main face first."""
    if not boxes:
        return []
    big = max(b[3] for b in boxes)
    idx = [i for i, b in enumerate(boxes) if b[3] >= MIN_SHARE * big]
    if sharp:
        top = max(sharp[i] for i in idx) or 1.0
        idx = [i for i in idx if sharp[i] >= MIN_SHARP * top]
        idx.sort(key=lambda i: boxes[i][3] * (0.6 + 0.4 * sharp[i] / top), reverse=True)
    else:
        idx.sort(key=lambda i: boxes[i][3], reverse=True)
    return [boxes[i] for i in idx]


def people(cv2, img) -> list[tuple[float, float, float, float]]:
    """(x, y, w, h) boxes of whole people (OpenCV's HOG people detector)."""
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    h, w = img.shape[:2]
    k = min(1.0, 480 / max(h, w))
    small = cv2.resize(img, (round(w * k), round(h * k))) if k < 1 else img
    boxes, weights = hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
    out = []
    for (x, y, bw, bh), wt in zip(boxes, list(weights) if len(boxes) else []):
        if float(wt) >= 0.5:
            out.append((x / k, y / k, bw / k, bh / k))
    return out


def head_of(box: tuple[float, float, float, float]) -> tuple[float, float, float, float, float]:
    """The head guessed from a person's box: HOG boxes have margin; the head is the top ~1/6, centred; eyes 40% down it."""
    x, y, w, h = box
    hh = h * 0.16
    top = y + h * 0.06
    return (x + w / 2 - hh / 2, top, hh, hh, top + hh * 0.4)


def summarise(boxes, w: int, h: int, kind: str) -> dict:
    """Boxes (pixels of a w x h picture) -> the stored focus. Small and background faces are left out."""
    if not boxes or not w or not h:
        return {}
    short = min(w, h)
    keep = [b for b in boxes if b[3] >= MIN_FACE * short]
    if not keep:
        return {}
    keep = keep[:MAX_FACES]               # already the foreground, main face first (foreground())
    fc = []
    for b in keep:
        x, y, bw, bh = b[:4]
        ey = b[4] if len(b) > 4 else y + bh * 0.4
        fc.append([round(float(x + bw / 2) / w, 3), round(float(y + bh / 2) / h, 3), round(float(bh) / h, 3), round(float(ey) / h, 3)])
    return {"fc": fc, "ar": round(w / h, 3), "fk": kind}


def corner(img) -> dict:
    """The colour under the greeting (owner, Oct 29 2026): the average of the picture's top-left corner as
    {"col": [hue 0-360, saturation 0-1, lightness 0-1, luminance 0-1]}. The site makes the pill from it."""
    import colorsys  # noqa: PLC0415
    h, w = img.shape[:2]
    b, g, r = (float(img[: max(1, int(h * .22)), : max(1, int(w * .62))][:, :, i].mean()) / 255 for i in range(3))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return {"col": [round(hh * 360), round(ss, 2), round(ll, 2), round(lum, 2)]}


def look(data: bytes) -> dict:
    cv2 = _cv()
    if cv2 is None:
        return {}
    img, _, _ = _decode(cv2, data)
    if img is None:
        return {}
    try:
        col = corner(img)
    except Exception:  # noqa: BLE001 - the colour is a nicety
        col = {}
    return {**col, **_faces_of(cv2, img)}


def look_safe(data: bytes) -> dict:
    """`look` in a child process: OpenCV's native code can segfault on a picture (Oct 29 2026: the whole feed export died with
    exit 139 and the site's feed went stale), and a crash cannot be caught inside the process. A crash, a timeout or bad
    output raises, so `attach` stores "no focus" for that picture and the export goes on."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415
    r = subprocess.run([sys.executable, "-m", "nishpaksh.focus"], input=data, capture_output=True, timeout=30, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"picture look exited {r.returncode}")
    out = json.loads(r.stdout.decode("utf-8") or "{}")
    return out if isinstance(out, dict) else {}


def _faces_of(cv2, img) -> dict:
    if not MODEL.exists():
        return {}
    h, w = img.shape[:2]
    found = [b for b in faces(cv2, img) if b[3] >= MIN_FACE * min(w, h)]
    if found:
        return summarise(foreground(found, [sharpness(cv2, img, b) for b in found]), w, h, "face")
    ppl = people(cv2, img)
    if ppl:
        heads = [head_of(b) for b in ppl]
        return summarise(foreground(heads), w, h, "person")
    return {}


def load_cache(root: pathlib.Path) -> dict:
    try:
        data = json.loads((root / CACHE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def attach(pics: dict[str, dict], root: pathlib.Path, max_new: int = MAX_NEW, fetcher=fetch, looker=None,
           budget: float = BUDGET) -> dict:
    """Add the focus to every picture in `pics` (story id -> img) from the cache, looking at up to `max_new` new ones.
    Writes the cache back (only the pictures in use and those looked at in the last CACHE_DAYS days). Returns stats."""
    stats = {"cached": 0, "looked": 0, "found": 0, "waiting": 0, "failed": 0}
    if looker is None:
        if _cv() is None:
            return stats
        looker = look_safe
    cache = load_cache(root)
    now = int(time.time())
    until = time.monotonic() + budget
    in_use = set()
    for img in pics.values():
        src = img.get("src") or ""
        if not src.startswith("http"):
            continue
        in_use.add(src)
        got = cache.get(src)
        if got is not None and got.get("v") != VERSION:
            got = None                         # looked at by an older version: look again
        if got is None:
            if stats["looked"] >= max_new or time.monotonic() > until:
                stats["waiting"] += 1
                continue
            data = fetcher(src)
            stats["looked"] += 1
            if data is None:
                stats["failed"] += 1
                continue                       # not cached: tried again next export
            try:
                f = looker(data)
            except Exception as e:  # noqa: BLE001 - a bad picture never stops the feed
                log.warning("focus: %s: %s", src[:80], e)
                f = {}
            got = {"f": f, "t": now, "v": VERSION}
            cache[src] = got
            if f:
                stats["found"] += 1
        else:
            stats["cached"] += 1
        if got.get("f"):
            img.update(got["f"])
    keep = {k: v for k, v in cache.items() if k in in_use or now - int(v.get("t") or 0) < CACHE_DAYS * 86400}
    try:
        (root / CACHE).write_text(json.dumps(keep, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass
    return stats


if __name__ == "__main__":      # child of look_safe: a picture on stdin, its focus as JSON on stdout
    import sys
    sys.stdout.write(json.dumps(look(sys.stdin.buffer.read())))

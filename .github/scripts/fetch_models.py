"""Download the Hugging Face models the newsroom reads, straight from the Hub, with retries.

Replaces the Actions cache of ~/.cache/huggingface (957 MB restored every hourly run: it was the biggest single
download of the job and the first thing to fail when the cache service throttled). The Hub is not metered against
the repository's cache, and a runner pulls ~1 GB from it in well under a minute.

Same models and same environment variables as nishpaksh/nli.py and nishpaksh/embed.py (the defaults are read from
those files as text, so they cannot drift). Only the files from_pretrained would use are fetched: config and
tokenizer files, and ONE weights file (safetensors if the repo has it, else pytorch_model.bin).

Never fails the job: a model that cannot be fetched is loaded lazily by the pipeline, which already falls back
(NLI: pair is "unread"; embedder: TF-IDF) exactly as it did when the cache was missing.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIES = 4


def model_names() -> list[str]:
    out = []
    for rel, var in (("nishpaksh/nli.py", "NISHPAKSH_NLI_MODEL"), ("nishpaksh/embed.py", "NISHPAKSH_EMBED_MODEL")):
        text = (ROOT / rel).read_text(encoding="utf-8")
        m = re.search(r'os\.getenv\("%s",\s*"([^"]+)"\)' % var, text)
        if not m:
            raise SystemExit(f"could not find the default of {var} in {rel}")
        out.append(os.getenv(var) or m.group(1))
    return out


def wanted(files: list[str]) -> list[str]:
    """The repo's files from_pretrained would download: everything small, plus one weights file."""
    weights = [f for f in files if f.endswith(".safetensors") and "/" not in f]
    if not weights:
        weights = [f for f in files if f in ("pytorch_model.bin",)] or [f for f in files if f.endswith(".bin") and "/" not in f]
    small = [f for f in files if "/" not in f and not f.endswith((".bin", ".safetensors", ".h5", ".msgpack", ".onnx", ".ot", ".md", ".gitattributes"))]
    # sentence-transformers keeps its pooling / dense layers in sub-folders: take those as well, minus extra weight formats
    nested = [f for f in files if "/" in f and not f.endswith((".h5", ".msgpack", ".onnx", ".ot", ".md", ".tflite", ".mlmodel"))
              and not f.startswith(("onnx/", "openvino/", "tf/", "flax/"))]
    return sorted(set(small + weights[:1] + nested))


def fetch(repo: str) -> bool:
    from huggingface_hub import HfApi, snapshot_download
    for attempt in range(1, TRIES + 1):
        try:
            files = HfApi().list_repo_files(repo)
            snapshot_download(repo, allow_patterns=wanted(files))
            print(f"{repo}: ok")
            return True
        except Exception as e:  # noqa: BLE001
            print(f"{repo}: try {attempt}/{TRIES} failed: {str(e)[:160]}")
            time.sleep(5 * attempt)
    return False


def main() -> int:
    t0 = time.time()
    bad = [m for m in model_names() if not fetch(m)]
    print(f"models fetched in {time.time() - t0:.0f}s" + (f"; NOT fetched (loaded lazily): {bad}" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

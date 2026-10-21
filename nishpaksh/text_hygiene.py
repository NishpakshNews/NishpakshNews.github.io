"""Conservative input text repair, before any claim or quotation extraction.

Keep this at the intake boundary: once a claim has been derived from corrupted
text, fixing typography in the published article cannot restore its evidence.
"""
from __future__ import annotations

import re
import unicodedata

from ftfy import fix_text


_META_CHARSET = re.compile(rb'<meta[^>]+charset\s*=\s*["\x27]?\s*([\w.-]+)', re.I)
_HTTP_CHARSET = re.compile(r'charset\s*=\s*["\x27]?\s*([\w.-]+)', re.I)


def decode_page(content: bytes, content_type: str = "", apparent_encoding: str = "") -> str:
    """Decode HTML bytes; don't accept requests' implicit Latin-1 default.

    A declared HTTP or HTML charset wins. Otherwise prefer valid UTF-8 over an
    encoding detector's guess (Indian-language pages are often mislabeled).
    """
    if not content:
        return ""
    found = _HTTP_CHARSET.search(content_type or "")
    meta = _META_CHARSET.search(content[:8192])
    encodings = []
    if found:
        encodings.append(found.group(1))
    if content.startswith((b"\xef\xbb\xbf",)):
        encodings.append("utf-8-sig")
    if meta:
        encodings.append(meta.group(1).decode("ascii", errors="ignore"))
    encodings.extend(["utf-8", apparent_encoding, "windows-1252"])
    for encoding in encodings:
        if not encoding:
            continue
        try:
            return content.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def clean_source_text(value: str | None) -> str:
    """Repair encoding artifacts and normalize canonical Unicode only.

    Preserve quotation marks, punctuation, and whitespace: editorial styling
    belongs after extraction, not in the evidence used to check source quotes.
    """
    return unicodedata.normalize("NFC", fix_text(value or "", normalization="NFC"))

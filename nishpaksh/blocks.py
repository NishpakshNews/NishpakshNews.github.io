"""Page blocks that are not the story (B33): related-link lists, "also read", sidebars.

Two established boilerplate classifiers read the page: trafilatura (which chooses the article body; here with
`favor_precision`) and jusText (which labels every paragraph of the page good / bad from its length, its stop-word
density and its LINK density). A paragraph trafilatura kept is dropped only when jusText calls the same paragraph
boilerplate AND it is mostly link text: a related-story headline or a "Read more" strip, which would otherwise become a
statement of the story. A paragraph jusText merely finds short or odd is kept (better a line too many than a fact
lost). Anything that cannot be analysed leaves the text exactly as it was.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("nishpaksh.blocks")

LINK_DENSITY = 0.5            # share of a paragraph's characters that sit inside links
_DEVA = re.compile(r"[ऀ-ॿ]")


def _key(s: str) -> str:
    return re.sub(r"\W+", " ", s or "").strip().lower()


def link_blocks(html: str) -> set[str]:
    """Normalised texts of the paragraphs jusText calls boilerplate that are mostly links."""
    try:
        import justext
        sample = re.sub(r"<[^>]+>", " ", html[:20000])
        language = "Hindi" if len(_DEVA.findall(sample)) > 60 else "English"
        paras = justext.justext(html.encode("utf-8", "ignore"), justext.get_stoplist(language))
    except Exception as e:  # noqa: BLE001 - no jusText, odd markup: nothing is dropped
        log.debug("jusText unavailable: %s", str(e)[:80])
        return set()
    return {_key(p.text) for p in paras if p.is_boilerplate and p.text and p.links_density() >= LINK_DENSITY}


def clean(html: str, text: str) -> tuple[str, int]:
    """(text without its link-list paragraphs, how many were dropped)."""
    if not text or not html:
        return text, 0
    bad = link_blocks(html)
    if not bad:
        return text, 0
    keep, dropped = [], 0
    for para in text.split("\n"):
        if para.strip() and _key(para) in bad:
            dropped += 1
            continue
        keep.append(para)
    return "\n".join(keep), dropped

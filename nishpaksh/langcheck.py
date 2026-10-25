"""A grammar and style checker over the finished article (LanguageTool, an established rule-based checker; B-grammar).

COUNTED, NEVER ENFORCED: a sentence is never dropped or changed because of it (a false alarm would cost a sentence, and
the rule is to minimise false positives). The article's `narrative.language` = {checked, issues, by_rule: {rule: n}}
says what is left, so the audit can read it, and the owner can decide later which rules to act on.
Spelling (names, Indian words) is left out: LanguageTool does not know them. Needs Java; without Java, the package or a
download it is simply not run (`available()` is False) and nothing else is affected. `set_backend(fn)` for tests:
fn(text) -> list[(rule_id, category, message)].
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("nishpaksh.langcheck")

SKIP_CATEGORIES = {"TYPOS", "CASING", "TYPOGRAPHY"}       # names and house typography are handled elsewhere
_backend = None
_tool = None
_lock = threading.Lock()


def set_backend(fn) -> None:
    global _backend
    _backend = fn


def _load():
    global _tool
    with _lock:
        if _tool is None:
            _tool = False
            try:
                import language_tool_python
                _tool = language_tool_python.LanguageTool("en-US")
            except Exception as e:  # noqa: BLE001 - no Java, no package, no download
                log.warning("LanguageTool unavailable: %s", str(e)[:120])
        return _tool or None


def available() -> bool:
    return _backend is not None or _load() is not None


def issues(text: str) -> list[tuple[str, str, str]] | None:
    """(rule, category, message) for each problem found in a text; None when the checker cannot run."""
    if not text:
        return []
    if _backend is not None:
        found = _backend(text)
    else:
        tool = _load()
        if tool is None:
            return None
        try:
            found = [(m.rule_id, str(m.category), m.message) for m in tool.check(text)]
        except Exception as e:  # noqa: BLE001
            log.warning("LanguageTool failed: %s", str(e)[:120])
            return None
    return [f for f in found if f[1].upper() not in SKIP_CATEGORIES]


def article_stats(paragraphs: list[list[dict]]) -> dict | None:
    """{checked, issues, by_rule} over every sentence of an article, or None when the checker cannot run."""
    by_rule: dict[str, int] = {}
    checked = 0
    for para in paragraphs:
        for sent in para:
            found = issues(sent.get("text") or "")
            if found is None:
                return None
            checked += 1
            for rule, _cat, _msg in found:
                by_rule[rule] = by_rule.get(rule, 0) + 1
    return {"checked": checked, "issues": sum(by_rule.values()), "by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])[:15])}

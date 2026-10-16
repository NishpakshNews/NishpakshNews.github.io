"""The base the three learners share (titles, synonyms, glossary; sessions 9-11 of the translation/learning plan,
Oct 16 2026).

Why: the learned files stayed empty because every run counted from scratch inside a 3-day window and forgot what it
had seen; a word one outlet used on Monday and another on Thursday never added up (owner, Oct 14 2026). Now:

  MEMORY     `learn_candidates` in the newsroom database (encrypted, never Supabase, never the public repo): per
             candidate the independent sources that used it (names.source_key: an agency byline, a copied wire text
             or an owner, the same in every story; state media never counts), the stories, the days, the articles
             already counted (so a re-read article adds nothing), learner-specific facets, and one example kept
             inside the database only. Forgotten after EXPIRE_DAYS without new evidence, unless learned or blocked.
  THE BAR    `Bar`: sources, stories, days, no single day holding more than `max_day_share` of the evidence, and a
             probation from first to latest sighting. "Conventional, not conservative" (owner, Oct 14 2026): the
             devil's advocate is what makes it safe to ask less.
  DEVIL'S    Each learner's `advocate` looks for counter-evidence with checks other than the ones that found the
  ADVOCATE   candidate. It can only HOLD (keep watching) or BLOCK, never approve. A model may judge a few sample
             sentences (quality tier, at most one batched call per learner per day, asked twice with the choices
             swapped), but only to block or hold. Verdicts and reasons are stored on the candidate. Learned entries
             are re-checked on every run from their stored evidence; one that now fails is reported for the owner.
  FUNNEL     How many candidates stop at each rule, logged and kept, so the bars are set from numbers (session 12).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import json
import logging
import pathlib
import re

import yaml

log = logging.getLogger(__name__)

EXPIRE_DAYS = 30
KEEP = 200                  # evidence items kept per set
CUES_FILE = pathlib.Path(__file__).resolve().parent.parent / "config" / "devils_advocate.yaml"


# -- memory --------------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Candidate:
    kind: str
    key: str
    sources: list = dataclasses.field(default_factory=list)
    stories: list = dataclasses.field(default_factory=list)
    days: dict = dataclasses.field(default_factory=dict)          # "YYYY-MM-DD" -> mentions that day
    articles: list = dataclasses.field(default_factory=list)      # counted already: a re-read adds nothing
    facets: dict = dataclasses.field(default_factory=dict)        # learner-specific counts and sets
    example: str = ""
    status: str = "candidate"                                     # candidate / proposed / learned / blocked
    verdict: str = ""                                             # clear / hold / block (the devil's advocate)
    reason: str = ""
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None
    checked_at: dt.datetime | None = None
    dirty: bool = False

    def add(self, article_id, source: str | None, story, day: str, when: dt.datetime | None = None,
            example: str = "") -> bool:
        """One sighting from one article. Returns False when the article was counted before or its source is not
        independent (state media)."""
        if article_id in self.articles or not source:
            return False
        self.articles = (self.articles + [article_id])[-KEEP:]
        if source not in self.sources:
            self.sources = (self.sources + [source])[-KEEP:]
        if story is not None and story not in self.stories:
            self.stories = (self.stories + [story])[-KEEP:]
        self.days[day] = self.days.get(day, 0) + 1
        self.first_seen = min(filter(None, [self.first_seen, when])) if when else self.first_seen
        self.last_seen = max(filter(None, [self.last_seen, when])) if when else self.last_seen
        if example and not self.example:
            self.example = example[:300]
        self.dirty = True
        return True

    def bump(self, facet: str, n: int = 1) -> None:
        self.facets[facet] = self.facets.get(facet, 0) + n
        self.dirty = True

    def put(self, facet: str, value) -> None:
        s = list(self.facets.get(facet) or [])
        if value not in s:
            s = (s + [value])[-KEEP:]
            self.facets[facet] = s
            self.dirty = True


def _row(c: Candidate) -> dict:
    return {"kind": c.kind, "key": c.key, "status": c.status, "verdict": c.verdict, "reason": c.reason[:500],
            "first_seen": c.first_seen, "last_seen": c.last_seen, "checked_at": c.checked_at,
            "evidence": {"sources": c.sources, "stories": [_plain(s) for s in c.stories], "days": c.days,
                         "articles": c.articles, "facets": c.facets, "example": c.example}}


def _plain(x):
    try:
        json.dumps(x)
        return x
    except TypeError:
        return str(x)


def load(store, kind: str) -> dict[str, Candidate]:
    from sqlalchemy import select
    from .db import learn_candidates as t
    try:
        rows = store.rows(select(t).where(t.c.kind == kind))
    except Exception as e:  # noqa: BLE001 - a newsroom copy older than the table (read-only tools)
        log.info("learning: no learn_candidates table yet (%s)", str(e)[:80])
        return {}
    out = {}
    for r in rows:
        ev = r["evidence"] or {}
        out[r["key"]] = Candidate(kind, r["key"], list(ev.get("sources") or []), list(ev.get("stories") or []),
                                  dict(ev.get("days") or {}), list(ev.get("articles") or []),
                                  dict(ev.get("facets") or {}), ev.get("example") or "", r["status"] or "candidate",
                                  r["verdict"] or "", r["reason"] or "", r["first_seen"], r["last_seen"],
                                  r["checked_at"])
    return out


def save(store, cands: dict[str, Candidate], now: dt.datetime | None = None) -> dict:
    """Write the changed candidates; forget the stale ones (no new evidence for EXPIRE_DAYS, still candidates)."""
    from sqlalchemy import delete, insert
    from .db import learn_candidates as t
    now = now or dt.datetime.utcnow()
    stale = [c for c in cands.values() if c.status == "candidate" and c.last_seen
             and (now - c.last_seen).days > EXPIRE_DAYS]
    dirty = [c for c in cands.values() if c.dirty and c not in stale]
    with store.route(insert(t)).engine.begin() as conn:
        for c in stale + dirty:
            conn.execute(delete(t).where(t.c.kind == c.kind, t.c.key == c.key))
        for c in dirty:
            conn.execute(insert(t).values(**_row(c)))
            c.dirty = False
    for c in stale:
        cands.pop(c.key, None)
    return {"saved": len(dirty), "expired": len(stale)}


# -- the bar -------------------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Bar:
    sources: int
    stories: int = 1
    days: int = 1
    max_day_share: float = 1.0
    probation_days: float = 0.0

    def fails(self, c: Candidate) -> list[str]:
        """The rules this candidate does not meet yet, in funnel order (empty: it qualifies)."""
        out = []
        if len(c.sources) < self.sources:
            out.append("sources")
        if len(c.stories) < self.stories:
            out.append("stories")
        if len(c.days) < self.days:
            out.append("days")
        total = sum(c.days.values())
        if total and max(c.days.values()) / total > self.max_day_share:
            out.append("one_day")
        if self.probation_days and (not c.first_seen or not c.last_seen
                                    or (c.last_seen - c.first_seen).total_seconds() < self.probation_days * 86400):
            out.append("probation")
        return out


def funnel(cands, bar: Bar, extra=None) -> dict:
    """{rule: candidates stopped there first}; `extra(c)` adds learner-specific rules after the bar."""
    out: dict[str, int] = {}
    for c in cands:
        if c.status != "candidate":
            out[c.status] = out.get(c.status, 0) + 1
            continue
        why = bar.fails(c) or (extra(c) if extra else [])
        k = why[0] if why else "qualified"
        out[k] = out.get(k, 0) + 1
    return out


# -- the devil's advocate --------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Verdict:
    state: str              # clear / hold / block
    reason: str = ""


CLEAR = Verdict("clear")


def worst(*vs: Verdict) -> Verdict:
    order = {"clear": 0, "hold": 1, "block": 2}
    v = max(vs, key=lambda x: order[x.state]) if vs else CLEAR
    reasons = "; ".join(x.reason for x in vs if x.state == v.state and x.reason)
    return Verdict(v.state, reasons)


@functools.lru_cache(maxsize=2)
def cues(path: str | None = None) -> dict:
    data = yaml.safe_load(pathlib.Path(path or CUES_FILE).read_text(encoding="utf-8")) or {}
    return {k: [str(x) for x in (v or [])] for k, v in data.items()}


def cue_pattern(name: str) -> re.Pattern:
    words = cues().get(name) or []
    if not words:
        return re.compile(r"(?!x)x")
    alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?i)(?<![\wऀ-ॿ])(?:{alt})(?![\wऀ-ॿ])")


def model_due(store, kind: str, now: dt.datetime | None = None) -> bool:
    """At most one devil's-advocate model call per learner per day (stored as a meta candidate)."""
    now = now or dt.datetime.utcnow()
    meta = load(store, "meta").get(f"da:{kind}")
    return not (meta and meta.last_seen and meta.last_seen.date() == now.date())


def model_used(store, kind: str, now: dt.datetime | None = None) -> None:
    now = now or dt.datetime.utcnow()
    c = load(store, "meta").get(f"da:{kind}") or Candidate("meta", f"da:{kind}")
    c.last_seen, c.first_seen, c.dirty = now, c.first_seen or now, True
    c.status = "learned"                           # never expires
    save(store, {c.key: c}, now)


def ask_twice(router, question: str, items: list[str], choices: tuple[str, ...], max_tokens: int = 400) -> list[str | None]:
    """A fixed-choice question per item, asked twice with the choices listed in reverse order; an item's answer is
    kept only when both askings agree, else None. Quality tier; no quota or a refusal: all None."""
    from .router import CallFailed, QuotaExhausted, parse_json
    if router is None or not items:
        return [None] * len(items)
    try:
        if router.remaining_now("quality") <= 0:
            return [None] * len(items)
    except Exception:  # noqa: BLE001
        return [None] * len(items)
    answers = []
    for order in (choices, tuple(reversed(choices))):
        prompt = (question + "\n\nAnswer each with exactly one of: " + ", ".join(order) + ".\n\n"
                  + "\n".join(f"{k + 1}. {it}" for k, it in enumerate(items))
                  + f'\n\nAnswer as JSON: {{"answers": ["...", ...]}} with exactly {len(items)} entries, in order.')
        try:
            res = router.call("quality", prompt, json_out=True, max_output_tokens=max_tokens)
        except (QuotaExhausted, CallFailed):
            return [None] * len(items)
        data = res.data if getattr(res, "data", None) is not None else parse_json(res.text or "")
        got = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(got, list) or len(got) != len(items):
            return [None] * len(items)
        answers.append([str(x).strip().lower() for x in got])
    return [a if a == b and a in choices else None for a, b in zip(*answers)]


def day_of(when) -> str:
    return (when or dt.datetime.utcnow()).date().isoformat()


def router_for(store):
    """A router for the learners' devil's-advocate looks (quality tier only), or None without keys."""
    try:
        from .config import gemini_api_keys, load_yaml
        from .router import GeminiBackend, Router
        keys = gemini_api_keys()
        if not keys:
            return None
        r = Router(load_yaml("models.yaml")["tiers"], [GeminiBackend(k) for k in keys], store)
        r.resolve()
        return r
    except Exception as e:  # noqa: BLE001 - no model: candidates wait for their look
        log.info("learning: no router (%s)", str(e)[:120])
        return None


def near(cands, bar: Bar, extra=None, n: int = 15) -> list[dict]:
    """The candidates with the most evidence, each with where it stands (its status, the first rule it misses, or
    the devil's advocate's reason): the readout the bars are judged from."""
    out = []
    for c in sorted(cands, key=lambda c: (-len(c.sources), -len(c.days), c.key))[:n]:
        why = bar.fails(c) or (extra(c) if extra else [])
        out.append({"key": c.key, "sources": len(c.sources), "stories": len(c.stories), "days": len(c.days),
                    "status": c.status, "stops_at": why[0] if why else "", "reason": c.reason})
    return out


LOADED_MIN_TAGS = 3     # readings that must tag a word as loaded before the learners treat it so


def loaded_set(tags) -> set[str]:
    """Words readings tagged as loaded at least LOADED_MIN_TAGS times: one quirky reading tagging "relief" or
    "detained" must not block a neutral word for good (the replay of Oct 16 2026)."""
    from collections import Counter
    c = Counter(tags)
    return {w for w, n in c.items() if n >= LOADED_MIN_TAGS}

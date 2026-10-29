"""Lines of "Also in these reports" that belong in the article (B9 step 3; owner, Oct 29 2026). SHADOW: nothing calls it.

`payload["also"]` holds statements the pipeline kept out of the written article: lines `belong.check` tagged "other" (another
case on the same page, or a model that was not sure), and core lines `compose.trim_to_cap` cut ("cap"). Reading 25 published
stories (276 lines), some are plainly part of the story (a detail of the same decision, a background sentence, a figure) and
many are not (other events from a roundup page, an outlet describing itself, half sentences). This module decides by CODE, line
by line, which would read as part of the article, and where. A line is inserted only when ALL of these hold:

  form        a whole sentence: 6+ words, opens with a capital, brackets balanced, ends cleanly, does not lean on a sentence
              before it (a pronoun), is not the outlet talking about itself, was not read from a page's own navigation
  novelty     the article does not already say it (weighted containment against every written line; `tidy.judge` agrees
              it is not a repeat or a covered line)
  subject     it is about THIS story: it names something the story names that is not the story's setting (named in under a
              third of its lines), or is close to the story's headline and lead by weighted cosine
  no clash    `tidy.judge` finds no conflict between it and any written line (a conflict is for the dispute step, not for
              a quiet insertion)
  role        its role is background, explanation or core; a line read as a RELATED event stays out unless it names
              something the story names that is rare in the story

It goes into the paragraph whose lines are nearest to it (weighted cosine), right after the nearest line; none near enough =
it stays in "Also". It keeps its own colour (`narrative.shade`), so an inserted one-outlet line reads purple. Insertion runs
BEFORE the repair pass and `tidy` (which then folds any repeat it makes). The first measure is in `tools/insert_shadow.py`.
"""
from __future__ import annotations

import re

from . import tidy
from .relate import Profile

MIN_WORDS = 6
NOVEL_MAX = 0.6        # a line whose weight is held this much by an article line is already said
TIE_COS = 0.30         # weighted cosine to the headline + lead from which a line is about this story
PLACE_MIN = 0.22       # weighted cosine to the nearest written line from which a line has a place
SETTING_SHARE = 1 / 3  # a name in more than this share of the story's lines is its setting and ties nothing
NAME_COVER = 0.6      # of a line's names (by weight) this share must be names the story has: "Khelo India Sports Goods Scheme" is another scheme
MAX_SHARE = 0.25      # at most this share of the written lines is added (the cap that made them "also" had a reason)
ROLES = ("background", "explanation", "core")

_CLOSE = {"(": ")", "[": "]", "{": "}"}
_BAD_END = re.compile(r"(?i)(?:,|;|:|\b(?:and|or|but|of|the|a|an|to|in|on|at|for|with|by|from|that|which)\s*)$")


def form_problem(text: str, outlets: set[str] = frozenset(), speaker: str | None = None) -> str | None:
    t = (text or "").strip()
    if len(t.split()) < MIN_WORDS:
        return "too short"
    if not t[0].isupper() and not t[0].isdigit() and t[0] not in "“\"'‘":
        return "does not open like a sentence"
    if _BAD_END.search(t):
        return "cut off"
    stack = []
    for ch in t:
        if ch in _CLOSE:
            stack.append(_CLOSE[ch])
        elif ch in _CLOSE.values():
            if not stack or stack.pop() != ch:
                return "brackets do not balance"
    if stack:
        return "brackets do not balance"
    if tidy._LEANS.match(t):
        return "leans on a sentence before it"
    low = {o.lower() for o in outlets if o}
    if speaker and speaker.lower() in low:
        return "an outlet speaking of itself"
    if sum(ch.isalpha() for ch in t) < 0.6 * len(t):
        return "mostly not words"
    return None


SUBJECT_PROMPT = """A news article has this headline. Is the extra line about the SAME subject as the headline, or about ANOTHER one
of the same kind (another scheme, case, match, person, place or event that the article merely mentions)?

Answer with exactly one word: SAME, ANOTHER or UNSURE.

Example
HEADLINE: Cabinet approves scheme to boost domestic container manufacturing
LINE: The Cabinet also approved the Khelo India Sports Goods Manufacturing Scheme with an outlay of 1,856 crore.
ANSWER: ANOTHER
HEADLINE: Bharatiya Rail sets 25 November deadline for 1,265 posts
LINE: The selection process for Master Posts includes a computer based test and document verification.
ANSWER: SAME
HEADLINE: Cyclone Arnab upgraded by the weather department
LINE: Maximum temperature in Shimla is estimated at 23 degrees.
ANSWER: ANOTHER

HEADLINE: {h}
LINE: {t}
ANSWER:"""

_GENERIC = {"india", "indian", "govern", "state", "centr", "union", "minist", "court", "suprem"}


def _alias(x: str, y: str) -> bool:
    from .reconcile import names_alias
    return names_alias(x, y)


def shared_names(p: Profile, profiles: list[Profile]) -> set[str]:
    setting = _setting(profiles)
    return {n for n in p.names if n not in _GENERIC and any(n in q.names for q in profiles)} - setting


def _setting(profiles: list[Profile]) -> set[str]:
    count: dict[str, int] = {}
    for p in profiles:
        for n in p.names:
            count[n] = count.get(n, 0) + 1
    limit = max(2, int(len(profiles) * SETTING_SHARE))
    return {n for n, c in count.items() if c > limit}


def judge_line(line: dict, written: list[str], profiles: list[Profile], W, anchor: Profile, outlets: set[str],
               ask=None, headline: str = "") -> dict:
    """{"ok": bool, "why": reason, "place": (paragraph line index, cos) | None} for one `also` line."""
    text = line.get("text") or ""
    bad = form_problem(text, outlets, line.get("speaker"))
    if bad:
        return {"ok": False, "why": bad}
    if line.get("role") not in ROLES and line.get("role") != "related":
        return {"ok": False, "why": f"role {line.get('role')}"}
    p = Profile(text)
    best, best_cos, clash = None, 0.0, None
    for k, (t, q) in enumerate(zip(written, profiles)):
        v = tidy.judge(0, 1, text, t, p, q, W)
        if v.outcome in ("same", "covered"):
            return {"ok": False, "why": "the article already says it"}
        if v.outcome == "conflict":
            clash = clash or (t, v.why)
        cos, ca, cb = tidy.measures(W, tidy.bag(p), tidy.bag(q))
        if ca >= NOVEL_MAX:
            return {"ok": False, "why": "the article already says it"}
        if cos > best_cos:
            best, best_cos = k, cos
    if clash:
        return {"ok": False, "why": "clashes with a written line (for the dispute step)", "clash": clash}
    setting = _setting(profiles)
    shared = {n for n in p.names if any(n in q.names for q in profiles)} - setting
    cos_anchor = tidy.measures(W, tidy.bag(p), tidy.bag(anchor))[0]
    story_names = set().union(*(q.names for q in profiles)) if profiles else set()
    mine = {n for n in p.names if n not in _GENERIC}
    if len(mine) >= 2:
        w_all = sum(W.w(n) for n in mine)
        w_in = sum(W.w(n) for n in mine if any(n == m or _alias(n, m) for m in story_names))
        if w_all and w_in / w_all < NAME_COVER:
            # New names beside a name the story has are either a detail of it ("Master Posts") or a sibling (another scheme).
            # No weight tells them apart; ONE closed model question does, and without it the line stays out.
            word = None
            if ask is not None and shared_names(p, profiles):
                m = re.match(r"\W*([A-Za-z]+)", ask(SUBJECT_PROMPT.format(h=headline, t=text)) or "")
                word = m.group(1).upper() if m else None
            if word != "SAME":
                return {"ok": False, "why": "names something the story does not (another subject)"}
    tied = bool(shared) or cos_anchor >= TIE_COS
    if line.get("role") == "related" and not shared:
        return {"ok": False, "why": "another event"}
    if not tied:
        return {"ok": False, "why": "not about this story"}
    if best is None or best_cos < PLACE_MIN:
        return {"ok": False, "why": "no place near it"}
    return {"ok": True, "why": "belongs", "place": (best, round(best_cos, 2)), "shared": sorted(shared)[:4]}


def insert(paragraphs: list[list[dict]], also: list[dict], headline: str = "", shade=None, source_index=None, ask=None) -> tuple[list[list[dict]], dict]:
    """The paragraphs with the lines that belong inserted, and a report. Nothing is changed in place."""
    paras = [[dict(x) for x in para] for para in paragraphs]
    flat = [(n, k) for n, para in enumerate(paras) for k in range(len(para))]
    written = [paras[n][k]["text"] for n, k in flat]
    profiles = [Profile(t) for t in written]
    lead = " ".join(written[:2])
    anchor = Profile((headline + " " + lead).strip())
    cand = [Profile(x.get("text") or "") for x in also]
    W = tidy.weights(profiles + cand + [anchor])
    outlets = {s.get("outlet") for x in also for s in x.get("sources") or [] if isinstance(s, dict)}
    report = {"lines": len(also), "inserted": 0, "why_not": {}, "items": []}
    # strongest tie first, so two lines about one point land in the order of their nearness
    judged = [(judge_line(x, written, profiles, W, anchor, outlets, ask, headline), x) for x in also]
    room = max(1, int(len(written) * MAX_SHARE))
    for res, x in sorted(judged, key=lambda t: -(t[0].get("place", (0, 0))[1] if t[0]["ok"] else -1)):
        item = {"text": x.get("text"), **{k: v for k, v in res.items() if k != "ok"}, "ok": res["ok"]}
        if res["ok"] and report["inserted"] >= room:
            res = {"ok": False, "why": "room is used (a quarter of the article)"}
            item.update(res)
        if not res["ok"]:
            report["why_not"][res["why"]] = report["why_not"].get(res["why"], 0) + 1
            report["items"].append(item)
            continue
        k = res["place"][0]
        n, pos = flat[k]
        line = {"text": x["text"], "ids": [x["id"]] if x.get("id") is not None else [],
                "class": (shade(x) if shade else x.get("verdict") or "unverified"),
                "sources": [source_index.get(s.get("url")) for s in x.get("sources") or [] if source_index and source_index.get(s.get("url"))]
                if source_index else []}
        line["_inserted"] = True
        paras[n].insert(_after(paras[n], written[k]), line)
        report["inserted"] += 1
        item["paragraph"] = n
        report["items"].append(item)
    for para in paras:
        for x in para:
            x.pop("_inserted", None)
    return paras, report


def _after(para: list[dict], anchor_text: str) -> int:
    """Index right after the anchor line (and after lines already inserted there)."""
    for i, x in enumerate(para):
        if x["text"] == anchor_text:
            j = i + 1
            while j < len(para) and para[j].get("_inserted"):
                j += 1
            return j
    return len(para)

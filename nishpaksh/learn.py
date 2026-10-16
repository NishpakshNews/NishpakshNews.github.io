"""Titles learned from the outlets, PROPOSED to the owner (owner, Oct 10 and Oct 14 2026; session 9 of the
translation/learning plan, Oct 16 2026).

config/titles.yaml is written by hand and cannot hold every title in Indian news ("Captain", "Chancellor",
"Superintendent", ...). A word that stands, mid-sentence, right before the full name of a person the statements quote
("... said Skipper Rohit Sharma") may be a title. Each run reads the newsroom's recent English articles, finds such
words, and adds what it saw to the word's memory (learning.py: evidence builds up across runs and days; an article
read again adds nothing).

THE BAR (conventional, with the devil's advocate behind it; owner, Oct 14 2026):
  3+ independent sources (state media never counts), 3+ days with no single day holding over half the sightings,
  7 days from first to latest sighting, 2+ different people, 1+ sighting from a wire agency or a foreign outlet
  (outside any one owner's pressure), and the word also used in lower case ("the skipper said": a common noun).

THE DEVIL'S ADVOCATE (only holds or blocks): a nickname is not a title someone holds because outlets repeat it
(the owner's example: "Pappu"). Code: the word is on `never_titles` (config/devils_advocate.yaml); a reading tagged
it as a loaded word; over 70% of sightings stand before ONE person (a real title is shared: Justice X, Justice Y); a
label cue before it in over 20% ("dubbed", "called", "so-called", "कहकर"); a dispute or insult word near it in over
10% ("jibe", "taunt", "तंज"); inside quotation marks in over half (hold). Then, for words code clears, one question on
the quality tier (at most once a day for all titles together, asked twice with the choices swapped): "a formal title
or office the person holds, or a nickname, label or insult?". "label" blocks; no agreed answer or no quota holds.

NOTHING IS LEARNED AUTOMATICALLY: a word that passes is written to config/titles_proposed.yaml (words, people and
counts only: no article text, the repository is public). To APPROVE, move its line into titles_learned.yaml under
`roles:`; to REFUSE, add the word to `rejected:` in titles_learned.yaml. The proposals file is rewritten every run
from the newsroom's memory; its `review:` part lists approved titles the devil's advocate now objects to.

    python -m nishpaksh.learn [--days 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from . import learning as L
from . import titles

log = logging.getLogger(__name__)

FILE = "titles_learned.yaml"
PROPOSED = "titles_proposed.yaml"
KIND = "title"
BAR = L.Bar(sources=3, stories=1, days=3, max_day_share=0.5, probation_days=7)
MIN_NAMES = 2
MIN_LOWER = 2
MIN_ANCHORS = 1
CONCENTRATION = 0.7
LABEL_SHARE = 0.2
DISPUTE_SHARE = 0.1
QUOTED_SHARE = 0.5
CONTEXTS = 5                # sample contexts kept per word (in the newsroom only), for the model's look
MIN_FOR_SHARES = 5          # sightings before a share (one person) can block: 2 of 2 says nothing (replay, Oct 16)
NEVER = "on the never list"
LOADED = "a reading tagged it as a loaded word"
PERMANENT = {NEVER, LOADED}
WAITING = "waiting for the model's look (once a day)"

HEADER = """# Titles learned from the news (nishpaksh/learn.py, owner Oct 10 2026). titles.py reads this file after the
# hand-written titles.yaml, which always wins. Titles are never learned automatically (owner, Oct 14 2026): the job
# proposes them in titles_proposed.yaml; to APPROVE one, move its line from there to `roles:` below.
#
# A WRONG ENTRY: delete its line below and add its word to `rejected:`, so it is never proposed again.
# Keep `roles:` LAST in this file.
rejected: []

roles:
"""

PROPOSED_HEADER = """# Titles the outlets use, PROPOSED by nishpaksh/learn.py (rewritten every run; the owner approves, Oct 14 2026).
# Each passed the bar (3+ independent sources, 3+ days, 7 days of probation, 2+ people, a wire or foreign outlet)
# and the devil's advocate (not one person's nickname, no label or insult cues, the model's look).
#   APPROVE: move the line into titles_learned.yaml under `roles:`.   REFUSE: add the word to `rejected:` there.
# `review:` lists approved titles the devil's advocate now objects to (look again; nothing changes by itself).
"""

_NOT = {"the", "a", "an", "and", "but", "or", "for", "from", "with", "that", "this", "also", "after", "before",
        "while", "when", "then", "later", "earlier", "meanwhile", "however", "yesterday", "today", "tomorrow",
        "according", "said", "says", "told", "by", "on", "in", "at", "to", "of", "as", "if", "since", "during"}

_WORD = r"[A-Z][a-z][\w'’]*(?:-[A-Z][a-z]+)?"


# -- the owner's files ----------------------------------------------------------------------------------------------

def _learned_doc() -> dict:
    try:
        from .config import load_yaml
        return load_yaml(FILE) or {}
    except Exception:  # noqa: BLE001 (no file, or one that does not parse: nothing breaks)
        return {}


def rejected() -> set[str]:
    """The words the owner has struck out, lower case."""
    return {str(x).lower() for x in (_learned_doc().get("rejected") or [])}


def approved() -> set[str]:
    """The words the owner moved into the learned file, lower case."""
    out = set()
    for r in _learned_doc().get("roles") or []:
        if isinstance(r, dict):
            out.update(str(f).lower() for f in r.get("forms") or [])
    return out


def _known(word: str) -> bool:
    w = word.lower()
    return (word in titles.title_words() or word in titles.person_title_words() or w in titles.role_nouns()
            or w in {h.lower() for h in titles.honorifics()} or w in _NOT or w in titles._OPENERS)


def _bare(name: str) -> str:
    return titles.strip(re.sub(r"\s+", " ", name or "").strip())


def person_names(attributed: list[str]) -> set[str]:
    """Full names (2 to 4 capitalised words) among the names statements are attributed to; titles stripped, bodies out."""
    from . import voice
    out = set()
    for raw in attributed:
        name = _bare(raw)
        words = name.split()
        if (2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Z][\w.'’-]*", w) for w in words)
                and not voice.is_body(name) and name == " ".join(words)):
            out.add(name)
    return out


# -- sightings (pure) ------------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Sighting:
    word: str
    article_id: int
    name: str
    context: str
    label: bool
    dispute: bool
    quoted: bool


def _quoted(text: str, i: int) -> bool:
    """Inside quotation marks: an odd number of straight quotes before it, or a curly quote opened and not closed."""
    before = text[max(0, i - 400):i]
    return before.count('"') % 2 == 1 or before.rfind("“") > before.rfind("”")


def sightings(articles: list[dict], names_of: dict[int, set[str]], outlets_known=frozenset()) -> list[Sighting]:
    """Every word standing mid-sentence right before a quoted person's full name. `articles`: id, text;
    `names_of`: article id -> the full names of its speakers."""
    label, dispute = L.cue_pattern("label"), L.cue_pattern("dispute")
    skip = {o.lower() for o in outlets_known}
    out = []
    for a in articles:
        text = a.get("text") or ""
        for name in names_of.get(a["id"]) or ():
            sur = {w.lower() for w in name.split()}
            for m in re.finditer(rf"(?<=[a-z,] )({_WORD})\s+{re.escape(name)}(?![\w-])", text):
                word = m.group(1)
                if _known(word) or word.lower() in sur or word.lower() in skip or len(word) < 3:
                    continue
                s, e = m.start(1), m.end()
                around = text[max(0, s - 80):min(len(text), e + 80)]
                out.append(Sighting(word, a["id"], name, " ".join(around.split()),
                                    bool(label.search(text[max(0, s - 40):s])), bool(dispute.search(around)),
                                    _quoted(text, s)))
    return out


def lower_uses(word: str, corpus: str) -> int:
    return len(re.findall(rf"(?<![\w-]){re.escape(word.lower())}(?![\w-])", corpus))


def record(cands: dict[str, L.Candidate], seen: list[Sighting], info: dict[int, dict], corpus: str) -> int:
    """Add the sightings to the words' memory. `info`: article id -> {source, story, when, anchor}. Returns how many
    sightings were new evidence."""
    n = 0
    for s in seen:
        a = info.get(s.article_id) or {}
        c = cands.get(s.word)
        if c is None:
            c = cands[s.word] = L.Candidate(KIND, s.word)
        if not c.add(s.article_id, a.get("source"), a.get("story"), L.day_of(a.get("when")), a.get("when")):
            continue
        n += 1
        c.bump("sightings")
        per = dict(c.facets.get("per_person") or {})
        per[s.name] = per.get(s.name, 0) + 1
        c.facets["per_person"] = per
        c.put("people", s.name)
        for flag in ("label", "dispute", "quoted"):
            if getattr(s, flag):
                c.bump(flag)
        if a.get("anchor"):
            c.put("anchors", a["source"])
        ctx = list(c.facets.get("contexts") or [])
        if len(ctx) < CONTEXTS:
            c.facets["contexts"] = ctx + [s.context[:240]]
    for w, c in cands.items():
        if c.dirty:
            c.facets["lower"] = max(int(c.facets.get("lower") or 0), lower_uses(w, corpus))
    return n


# -- the bar and the devil's advocate (pure) ----------------------------------------------------------------------

def extra_rules(c: L.Candidate) -> list[str]:
    out = []
    if len(c.facets.get("people") or []) < MIN_NAMES:
        out.append("people")
    if len(c.facets.get("anchors") or []) < MIN_ANCHORS:
        out.append("anchor")
    if int(c.facets.get("lower") or 0) < MIN_LOWER:
        out.append("lower_case")
    return out


def advocate(c: L.Candidate, loaded=frozenset()) -> L.Verdict:
    """Code's case against a word (hold or block, never approve)."""
    w = c.key.lower()
    n = int(c.facets.get("sightings") or 0) or 1
    if w in {x.lower() for x in L.cues().get("never_titles", [])}:
        return L.Verdict("block", NEVER)
    if w in loaded:
        return L.Verdict("block", LOADED)
    per = c.facets.get("per_person") or {}
    total = sum(per.values())
    if total >= MIN_FOR_SHARES and max(per.values()) / total > CONCENTRATION:
        top = max(per, key=per.get)
        return L.Verdict("block", f"{per[top]} of {total} sightings stand before {top}: a nickname sticks to one person")
    out = []
    if int(c.facets.get("label") or 0) / n > LABEL_SHARE:
        out.append(L.Verdict("block", "outlets report it as what someone was called (dubbed, branded, so-called)"))
    if int(c.facets.get("dispute") or 0) / n > DISPUTE_SHARE:
        out.append(L.Verdict("block", "insult or dispute words stand near it (jibe, taunt, तंज)"))
    if int(c.facets.get("quoted") or 0) / n > QUOTED_SHARE:
        out.append(L.Verdict("hold", "mostly inside quotation marks: someone's words, not the outlets'"))
    return L.worst(*out) if out else L.CLEAR


MODEL_QUESTION = ("Each numbered line is a word that news outlets wrote right before a person's name, with sentences "
                  "it stood in. Is the word a formal TITLE or office the person holds (like Justice, Captain, "
                  "Commissioner), or a LABEL: a nickname, an epithet or an insult someone gave them?")


def model_look(router, cands: list[L.Candidate]) -> dict[str, L.Verdict]:
    items = [f'"{c.key}": ' + " | ".join(c.facets.get("contexts") or []) for c in cands]
    answers = L.ask_twice(router, MODEL_QUESTION, items, ("title", "label", "unsure"), max_tokens=60 + 20 * len(items))
    out = {}
    for c, a in zip(cands, answers):
        if a == "title":
            out[c.key] = L.CLEAR
        elif a == "label":
            out[c.key] = L.Verdict("block", "the model's look: a nickname or label, not a title held")
        else:
            out[c.key] = L.Verdict("hold", "the model's look gave no agreed answer")
    return out


def decide(cands: dict[str, L.Candidate], loaded=frozenset(), router=None, model_allowed: bool = True,
           now: dt.datetime | None = None, no=None, yes=None) -> tuple[list[L.Candidate], list[dict], bool]:
    """Statuses from the owner's files, the bar and the devil's advocate: (newly proposed, review notes, whether the
    model was asked)."""
    now = now or dt.datetime.utcnow()
    no = rejected() if no is None else no
    yes = approved() if yes is None else yes
    review, fresh, waiting = [], [], []

    def mark(c, **kw):
        for k, v in kw.items():
            setattr(c, k, v)
        c.checked_at, c.dirty = now, True

    for c in cands.values():
        w = c.key.lower()
        if w in no:
            if c.status != "blocked":
                mark(c, status="blocked", verdict="block", reason="refused by the owner")
            continue
        if w in yes:
            if c.status != "learned":
                mark(c, status="learned")
            v = advocate(c, loaded)
            if v.state == "block":
                review.append({"word": c.key, "reason": v.reason})
            continue
        if c.status == "blocked":
            continue
        v = advocate(c, loaded)
        if v.state == "block":
            # for good only when the reason cannot change (the never list, a loaded word); a block from shares of
            # the evidence (one person, label or insult cues) is looked at again as evidence grows
            if v.reason in PERMANENT:
                mark(c, status="blocked", verdict="block", reason=v.reason)
            elif c.verdict != "block" or c.reason != v.reason:
                mark(c, verdict="block", reason=v.reason)
            continue
        if c.status == "proposed":
            continue
        if BAR.fails(c) or extra_rules(c):
            continue
        if v.state == "hold":
            if c.reason != v.reason:
                mark(c, verdict="hold", reason=v.reason)
            continue
        waiting.append(c)
    used = False
    if waiting and model_allowed and router is not None:
        used = True
        looks = model_look(router, waiting)
        for c in waiting:
            v = looks.get(c.key, L.Verdict("hold", "not looked at"))
            if v.state == "clear":
                mark(c, status="proposed", verdict="clear", reason="the model's look: a title held")
                fresh.append(c)
            elif v.state == "block":
                mark(c, status="blocked", verdict="block", reason=v.reason)
            else:
                mark(c, verdict="hold", reason=v.reason)
    else:
        for c in waiting:
            if c.reason != WAITING:
                mark(c, verdict="hold", reason=WAITING)
    return fresh, review, used


# -- the proposals file --------------------------------------------------------------------------------------------

def entry(c: L.Candidate) -> dict:
    return {"id": f"learned_{re.sub(r'[^a-z0-9]+', '_', c.key.lower()).strip('_')}", "forms": [c.key],
            "ref": f"the {c.key.lower()}", "learned": (c.checked_at or dt.datetime.utcnow()).date().isoformat(),
            "seen": sorted(c.facets.get("people") or [])[:3], "sources": len(c.sources), "days": len(c.days)}


def line(e: dict) -> str:
    """One entry as one flow-style YAML line (JSON strings are valid YAML strings)."""
    return "  - {" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in e.items()) + "}\n"


def write_proposals(path: Path, proposed: list[dict], review: list[dict]) -> None:
    body = PROPOSED_HEADER + "\n"
    body += ("proposed:\n" + "".join(line(e) for e in proposed)) if proposed else "proposed: []\n"
    body += "\n" + (("review:\n" + "".join(line(r) for r in review)) if review else "review: []\n")
    path.write_text(body, encoding="utf-8")


# -- the run -------------------------------------------------------------------------------------------------------

def run(store, router=None, days: float = 3, dry_run: bool = False, config_dir: Path | None = None) -> dict:
    """Read the newsroom's recent English articles and their speakers, add to the memory, decide, write proposals."""
    from . import heavy, names as N
    from .config import CONFIG_DIR
    from .db import articles, claims, select
    from .ownership import region_of
    cfg = config_dir or CONFIG_DIR
    now = dt.datetime.utcnow()
    since = now - dt.timedelta(days=days)
    rows = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.lang,
                             articles.c.wire_group, articles.c.story_id, articles.c.published_at,
                             *heavy.columns(store, "text")).where(articles.c.published_at >= since))
    rows = [r for r in heavy.fill(store, rows, "text") if r.get("text") and (r.get("lang") or "en") == "en"]
    ids = [r["id"] for r in rows]
    attributed: dict[int, list[str]] = defaultdict(list)
    loaded_tags: list[str] = []
    for start in range(0, len(ids), 400):
        for c in store.rows(select(claims.c.article_id, claims.c.attributed_to, claims.c.loaded_words)
                            .where(claims.c.article_id.in_(ids[start:start + 400]))):
            if c.get("attributed_to"):
                attributed[c["article_id"]].append(c["attributed_to"])
            for w in c.get("loaded_words") or []:
                loaded_tags.extend(x.lower() for x in str(w).split())
    names_of = {i: person_names(v) for i, v in attributed.items()}
    info = {r["id"]: {"source": N.source_key(r), "story": r.get("story_id"), "when": r.get("published_at"),
                      "anchor": bool(r.get("agency")) or region_of(r.get("outlet"), r.get("url"), r.get("lang")) == "world"}
            for r in rows}
    seen = sightings(rows, names_of, {r["outlet"] for r in rows if r.get("outlet")})
    cands = L.load(store, KIND)
    new = record(cands, seen, info, "\n".join(r["text"] for r in rows))
    loaded = L.loaded_set(loaded_tags)
    fresh, review, used = decide(cands, loaded, router, L.model_due(store, KIND, now), now)
    out = {"articles": len(rows), "sightings": len(seen), "new_evidence": new, "candidates": len(cands),
           "funnel": L.funnel(cands.values(), BAR, extra_rules), "near": L.near(cands.values(), BAR, extra_rules), "proposed_now": [c.key for c in fresh],
           "review": review, "model_asked": used}
    if dry_run:
        return out
    if used:
        L.model_used(store, KIND, now)
    out.update(L.save(store, cands, now))
    if not (cfg / FILE).exists():
        (cfg / FILE).write_text(HEADER, encoding="utf-8")
    write_proposals(cfg / PROPOSED, [entry(c) for c in sorted(cands.values(), key=lambda c: c.key)
                                     if c.status == "proposed"], review)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=float, default=3)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .config import database_url
    from .db import Store
    store = Store(database_url())
    store.init()
    res = run(store, L.router_for(store), a.days, a.dry_run)
    log.info("title candidates: %s", res.get("funnel"))
    print(json.dumps(res, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

"""Synonyms learned from the outlets (owner, Oct 11 2026: "can synonyms grow too, on its own"; rebuilt on the
learners' base in session 9-10 of the translation/learning plan, Oct 16 2026).

config/synonyms.yaml is written by hand and cannot hold every pair of words the outlets use for one thing. When two
outlets say one fact in different words and code cannot tell, the model is asked twice (match.same_facts) and, on two
"same", the statements are merged under one `canonical_id`. That merge is the evidence: two claims under one merged
statement, from different independent outlets, the same words but for ONE (3+ words around it, same numbers and
names, both swapped words lower case), which code alone had NOT already called the same. Each run adds what it sees
to the pair's memory in the newsroom (learning.py), so a pair seen on Monday and on Thursday adds up.

THE BAR (the lightest of the three learners: a wrong pair merges two statements, which contradictions usually
expose): 2+ independent sources, 2+ stories, 2+ days with no day over 70% of the evidence, 3+ merged statements.

THE DEVIL'S ADVOCATE (only holds or blocks; the owner's worry: protesters / rioters, regime / government):
  - EVIDENCE AGAINST, remembered for good: both words in one statement ("injured and killed"), or the same swap
    between two statements the pipeline judged contradictory;
  - a word on `never:` (synonyms.yaml) or refused (`rejected:` in the learned file);
  - a word that limits a claim (the fidelity glossary: only, alleged, at least ...);
  - a word a reading tagged as loaded;
  - FRAMING SPLIT (hold): no outlet has used both words; each sticking to its own word may be two judgments;
  - the model's look (quality tier, once a day for all pairs, asked twice with the choices swapped): does swapping
    keep the meaning or change stance, degree, certainty or judgment? "changes" blocks; no agreed answer holds.
A pair that passes is LEARNED automatically (owner, Oct 14 2026), appended to config/synonyms_learned.yaml (words and
counts only: no article text, the repository is public), read by relate.py after the hand-written file. A learned
pair the advocate later blocks is taken out of the file again. A WRONG ENTRY: delete its line and add its two words
as one line to `rejected:` at the top of the file: it is never learned again.

    python -m nishpaksh.learn_synonyms [--file config/synonyms_learned.yaml] [--days 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import learning as L
from . import relate
from .frames import STOP, _stem

log = logging.getLogger(__name__)

FILE = "synonyms_learned.yaml"
KIND = "synonym"
BAR = L.Bar(sources=2, stories=2, days=2, max_day_share=0.7)
MIN_STATEMENTS = 3      # different merged statements that showed the pair
MIN_CONTEXT = 3         # words the two lines share around the swapped word
WAITING = "waiting for the model's look (once a day)"
MAX_CLAIMS = 12         # claims of one statement compared with each other (a bug cannot make this explode)
MAX_NEW = 5             # most pairs one run adds

HEADER = """# Synonyms learned from the news by nishpaksh/learn_synonyms.py (owner, Oct 11 2026). The job appends here and
# commits it; nishpaksh/relate.py reads it after the hand-written synonyms.yaml, which always wins.
# A pair enters this file when outlets said one fact (merged by the model, asked twice) in the same words but for
# ONE word, in 3+ statements of 2+ stories, from 2+ independent sources on 2+ days, and the devil's advocate found
# nothing against it (learning.py). Counts only, no article text (the repository is public). A pair the advocate
# later objects to is taken out again.
#
# A WRONG ENTRY: delete its line below and add its two words as one line to `rejected:` (for example
# "killed murdered"), so it is never learned again. To keep two words apart in all cases, also add them to `never:`
# in synonyms.yaml.
rejected: []

groups:
"""

_NEG_PREFIX = ("un", "in", "im", "il", "ir", "non", "dis", "anti", "de", "mis", "counter")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text or "")


def _opposed(x: str, y: str) -> bool:
    """\"able\" / \"unable\", \"legal\" / \"illegal\": a negating prefix is an opposite, never a synonym."""
    return any(x == p + y or y == p + x for p in _NEG_PREFIX)


def swap(a: str, b: str) -> tuple[str, str] | None:
    """The one pair of words (lower case) in which two lines differ, when they are otherwise word for word the
    same (same length, 3+ words around it, the swapped word not first). None when they differ in more, or the word
    cannot be a synonym: not lower case, a number, a small or filler word, a negation, a contrast word, the same
    stem (arrest / arrests), an opposite by prefix."""
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) != len(tb) or len(ta) < MIN_CONTEXT + 1:
        return None
    diff = [i for i, (x, y) in enumerate(zip(ta, tb)) if x.lower() != y.lower()]
    if len(diff) != 1 or diff[0] == 0:
        return None
    x, y = ta[diff[0]], tb[diff[0]]
    if not (x.isalpha() and y.isalpha() and x.islower() and y.islower() and len(x) >= 3 and len(y) >= 3):
        return None
    sx, sy = _stem(x), _stem(y)
    if (sx == sy or x in STOP or y in STOP or sx in relate.FILLER or sy in relate.FILLER
            or sx in relate._NUMBER_STEMS or sy in relate._NUMBER_STEMS or sx in relate._DATE_WORDS
            or sy in relate._DATE_WORDS or relate.NEGATION.search(x) or relate.NEGATION.search(y)
            or relate.CONTRAST.search(x) or relate.CONTRAST.search(y) or _opposed(x, y)):
        return None
    return x, y


def _key(x: str, y: str) -> tuple[str, str]:
    sx, sy = _stem(x), _stem(y)
    return (sx, sy) if sx <= sy else (sy, sx)


def pair_key(x: str, y: str) -> str:
    return " ".join(_key(x, y))


# -- sightings (pure) ------------------------------------------------------------------------------------------------

def scan(by_canon: dict[int, list[dict]], conflicts: dict[int, list[int]], groups: dict[int, str]) -> dict:
    """What the merged statements show, as {"seen": [(pair key, word a, word b, claim a, claim b)], "against":
    {pair keys}}. `by_canon`: merged statement id -> its claims (id, article_id, story_id, text, time); `conflicts`:
    statement id -> ids judged contradictory; `groups`: article id -> independence group (within this read)."""
    seen, against = [], set()
    for cid, cl in by_canon.items():
        cl = cl[:MAX_CLAIMS]
        for i, a in enumerate(cl):
            for b in cl[i + 1:]:
                if groups.get(a["article_id"], f"a{a['article_id']}") == groups.get(b["article_id"], f"a{b['article_id']}"):
                    continue
                s = swap(a["text"], b["text"])
                if not s:
                    continue
                # only a pair the model had to confirm is evidence: code alone already merged the others
                if relate.relate(a["text"], b["text"], a.get("time"), b.get("time")) == "same":
                    continue
                seen.append((pair_key(*s), s[0], s[1], dict(a, canonical_id=cid), dict(b, canonical_id=cid)))
    keys = {k for k, *_ in seen}
    # evidence against: the same swap between two statements the pipeline judged contradictory
    for cid, others in conflicts.items():
        for d in others or ():
            if d <= cid or cid not in by_canon or d not in by_canon:
                continue
            for a in by_canon[cid][:MAX_CLAIMS]:
                for b in by_canon[d][:MAX_CLAIMS]:
                    s = swap(a["text"], b["text"])
                    if s:
                        against.add(pair_key(*s))
    # evidence against: both words in one statement ("injured and killed")
    wanted = {st for k in keys for st in k.split()}
    if wanted:
        for cl in by_canon.values():
            for c in cl:
                stems = {_stem(t.lower()) for t in _tokens(c["text"])} & wanted
                if len(stems) >= 2:
                    for k in keys:
                        a, b = k.split()
                        if a in stems and b in stems:
                            against.add(k)
    return {"seen": seen, "against": against}


def record(cands: dict, found: dict, info: dict[int, dict], words_by_article: dict[int, set[str]] | None = None) -> int:
    """Add what the merged statements showed to the pairs' memory. `info`: article id -> {source, story, when};
    `words_by_article`: article id -> the stems its statements use (one source using both words in one article)."""
    words_by_article = words_by_article or {}
    n = 0
    for key, x, y, a, b in found["seen"]:
        c = cands.get(key)
        if c is None:
            c = cands[key] = L.Candidate(KIND, key)
        new = False
        for cl, w in ((a, x), (b, y)):
            i = info.get(cl["article_id"]) or {}
            if c.add(cl["article_id"], i.get("source"), i.get("story", cl.get("story_id")), L.day_of(i.get("when")),
                     i.get("when"), example=""):
                new = True
                by = dict(c.facets.get("by_source") or {})
                by[i["source"]] = sorted(set(by.get(i["source"], [])) | {_stem(w)})
                c.facets["by_source"] = by
                if set(key.split()) <= words_by_article.get(cl["article_id"], set()):
                    c.put("both_in_one_article", i["source"])
        if new:
            n += 1
            c.put("statements", a["canonical_id"])
            for w in (x, y):
                words = dict(c.facets.get("words") or {})
                words[w] = words.get(w, 0) + 1
                c.facets["words"] = words
            if not c.facets.get("sample"):
                c.facets["sample"] = [a["text"][:200], b["text"][:200]]
    for key in found["against"]:
        c = cands.get(key)
        if c is not None and not c.facets.get("against"):
            c.facets["against"] = True                     # remembered for good
            c.dirty = True
    return n


# -- the bar and the devil's advocate (pure) ----------------------------------------------------------------------

def extra_rules(c: L.Candidate) -> list[str]:
    return ["statements"] if len(c.facets.get("statements") or []) < MIN_STATEMENTS else []


def _qualifier_words() -> set[str]:
    from . import fidelity
    out = set()
    for q in fidelity.glossary()["qualifiers"]:
        for p in q.en:
            out.update(_stem(w) for w in p.lower().split())
    return out


def advocate(c: L.Candidate, loaded: set[str] = frozenset(), never=None, struck=None) -> L.Verdict:
    """Code's case against a pair (hold or block, never approve): the protesters / rioters kind of pair carries two
    judgments, and merging them would silently pick one."""
    stems = frozenset(c.key.split())
    never = relate.load_never() if never is None else never
    struck = rejected() if struck is None else struck
    if any(stems <= n for n in never) or any(stems <= r for r in struck):
        return L.Verdict("block", "on the never list or refused by the owner")
    if c.facets.get("against"):
        return L.Verdict("block", "evidence against: both words in one statement, or the swap between contradicting statements")
    if stems & _qualifier_words():
        return L.Verdict("block", "a word that limits a claim (fidelity glossary): never interchangeable")
    if stems & {_stem(w) for w in loaded}:
        return L.Verdict("block", "a reading tagged one of the words as loaded")
    if not any(len(v) >= 2 for v in (c.facets.get("by_source") or {}).values()) and not c.facets.get("both_in_one_article"):
        return L.Verdict("hold", "no outlet uses both words yet: each sticking to its own word may be a framing split")
    return L.CLEAR


MODEL_QUESTION = ("Each numbered line gives two words and two sentences from news reports that differ only in those "
                  "words. Does swapping one word for the other keep the meaning (SAME), or change the stance, "
                  "degree, certainty or judgment of the sentence (CHANGES)?")


def model_look(router, cands: list[L.Candidate]) -> dict[str, L.Verdict]:
    items = []
    for c in cands:
        words = sorted((c.facets.get("words") or {}), key=lambda w: -(c.facets["words"][w]))[:2]
        sample = " / ".join(c.facets.get("sample") or [])
        items.append(f'"{words[0] if words else c.key}" and "{words[1] if len(words) > 1 else ""}": {sample}')
    answers = L.ask_twice(router, MODEL_QUESTION, items, ("same", "changes", "unsure"), max_tokens=60 + 20 * len(items))
    out = {}
    for c, a in zip(cands, answers):
        out[c.key] = (L.CLEAR if a == "same" else
                      L.Verdict("block", "the model's look: swapping changes the meaning") if a == "changes" else
                      L.Verdict("hold", "the model's look gave no agreed answer"))
    return out


def decide(cands: dict, loaded=frozenset(), router=None, model_allowed: bool = True, now=None, never=None,
           struck=None, learned_stems=None) -> tuple[list, list, bool]:
    """Statuses: (newly learned, learned pairs the advocate now blocks, whether the model was asked)."""
    now = now or dt.datetime.utcnow()
    learned_stems = learned_stems if learned_stems is not None else set()
    fresh, withdrawn, waiting = [], [], []

    def mark(c, **kw):
        for k, v in kw.items():
            setattr(c, k, v)
        c.checked_at, c.dirty = now, True

    for c in cands.values():
        v = advocate(c, loaded, never, struck)
        if c.status == "learned":
            if v.state == "block":
                mark(c, status="blocked", verdict="block", reason=v.reason)
                withdrawn.append(c)
            continue
        if c.status == "blocked":
            continue
        if v.state == "block":
            mark(c, status="blocked", verdict="block", reason=v.reason)
            continue
        if BAR.fails(c) or extra_rules(c):
            continue
        if any(s in relate.SYNONYM for s in c.key.split()) or set(c.key.split()) & learned_stems:
            if c.reason != "a word already in a group":
                mark(c, verdict="hold", reason="a word already in a group")
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
        taken: set[str] = set()
        for c in waiting:
            v = looks.get(c.key, L.Verdict("hold", "not looked at"))
            if v.state == "clear" and not set(c.key.split()) & taken and len(fresh) < MAX_NEW:
                mark(c, status="learned", verdict="clear", reason="the model's look: same meaning")
                fresh.append(c)
                taken |= set(c.key.split())
            elif v.state == "block":
                mark(c, status="blocked", verdict="block", reason=v.reason)
            elif v.state == "hold":
                mark(c, verdict="hold", reason=v.reason)
    else:
        for c in waiting:
            if c.reason != WAITING:
                mark(c, verdict="hold", reason=WAITING)
    return fresh, withdrawn, used


# -- the learned file --------------------------------------------------------------------------------------------

def _stem_sets(lines: list[str]) -> list[frozenset[str]]:
    return [frozenset(_stem(w) for w in str(x).lower().split()) for x in lines if isinstance(x, str) and len(str(x).split()) >= 2]


def rejected() -> list[frozenset[str]]:
    """The pairs the owner has struck out (each line: the stems of its words), from the learned file."""
    try:
        from .config import load_yaml
        return _stem_sets(load_yaml(FILE).get("rejected") or [])
    except Exception:  # noqa: BLE001 (no file, or one that does not parse: nothing is rejected, nothing breaks)
        return []


def entry(c: L.Candidate, today: dt.date) -> dict:
    words = sorted((c.facets.get("words") or {}), key=lambda w: -(c.facets["words"][w]))[:2]
    return {"words": " ".join(sorted(words)), "learned": today.isoformat(), "statements": len(c.facets.get("statements") or []),
            "stories": len(c.stories), "sources": len(c.sources), "days": len(c.days)}


def line(entry: dict) -> str:
    """One entry as one flow-style YAML line (JSON strings are valid YAML strings), appended to the file."""
    return "  - {" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in entry.items()) + "}\n"


def learned_stems(path: Path) -> set[str]:
    import yaml
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return set()
    have = set()
    for g in doc.get("groups") or []:
        if isinstance(g, dict) and isinstance(g.get("words"), str):
            have.update(_stem(w) for w in g["words"].lower().split())
    return have


def append(entries: list[dict], path: Path) -> int:
    """Add the entries whose words are not in the file yet (a word is in one group only), at its end. The file is
    created with its header when missing; a file that does not parse is left alone. Returns how many lines were
    added."""
    import yaml
    if not path.exists():
        path.write_text(HEADER, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    try:
        yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        log.warning("%s does not parse; nothing appended", path)
        return 0
    have = learned_stems(path)
    new = []
    for e in entries:
        stems = {_stem(w) for w in e["words"].split()}
        if not stems & have:
            new.append(e)
            have |= stems
    if new:
        path.write_text(text + ("" if text.endswith("\n") else "\n") + "".join(line(e) for e in new), encoding="utf-8")
    return len(new)


def withdraw(keys: list[str], path: Path) -> int:
    """Take learned pairs the devil's advocate now blocks out of the file (their lines only)."""
    if not keys or not path.exists():
        return 0
    want = [frozenset(k.split()) for k in keys]
    out, n = [], 0
    for ln in path.read_text(encoding="utf-8").splitlines(keepends=True):
        m = re.search(r'words: "([^"]+)"', ln)
        if m and frozenset(_stem(w) for w in m.group(1).lower().split()) in want:
            n += 1
            continue
        out.append(ln)
    if n:
        path.write_text("".join(out), encoding="utf-8")
    return n


# -- the run -------------------------------------------------------------------------------------------------------

def run(store, router=None, days: float = 3, dry_run: bool = False, path: Path | None = None) -> dict:
    """Read the newsroom's recent merged statements and the wordings under them, add to the memory, decide."""
    from . import names as N, wire
    from .config import CONFIG_DIR
    from .db import articles, canonical, claims, select
    path = path or (CONFIG_DIR / FILE)
    now = dt.datetime.utcnow()
    since = now - dt.timedelta(days=days)
    arts = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.wire_group,
                             articles.c.story_id, articles.c.published_at).where(articles.c.published_at >= since))
    ids = [a["id"] for a in arts]
    by_canon: dict[int, list[dict]] = defaultdict(list)
    words_by_article: dict[int, set[str]] = defaultdict(set)
    loaded_tags: list[str] = []
    for start in range(0, len(ids), 400):
        for c in store.rows(select(claims.c.id, claims.c.story_id, claims.c.article_id, claims.c.canonical_id,
                                   claims.c.kind, claims.c.text, claims.c.time, claims.c.loaded_words)
                            .where(claims.c.article_id.in_(ids[start:start + 400]))):
            for w in c.get("loaded_words") or []:
                loaded_tags.extend(x.lower() for x in str(w).split())
            if c.get("kind") in ("event", "claim") and c.get("text"):
                words_by_article[c["article_id"]] |= {_stem(t.lower()) for t in _tokens(c["text"])}
                if c.get("canonical_id") is not None:
                    by_canon[c["canonical_id"]].append(c)
    conflicts: dict[int, list[int]] = {}
    cids = list(by_canon)
    for start in range(0, len(cids), 400):
        for r in store.rows(select(canonical.c.id, canonical.c.conflicts).where(canonical.c.id.in_(cids[start:start + 400]))):
            conflicts[r["id"]] = list(r.get("conflicts") or [])
    found = scan(by_canon, conflicts, wire.independence_groups(arts))
    info = {a["id"]: {"source": N.source_key(a), "story": a.get("story_id"), "when": a.get("published_at")} for a in arts}
    cands = L.load(store, KIND)
    new = record(cands, found, info, words_by_article)
    loaded = L.loaded_set(loaded_tags)
    fresh, withdrawn, used = decide(cands, loaded, router, L.model_due(store, KIND, now), now,
                                    learned_stems=learned_stems(path) if path.exists() else set())
    out = {"articles": len(arts), "statements": len(by_canon), "new_evidence": new, "candidates": len(cands),
           "funnel": L.funnel(cands.values(), BAR, extra_rules), "near": L.near(cands.values(), BAR, extra_rules), "learned_now": [c.key for c in fresh],
           "withdrawn": [c.key for c in withdrawn], "model_asked": used}
    if dry_run:
        return out
    if used:
        L.model_used(store, KIND, now)
    out["added"] = append([entry(c, now.date()) for c in fresh], path)
    out["removed"] = withdraw([c.key for c in withdrawn], path)
    out.update(L.save(store, cands, now))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", default=None)
    p.add_argument("--days", type=float, default=3)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .config import database_url
    from .db import Store
    store = Store(database_url())
    store.init()
    res = run(store, L.router_for(store), a.days, a.dry_run, Path(a.file) if a.file else None)
    log.info("synonym candidates: %s", res.get("funnel"))
    print(json.dumps(res, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

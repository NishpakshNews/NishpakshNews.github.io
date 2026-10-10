"""Synonyms learned from the outlets (owner, Oct 11 2026: "like the project learns and grows the titles' list on its
own, can synonyms grow too, on its own"). The twin of learn.py (titles).

config/synonyms.yaml is written by hand and cannot hold every pair of words the outlets use for one thing. When two
outlets say one fact in different words and the words alone do not tell the pipeline they are one fact, the model is
asked twice (match.same_facts, A/B swapped) and, on two "same", the two statements are merged under one
`canonical_id`. That merge is the evidence: the database already holds, for each merged statement, the different
wordings the outlets used. This module reads them and, when the wordings differ by exactly ONE word, counts the pair
of words. A pair is APPENDED to config/synonyms_learned.yaml (the job commits it: .github/scripts/learn_synonyms.sh)
and relate.py reads it after the hand-written file, so from the next run the same two lines are one by code, with no
model call. No model is used here: a model alone is never the source of an entry.

A pair of words is learned only when ALL of this holds:

  - two claims under one merged statement are the same words except one word in the same place, with at least 3
    other words around it, the same numbers, the same names, and both swapped words in lower case (a name or a
    number is never a synonym),
  - code alone did NOT already call the two lines "same" (relate.relate): only a pair the model had to confirm is
    evidence; a long line that code merged with one word different (\"injured\" / \"killed\") proves nothing,
  - the two claims come from different independence groups of outlets (wire copies, one owner, state media are one),
  - the pair shows in 3+ different statements, in 2+ different stories, and in 2+ independent groups of outlets,
  - and there is no evidence against it: the two words never stand in one statement (\"injured and killed\"), never
    differ between two statements the pipeline judged to CONTRADICT each other (canonical.conflicts), are not
    opposites by prefix (\"able\" / \"unable\"), are not on a `never:` line of synonyms.yaml, and are not struck out
    in `rejected:` of the learned file.

Neither word may already be in a group (the hand-written groups win and a learned group never grows by itself:
a word stays in the first group it appears in). At most MAX_NEW pairs are added in a run, so a bug cannot flood the
file. An entry carries the day it was learned, how many statements and stories showed it, and one example pair of
sentences, so the owner can judge it at a glance. Entries are only ever appended. A WRONG ENTRY: delete its line
and add its two words as one line to `rejected:` at the top of the file: it is never learned again.

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

from . import relate
from .frames import STOP, _stem

log = logging.getLogger(__name__)

FILE = "synonyms_learned.yaml"
MIN_STATEMENTS = 3      # different merged statements that showed the pair
MIN_STORIES = 2         # different stories
MIN_GROUPS = 2          # independent groups of outlets
MIN_CONTEXT = 3         # words the two lines share around the swapped word
MAX_CLAIMS = 12         # claims of one statement compared with each other (a bug cannot make this explode)
MAX_NEW = 5             # most pairs one run adds

HEADER = """# Synonyms learned from the news by nishpaksh/learn_synonyms.py (owner, Oct 11 2026). The job appends here and
# commits it; nishpaksh/relate.py reads it after the hand-written synonyms.yaml, which always wins.
# A pair enters this file only when two outlets said one fact (merged by the model, asked twice) in the same words
# but for ONE word, in 3+ statements of 2+ stories and 2+ independent outlets, and nothing showed the two words to
# differ. `statements` and `stories` say how often, `example` shows one pair of sentences, `learned` the day.
# Entries are only appended.
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


def scan(by_canon: dict[int, list[dict]], conflicts: dict[int, list[int]], groups: dict[int, str]
         ) -> dict[tuple[str, str], dict]:
    """Evidence per pair of stems: {statements, stories, groups, words, example, veto}. `by_canon`: merged statement
    id -> its claims (id, article_id, story_id, text, time); `conflicts`: statement id -> ids judged contradictory;
    `groups`: article id -> independence group."""
    ev: dict[tuple[str, str], dict] = defaultdict(lambda: {"statements": set(), "stories": set(), "groups": set(),
                                                           "words": defaultdict(Counter), "example": None,
                                                           "veto": False})
    for cid, cl in by_canon.items():
        cl = cl[:MAX_CLAIMS]
        for i, a in enumerate(cl):
            for b in cl[i + 1:]:
                ga = groups.get(a["article_id"], f"a{a['article_id']}")
                gb = groups.get(b["article_id"], f"a{b['article_id']}")
                if ga == gb:
                    continue
                s = swap(a["text"], b["text"])
                if not s:
                    continue
                # only a pair the model had to confirm is evidence: code alone already merged the others
                if relate.relate(a["text"], b["text"], a.get("time"), b.get("time")) == "same":
                    continue
                e = ev[_key(*s)]
                e["statements"].add(cid)
                e["stories"].add(a.get("story_id"))
                e["groups"].update((ga, gb))
                for w in s:
                    e["words"][_stem(w)][w] += 1
                if e["example"] is None:
                    e["example"] = (a["text"], b["text"])
    # evidence against: the same swap between two statements the pipeline judged contradictory
    for cid, others in conflicts.items():
        for d in others or ():
            if d <= cid or cid not in by_canon or d not in by_canon:
                continue
            for a in by_canon[cid][:MAX_CLAIMS]:
                for b in by_canon[d][:MAX_CLAIMS]:
                    s = swap(a["text"], b["text"])
                    if s and _key(*s) in ev:
                        ev[_key(*s)]["veto"] = True
    # evidence against: both words in one statement (\"injured and killed\")
    wanted = {st for k in ev for st in k}
    if wanted:
        for cl in by_canon.values():
            for c in cl:
                stems = {_stem(t.lower()) for t in _tokens(c["text"])} & wanted
                if len(stems) >= 2:
                    for k, e in ev.items():
                        if k[0] in stems and k[1] in stems:
                            e["veto"] = True
    return dict(ev)


def _stem_sets(lines: list[str]) -> list[frozenset[str]]:
    return [frozenset(_stem(w) for w in str(x).lower().split()) for x in lines if isinstance(x, str) and len(str(x).split()) >= 2]


def rejected() -> list[frozenset[str]]:
    """The pairs the owner has struck out (each line: the stems of its words), from the learned file."""
    try:
        from .config import load_yaml
        return _stem_sets(load_yaml(FILE).get("rejected") or [])
    except Exception:  # noqa: BLE001 (no file, or one that does not parse: nothing is rejected, nothing breaks)
        return []


def pick(ev: dict[tuple[str, str], dict], today: dt.date | None = None,
         never: list[frozenset[str]] | None = None, struck: list[frozenset[str]] | None = None) -> list[dict]:
    """The pairs with enough evidence and none against, as entries for the file (most evidence first, at most
    MAX_NEW, no word twice in one run)."""
    today = today or dt.date.today()
    never = relate.load_never() if never is None else never
    struck = rejected() if struck is None else struck
    out, used = [], set()
    for key, e in sorted(ev.items(), key=lambda kv: (-len(kv[1]["statements"]), -len(kv[1]["stories"]), kv[0])):
        if (e["veto"] or len(e["statements"]) < MIN_STATEMENTS or len(e["stories"]) < MIN_STORIES
                or len(e["groups"]) < MIN_GROUPS):
            continue
        if any(s in relate.SYNONYM for s in key) or used & set(key):   # a word stays in the group it is in
            continue
        pair = frozenset(key)
        if any(pair <= n for n in never) or any(pair <= r for r in struck):
            continue
        words = sorted(e["words"][s].most_common(1)[0][0] for s in key)
        ex = e["example"] or ("", "")
        out.append({"words": " ".join(words), "learned": today.isoformat(), "statements": len(e["statements"]),
                    "stories": len(e["stories"]), "example": [ex[0][:110], ex[1][:110]]})
        used.update(key)
    return out[:MAX_NEW]


def line(entry: dict) -> str:
    """One entry as one flow-style YAML line (JSON strings are valid YAML strings), appended to the file."""
    return "  - {" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in entry.items()) + "}\n"


def append(entries: list[dict], path: Path) -> int:
    """Add the entries whose words are not in the file yet (a word is in one group only), at its end. The file is
    created with its header when missing; a file that does not parse is left alone. Returns how many lines were
    added."""
    import yaml
    if not path.exists():
        path.write_text(HEADER, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001
        log.warning("%s does not parse; nothing appended", path)
        return 0
    have = set()
    for g in doc.get("groups") or []:
        if isinstance(g, dict) and isinstance(g.get("words"), str):
            have.update(_stem(w) for w in g["words"].lower().split())
    new = []
    for e in entries:
        stems = {_stem(w) for w in e["words"].split()}
        if not stems & have:
            new.append(e)
            have |= stems
    if new:
        path.write_text(text + ("" if text.endswith("\n") else "\n") + "".join(line(e) for e in new), encoding="utf-8")
    return len(new)


def run(store, path: Path | None = None, days: float = 3, dry_run: bool = False) -> dict:
    """Read the newsroom's recent merged statements and the wordings under them, append what has the evidence."""
    from . import wire
    from .config import CONFIG_DIR
    from .db import articles, canonical, claims, select
    path = path or (CONFIG_DIR / FILE)
    since = dt.datetime.utcnow() - dt.timedelta(days=days)
    arts = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency, articles.c.wire_group)
                      .where(articles.c.published_at >= since))
    ids = [a["id"] for a in arts]
    by_canon: dict[int, list[dict]] = defaultdict(list)
    for start in range(0, len(ids), 400):
        for c in store.rows(select(claims.c.id, claims.c.story_id, claims.c.article_id, claims.c.canonical_id,
                                   claims.c.kind, claims.c.text, claims.c.time)
                            .where(claims.c.article_id.in_(ids[start:start + 400]))):
            if c.get("canonical_id") is not None and c.get("kind") in ("event", "claim") and c.get("text"):
                by_canon[c["canonical_id"]].append(c)
    conflicts: dict[int, list[int]] = {}
    cids = list(by_canon)
    for start in range(0, len(cids), 400):
        for r in store.rows(select(canonical.c.id, canonical.c.conflicts).where(canonical.c.id.in_(cids[start:start + 400]))):
            conflicts[r["id"]] = list(r.get("conflicts") or [])
    ev = scan(by_canon, conflicts, wire.independence_groups(arts))
    found = pick(ev)
    added = 0 if dry_run else append(found, path)
    return {"articles": len(arts), "statements": len(by_canon), "candidates": len(ev), "qualified": len(found),
            "added": added, "pairs": [e["words"] for e in found]}


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
    res = run(store, Path(a.file) if a.file else None, a.days, a.dry_run)
    log.info("learned synonyms: %s", res)
    print(json.dumps(res))


if __name__ == "__main__":
    main()

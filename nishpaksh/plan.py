"""Grammar of the article's structure (owner, Oct 10 2026, phase 3 of "grammar, not rules").

Until now the writer received every statement sorted into sections and decided the paragraphs itself: which
statements share a paragraph, in what order, how a paragraph begins. It is a small model and it got that wrong
often (a paragraph per statement, one block of fourteen, a speaker's argument scattered, a new paragraph opening
with "He added"). Code then regrouped what it could. This module moves the decision to code:

  build     the PLAN: article > sections > paragraphs. Each section has its own rule (RULES: how its statements
            are ordered, what makes two of them one paragraph, how a paragraph opens). A paragraph is a list of
            statement ids, a speaker for "What they say", and a link to the one before it. No model in it.
  block     the plan as the writer sees it: PARAGRAPH n under each SECTION, with how it opens. The writer's
            task is to phrase each paragraph, not to design the article.
  conform   after writing: every sentence goes back to the paragraph its statements were planned in, in plan
            order, whatever paragraphs the writer made. A sentence that leans on the one before it ("He added
            ...") moves with it, so a paragraph never opens with it. Sentences are never changed.

"Flow" is not a rule here: it comes from a sound plan (one subject per paragraph, a fixed order, each paragraph
opening the way its section needs). Everything is a function of the statements.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass, field


MAX_STATEMENTS = 4      # statements in one paragraph (about 2-5 sentences once written)
MIN_STATEMENTS = 2      # a paragraph changes subject only after this many statements


@dataclass(frozen=True)
class Rule:
    """What a section's paragraphs are."""
    order: str          # "time": by when it happened; "given": the order the statements come in; "speaker": by speaker
    group: str          # "subject": shared names and key words; "event": the related event's own label; "none"
    opens: str          # "when": its time, when the time changes; "term": the thing explained; "speaker"; ""
    says: str           # one line for the writer: what this section's paragraph is


RULES: dict[str, Rule] = {
    "news": Rule("given", "none", "", "the lead: what makes this a story today, with who, where and when"),
    "background": Rule("time", "subject", "when", "the past of the story's own subject, oldest first: its history, then the "
                                                   "steps just before the news; each paragraph one subject, with its own time"),
    "explained": Rule("given", "subject", "term", "what a term, rule, post or finding means"),
    "happened": Rule("time", "subject", "when", "what happened, in time order"),
    "numbers": Rule("given", "subject", "", "figures: each with what it measures"),
    "say": Rule("speaker", "subject", "speaker", "one speaker's argument, the main point first"),
    "related": Rule("time", "event", "when", "one related event, with its own time and people"),
    "next": Rule("time", "subject", "when", "what happens next: hearings, deadlines, required steps"),
    # the express desk's layouts (expressdesk.py)
    "performers": Rule("given", "subject", "", "one standout player or team, with their figures"),
    "who": Rule("given", "subject", "", "who the person is: role, age, where from, what they are known for"),
    "journey": Rule("time", "subject", "when", "their path so far, oldest first, each step with its time"),
    "words": Rule("speaker", "subject", "speaker", "a person's own words, quoted, with what they are about"),
    "drivers": Rule("given", "subject", "", "what explains the figures, one subject per paragraph"),
    "market": Rule("time", "subject", "", "how the share price and investors reacted"),
}


@dataclass
class Para:
    n: int                              # 1-based, in page order
    section: str
    ids: list[int]
    speaker: str | None = None          # "What they say": whose argument it is
    link: str = "new"                   # new | continues (same speaker, next paragraph) | answers (to an earlier one)
    opens: str = ""                     # how it begins, for the writer
    answers: list[int] = field(default_factory=list)


# ------------------------------------------------------------------ helpers (narrative is imported late: it imports us)
def _start(i: dict):
    start = (i.get("time") or {}).get("start")
    try:
        return dt.datetime.fromisoformat(start) if start else dt.datetime.max
    except (ValueError, TypeError):
        return dt.datetime.max


def _links(i: dict) -> set[int]:
    """The statements that must be written WITH this one: its contradiction, its response, the figure it updates."""
    from . import narrative
    out = set(narrative._partners(i))
    for k in ("update_of", "updated_by", "adds_to"):
        v = i.get(k)
        if isinstance(v, int) and v >= 0:
            out.add(v)
    return out


def _units(ordered: list[dict]) -> list[list[dict]]:
    """Statements joined with the ones they must be written with, each unit at its first member's place."""
    pos = {i["id"]: n for n, i in enumerate(ordered)}
    parent = {i["id"]: i["id"] for i in ordered}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i in ordered:
        for x in _links(i):
            if x in parent:
                parent[find(x)] = find(i["id"])
    units: dict[int, list[dict]] = {}
    for i in ordered:
        units.setdefault(find(i["id"]), []).append(i)
    return sorted(units.values(), key=lambda u: pos[u[0]["id"]])


_W = None   # idf.Weights of the statements being planned (set by build); None = every word weighs 1


def _related(a: set, b: set) -> bool:
    """Do two statements share a subject? Shared weight counts: a name or rare word is worth 1, a word nearly every
    statement of the story has (learned from the statements, idf.py) close to nothing."""
    if _W is None:
        return bool(a & b)
    return _W.related(a, b)


def _lean(u: list[dict]) -> bool:
    from . import narrative
    return bool(narrative.PRONOUN_START.match((u[0].get("text") or "").strip()))


def _cluster(units: list[list[dict]], words) -> list[list[dict]]:
    """Units about the same thing side by side (owner, Oct 13 2026: a paragraph read \"transferred the complaints to
    the Crime Branch. Then the Supreme Court issued a notice on the Election Commission. Delhi Police denied
    permission for the protest.\": time order put three unrelated facts in one paragraph). A unit that leans on the
    one before it (\"He added ...\") stays with it. The rest are grouped by subject: the first unit, then the earliest
    one that shares its subject, and so on; when none does, the earliest left starts a new group."""
    glued: list[list[dict]] = []
    for u in units:
        if glued and _lean(u):
            glued[-1] = glued[-1] + u
        else:
            glued.append(list(u))
    coded = _theme_order(glued)
    if coded is not None:
        return coded
    left = list(glued)
    out: list[list[dict]] = []
    while left:
        cur = left.pop(0)
        out.append(cur)
        grp_words = set().union(*(words(i) for i in cur))
        while True:
            nxt = next((u for u in left if _related(grp_words, set().union(*(words(i) for i in u)))), None)
            if nxt is None:
                break
            left.remove(nxt)
            out.append(nxt)
            grp_words = set().union(*(words(i) for i in nxt))       # the next one must fit the one before it
    return out


def _theme_order(units: list[list[dict]]) -> list[list[dict]] | None:
    """S28: themes by CONSTRAINED CLUSTERING in code. The units are the must-link atoms (a statement with its contradiction,
    response or updated figure is one unit already); agglomerative clustering (average linkage) on sentence-embedding
    distance groups the units into themes; two units naming different people (both name someone, no name in common) are
    cannot-link (their distance is set beyond any threshold). Themes come in the order of their earliest unit, units inside
    a theme in their own order. None (no clustering possible) = the older word-overlap grouping."""
    if len(units) < 3:
        return None
    try:
        import numpy as np
        from sklearn.cluster import AgglomerativeClustering
        from . import embed
        from .relate import Profile
        texts = [" ".join(i.get("text") or "" for i in u) for u in units]
        v, how = embed.vectors(texts)
        dist = 1.0 - np.clip(v @ v.T, -1.0, 1.0)
        names = [set().union(*(Profile(i.get("text") or "").names for i in u)) for u in units]
        for a in range(len(units)):
            for b in range(a + 1, len(units)):
                if names[a] and names[b] and not names[a] & names[b]:
                    dist[a, b] = dist[b, a] = 2.0
        np.fill_diagonal(dist, 0.0)
        cut = 1.0 - embed.PROPOSE[how]
        labels = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                         distance_threshold=cut).fit_predict(dist)
    except Exception:  # noqa: BLE001
        return None
    first: dict[int, int] = {}
    for k, lab in enumerate(labels):
        first.setdefault(int(lab), k)
    out: list[list[dict]] = []
    for lab in sorted(first, key=lambda x: first[x]):
        out += [units[k] for k, l_ in enumerate(labels) if int(l_) == lab]
    return out


def _pack(units: list[list[dict]], words, strict: bool = True, topical: bool = False) -> list[list[dict]]:
    """Units into paragraphs: closed at MAX_STATEMENTS, or when the next unit is not about what the paragraph is
    about. `strict` (every section but one speaker's own argument): units are first grouped by subject, a unit
    joins a paragraph only if it shares a subject with the unit before it, and a lone statement stays alone rather
    than join a paragraph it has nothing to do with. Not strict (a speaker's argument): the earlier rule, a
    paragraph changes subject after MIN_STATEMENTS statements. `topical`: the units are already ONE topic (the
    grouping call, belong.assign_topics), so a paragraph closes only at MAX_STATEMENTS."""
    if topical:
        paras_t: list[list[dict]] = []
        cur_t: list[dict] = []
        for u in units:
            if cur_t and len(cur_t) + len(u) > MAX_STATEMENTS:
                paras_t.append(cur_t)
                cur_t = []
            cur_t += u
        if cur_t:
            paras_t.append(cur_t)
        return paras_t
    if strict:
        units = _cluster(units, words)
    paras: list[list[dict]] = []
    cur: list[dict] = []
    cur_words: set = set()
    last_words: set = set()
    for u in units:
        w = set().union(*(words(i) for i in u))
        if strict:
            split = bool(cur) and (len(cur) + len(u) > MAX_STATEMENTS or not _related(last_words, w))
        else:
            split = bool(cur) and (len(cur) + len(u) > MAX_STATEMENTS
                                   or (len(cur) >= MIN_STATEMENTS and not (w & cur_words)))
        if split:
            paras.append(cur)
            cur, cur_words = [], set()
        cur += u
        cur_words |= w
        last_words = w
    if cur:
        paras.append(cur)
    if (not strict and len(paras) > 1 and len(paras[-1]) == 1 and len(paras[-2]) < MAX_STATEMENTS):
        tail = paras.pop()
        paras[-1] += tail
    return paras


def _words_fn():
    from . import narrative
    cache: dict[int, set] = {}

    def words(i: dict) -> set:
        k = i["id"]
        if k not in cache:
            cache[k] = narrative._subject_words(i["text"])
        return cache[k]
    return words


# ------------------------------------------------------------------ the plan
def build(items: list[dict], sec: dict[int, str]) -> list[Para]:
    """The paragraph plan for these statements (`sec`: statement id -> section, from narrative.assign_sections),
    in page order."""
    global _W
    from . import idf, narrative, order
    words = _words_fn()
    _W = idf.Weights([set(words(i)) for i in items])
    plan: list[Para] = []
    for key in narrative._keys():
        mine = [i for i in items if sec.get(i["id"]) == key]
        if not mine:
            continue
        rule = RULES[key]
        made: list[Para] = []
        if key == "news":
            made = [Para(0, key, [i["id"] for i in mine])]
        elif rule.order == "speaker":
            made = _say(mine, words, key)
        else:
            ordered = order.chronological(mine) if rule.order == "time" else list(mine)
            if rule.group == "event":
                labels: dict = {}
                for i in ordered:
                    labels.setdefault(i.get("related_event") or None, []).append(i)
                chunks = [c for c in labels.values()]
            elif key == "background":
                # the subject's history first, then the steps just before the news (belong.place sets `slot`);
                # a paragraph never mixes the two, and both are oldest first
                chunks = [[i for i in ordered if (i.get("slot") or "history") == s_] for s_ in ("history", "leadup")]
                chunks = [c for c in chunks if c]
            else:
                chunks = [ordered]
            # an express layout's sections are already one subject each (a match's performers, a person's journey):
            # paragraphs are filled up to MAX_STATEMENTS instead of cut at every change of words (Oct 16 2026: the
            # first express pages had a paragraph per sentence)
            express_layout = narrative._keys() is not narrative.SECTION_KEYS
            for chunk in chunks:
                for part, topical in _by_topic(chunk):
                    for group in _pack(_units(part), words, topical=topical or express_layout):
                        made.append(Para(0, key, [i["id"] for i in group]))
        _open(made, key, {i["id"]: i for i in mine})
        plan += made
    for n, p in enumerate(plan, 1):
        p.n = n
    return plan


def _by_topic(chunk: list[dict]) -> list[tuple[list[dict], bool]]:
    """A chunk split by topic (belong.assign_topics): one subject per paragraph, whatever the time order says.
    [(statements, topical)]; without topics (the grouping call failed) the chunk stays whole and is grouped by
    shared words as before. Topics come in the order their earliest statement comes in the chunk."""
    if not any(i.get("topic") is not None for i in chunk):
        return [(chunk, False)]
    parts: dict = {}
    for i in chunk:
        parts.setdefault(i.get("topic") if i.get("topic") is not None else ("alone", i["id"]), []).append(i)
    return [(p_, True) for p_ in parts.values()]


def _say(items: list[dict], words, key: str = "say") -> list[Para]:
    """"What they say": one speaker's statements together, speakers in order of first appearance, an answer right
    after what it answers (narrative._by_speaker); a long argument is cut into paragraphs by subject."""
    from . import narrative
    out: list[Para] = []
    seen: set[int] = set()              # statements already placed: an answer follows what it answers
    pending: list[dict] = []            # statements with no named speaker, packed together

    def flush():
        nonlocal pending
        for group in _pack(_units(pending), words):
            out.append(Para(0, key, [i["id"] for i in group]))
            seen.update(i["id"] for i in group)
        pending = []
    for name, group in narrative._by_speaker(items):
        if not name:
            pending += group
            continue
        flush()
        for n, part in enumerate(_pack(_units(group), words, strict=False)):
            ids = [i["id"] for i in part]
            partners = set().union(*(narrative._partners(i) for i in part)) - set(ids)
            hit = sorted(partners & seen)
            out.append(Para(0, key, ids, speaker=name, link=("continues" if n else "answers" if hit else "new"),
                            answers=hit if not n else []))
            seen.update(ids)
    flush()
    return out


def _open(made: list[Para], key: str, by_id: dict[int, dict]) -> None:
    """How each paragraph begins (the paragraph grammar: links between consecutive paragraphs)."""
    from . import narrative
    rule = RULES[key]
    prev_when = ""
    for p in made:
        first, last = by_id[p.ids[0]], by_id[p.ids[-1]]
        if rule.opens == "when":
            w = narrative.english_when(first.get("time") or {})
            if w and w != prev_when:
                p.opens = f"its time ({w}): a reader must know when this happened"
            elif prev_when:
                p.opens = "no new time: it continues the paragraph before"
            prev_when = narrative.english_when(last.get("time") or {}) or prev_when
        elif rule.opens == "term":
            p.opens = "the thing being explained, then what it means"
        elif rule.opens == "speaker":
            who = (p.speaker or "").split(" = ")[0]
            if p.link == "continues":
                p.opens = "the same speaker as the paragraph before: do not introduce them again"
            elif p.link == "answers":
                p.opens = (f"the one who answers ({who}), saying what is answered (" +
                           ", ".join(f"#{x}" for x in p.answers) + ")")
            elif who:
                p.opens = f"its speaker, {who}"
            else:
                p.opens = "what is said; no speaker is named for it"


def block(plan: list[Para], by_id: dict[int, dict], line_of, link=None) -> str:
    """The plan as the writer reads it: SECTION, then PARAGRAPH n with how it opens, then its statements.
    `link(item, previous_item)` (sentences.link_line, phase 4) adds to each statement after the first how its
    sentence connects to the one before."""
    out: list[str] = []
    last = None
    for p in plan:
        if p.section != last:
            out.append("SECTION news (THE NEWS: the lead is written from it):" if p.section == "news"
                       else f"SECTION {p.section}: ({RULES[p.section].says})")
            last = p.section
        head = f"  PARAGRAPH {p.n}"
        if p.opens:
            head += f" (opens with {p.opens})"
        out.append(head + ":")
        prev = None
        for i in p.ids:
            if i not in by_id:
                continue
            line = f"    {line_of(by_id[i])}"
            how = link(by_id[i], prev) if link else None
            out.append(line + (f" | LINK: {how}" if how else ""))
            prev = by_id[i]
    return "\n".join(out)


def where(plan: list[Para]) -> dict[int, int]:
    """Statement id -> its paragraph's position in the plan."""
    return {i: n for n, p in enumerate(plan) for i in p.ids}


# ------------------------------------------------------------------ after writing
def _leans(text: str) -> bool:
    from . import narrative
    t = (text or "").strip()
    return bool(narrative.LEANS_BACK.search(t) or narrative.PRONOUN_START.match(t))


def conform(paragraphs: list, keys: list, plan: list[Para]) -> tuple[list, list, dict]:
    """The writer's sentences put back into the plan: each to the paragraph most of its statements were planned
    in (a tie: the section the writer wrote it in, then the earlier one), paragraphs in plan order. A sentence
    leaning on the one before ("He added ...") goes where that one went. A lead sentence citing a news statement
    stays the lead. Sentences are never changed. Returns (paragraphs, section keys, stats)."""
    at = where(plan)
    news = {n for n, p in enumerate(plan) if p.section == "news"}
    buckets: dict[int, list[list]] = {}     # plan paragraph -> chunks: a sentence and the ones leaning on it
    orphans: dict[str, list[list]] = {}
    moved = n_orphans = 0
    for para, key in zip(paragraphs, keys):
        prev = None                     # where the sentence before went: an int, or "o" (orphan)
        run: list = []                  # orphans of this writer paragraph, kept together
        for sent in para:
            votes = Counter(at[x] for x in sent["ids"] if x in at)
            target = None
            lean = False
            if key == "news" and (news & set(votes)):
                target = min(news & set(votes))
            elif key == "news" and not news:
                target = None           # no news was chosen for the plan: the writer's lead stays the lead
            elif prev is not None and _leans(sent["text"]) and (not votes or prev in votes):
                target = prev if prev != "o" else None
                lean = target is not None
            elif votes:
                best = max(votes.values())
                tied = sorted(n for n, c in votes.items() if c == best)
                target = next((n for n in tied if plan[n].section == key), tied[0])
            if target is None:
                run.append(sent)
                prev = "o"
                continue
            if run:
                orphans.setdefault(key, []).append(run)
                n_orphans += 1
                run = []
            if plan[target].section != key:
                moved += 1
            chunks = buckets.setdefault(target, [])
            if lean and chunks:
                chunks[-1].append(sent)
            else:
                chunks.append([sent])
            prev = target
        if run:
            orphans.setdefault(key, []).append(run)
            n_orphans += 1
    # inside a paragraph the statements' own order (time order, main claim first); a leaning sentence stays behind
    for n, chunks in buckets.items():
        pos = {i: k for k, i in enumerate(plan[n].ids)}
        chunks.sort(key=lambda c: min([pos[x] for x in c[0]["ids"] if x in pos] or [len(pos)]))
    buckets = {n: [x for c in chunks for x in c] for n, chunks in buckets.items()}
    out_p: list = []
    out_k: list = []
    for run in orphans.pop("news", []) if not news else []:
        out_p.append(run)
        out_k.append("news")
    last_of = {}
    for n, p in enumerate(plan):
        last_of[p.section] = n
    for n, p in enumerate(plan):
        if buckets.get(n):
            out_p.append(buckets[n])
            out_k.append(p.section)
        if last_of[p.section] == n:
            for run in orphans.pop(p.section, []):
                out_p.append(run)
                out_k.append(p.section)
    for key, runs in orphans.items():       # a section the plan does not have: where the writer put it, at the end
        for run in runs:
            out_p.append(run)
            out_k.append(key)
    stats = {"planned": len(plan), "written": len({n for n in buckets if buckets[n]}), "moved": moved,
             "orphans": n_orphans}
    return out_p, out_k, stats

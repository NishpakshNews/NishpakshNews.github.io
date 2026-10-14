"""Where does a context line belong? (owner, Oct 8 2026; rebuilt Oct 13 2026: place, never drop)

A news page carries other news too: a sidebar, a list of other videos, "also read" links. Reading picks
some of it up as context, and the old filter let it in: "a fact about a person, place or body in the story"
was "connected", and anything unsure stayed (a cricketer's wicket record under the match's Background; a
harassment complaint under the Background of a protest-site story).

The owner's old rule: "better something unrelated than miss something important". The new rule keeps it and
fixes the pollution: a line that does not belong to the story's own subject is NOT dropped, it is moved to
"Also in these reports" (`payload["also"]`, a collapsed list under the article, one plain line each, never in
a paragraph). Nothing is lost and nothing unrelated sits in the story.

One plain question per background / related / explanation line, a fixed choice, with the story's news as the
anchor and worked examples of the traps:
    history   the past of the story's own subject          -> Background (history slot)
    lead-up   an earlier step of this same matter          -> Background (lead-up slot)
    explains  what a term, place, rule or number means     -> Explained
    linked    a different event the line itself ties in    -> Related events
    other     anything else                                -> Also in these reports
Asked twice (the lines in reverse order the second time). Two answers that agree decide; two that differ in
KIND decide "other" (the safe answer: demoted, not deleted); history vs lead-up is settled by CODE from the
date (within 14 days before the news = lead-up). A line with fewer than two answers (quota, a model that never
answers) keeps the role extraction gave it: an outage never demotes anything. A background line dated AFTER
the news is not background: it goes to Related events. Reactions and "what next" are not asked (owner).

Paragraph subjects: `assign_topics` gives every statement a topic (the same one-call grouping dupes.py
uses) so plan.py never puts two topics in one paragraph.
"""
from __future__ import annotations

import hashlib
import logging

from .db import Store, select, stories, update
from .router import QuotaExhausted, Router

log = logging.getLogger(__name__)

MODEL_ROLES = ("background", "related", "explanation")
TAGS = ("history", "leadup", "explains", "linked", "other")
LEADUP_DAYS = 14        # dated within this many days before the news = lead-up, older = history (code, not model)

PROMPT = """A news story, and numbered lines from the pages that reported it. A news page often carries OTHER
news too (a sidebar, other videos, "also read" links, a live blog). The NEWS below is what the story is about.
For each numbered line choose ONE answer:

"history"  - the past of the story's own SUBJECT: how the place, rule, body or dispute at the centre of the NEWS
             came to be, or an earlier ruling or decision about that same subject.
"lead-up"  - an earlier step of THIS same matter, shortly before the NEWS, that led to it.
"explains" - says what a term, place, rule or number in the NEWS means.
"linked"   - a different event, but the line itself says how it is tied to the NEWS.
"other"    - anything else: another event or case (even with the same people or place), a record or fact about
             a person, a later event, or news that was only on the same page.

Examples, for the NEWS "Delhi Police removed Jantar Mantar Road from the list of designated protest sites":
  "Jantar Mantar had been a designated protest site for 33 years." -> history
  "In 2017 the National Green Tribunal banned protests at Jantar Mantar." -> history
  "On 10 October police detained activists during a protest at Jantar Mantar." -> lead-up
  "Jantar Mantar protests were held on the road, not inside the 18th-century observatory." -> explains
  "Three women journalists alleged harassment by police at an earlier protest." -> other (another case)
  "A Delhi Police inquiry into an earlier assault was moved to the Crime Branch." -> other (another case)
For the NEWS "India beat West Indies by 14 runs in the third T20":
  "West Indies' tour of India began on September 27." -> lead-up
  "Arshdeep Singh is India's highest wicket-taker in T20Is." -> other (a record, not this match)
For the NEWS "India's cheetah count reached 60 after cubs were born in Kuno":
  "Cheetahs were brought to Kuno from Namibia in 2022." -> history
  "Project Cheetah is India's programme to bring back the cheetah." -> explains
  "A Kerala minister defended a vigilance probe." -> other
If you are not sure: "other".

THE NEWS:
{news}

THE STORY'S OTHER STATEMENTS:
{story}

LINES:
{lines}

Reply with JSON only: {{"results": [{{"n": 1, "answer": "history"}}, {{"n": 2, "answer": "other"}}]}}"""

BATCH = 8


def _key(text: str) -> str:
    return hashlib.sha1((text or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def _story_text(payload: dict) -> tuple[str, str]:
    """What the model sees: (the news, the story's own statements up to ~1,400 characters)."""
    from .narrative import ordered_items
    from .news import pick_news
    items = [i for i in ordered_items(payload) if i.get("role", "core") == "core"] or ordered_items(payload)
    by_id = {i["id"]: i for i in items}
    news = [x for x in pick_news(items)[:2] if x in by_id]
    news_text = "\n".join(f"- {by_id[x]['text']}" for x in news) or "- " + (items[0]["text"] if items else "")
    shown, n = "", 0
    for i in items:
        if i["id"] in news:
            continue
        if n >= 10 or len(shown) + len(i["text"]) > 1400:
            break
        shown += f"- {i['text']}\n"
        n += 1
    return news_text, shown.strip() or "(none)"


def _norm(answer: object) -> str | None:
    a = str(answer or "").strip().lower().replace("-", "").replace(" ", "").replace("_", "")
    return a if a in TAGS else None


def resolve(answers: list[str]) -> str | None:
    """The tag two answers decide: history, leadup, bg (history or lead-up, settled by date), explains, linked or
    other. Fewer than two answers: None (undecided, nothing moves). Two that differ in kind: other."""
    if len(answers) < 2:
        return None
    a, b = answers[0], answers[1]
    if a == b:
        return a
    if {a, b} <= {"history", "leadup"}:
        return "bg"
    return "other"


def _news_start(payload: dict):
    from .narrative import ordered_items
    from .plan import _start
    import datetime as dt
    items = {i["id"]: i for i in ordered_items(payload)}
    starts = [_start(items[x]) for x in payload.get("news") or [] if x in items]
    starts = [s for s in starts if s != dt.datetime.max]
    return min(starts) if starts else None


def slot_of(tag: str, item: dict, news_start) -> str:
    """history or leadup. A dated line is placed by its date (code owns what code can know); an undated one by the
    model's answer ('bg': history)."""
    import datetime as dt
    from .plan import _start
    st = _start(item)
    if news_start is not None and st != dt.datetime.max:
        return "leadup" if (news_start - st) <= dt.timedelta(days=LEADUP_DAYS) else "history"
    return "leadup" if tag == "leadup" else "history"


def place(payload: dict, tags: dict[str, str | None]) -> dict:
    """Moves each tagged context line to where it belongs: role changed, or into payload["also"]. {kept, also, moved}."""
    from .plan import _start
    import datetime as dt
    news_start = _news_start(payload)
    keep, also, moved = [], [], 0
    for i in payload.get("context") or []:
        tag = tags.get(_key(i.get("text") or "")) if i.get("role") in MODEL_ROLES else None
        if tag is None:
            keep.append(i)
            continue
        if tag == "other":
            i["tag"] = "other"
            also.append(i)
            log.info("context line moved to 'also in these reports' (%s): %s", i.get("role"), (i.get("text") or "")[:100])
            continue
        was = i.get("role")
        if tag == "explains":
            i["role"] = "explanation"
        elif tag == "linked":
            i["role"] = "related"
        else:                                    # history / leadup / bg
            st = _start(i)
            if news_start is not None and st != dt.datetime.max and st - news_start > dt.timedelta(days=1):
                i["role"] = "related"            # dated after the news: not background
            else:
                i["role"] = "background"
                i["slot"] = slot_of(tag, i, news_start)
        i["tag"] = tag
        moved += i["role"] != was
        keep.append(i)
    payload["context"] = keep
    payload["also"] = also
    return {"kept": len(keep), "also": len(also), "moved": moved}


def check(store: Store, router: Router | None, story_id: int, payload: dict) -> dict:
    """Tags every background / related / explanation line (two answers each, cached per line text) and places it.
    Returns the counts from `place`."""
    lines = [i for i in payload.get("context") or [] if i.get("role") in MODEL_ROLES and i.get("text")]
    payload.setdefault("also", [])
    if not lines:
        return {"kept": len(payload.get("context") or []), "also": 0, "moved": 0}
    row = store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}
    an = dict(row.get("analysis") or {})
    cache: dict[str, list] = {k: [a for a in v if a in TAGS] for k, v in (an.get("context_tags") or {}).items()
                              if isinstance(v, list)}
    news, story = _story_text(payload)

    def ask(todo: list[dict]) -> None:
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            body = "\n".join(f'{k + 1}. "{i["text"]}"' for k, i in enumerate(chunk))
            try:
                res = router.call("page", PROMPT.format(news=news, story=story, lines=body), json_out=True,
                                  max_output_tokens=400)
            except QuotaExhausted:
                return
            except Exception as e:  # noqa: BLE001
                log.warning("context tagging failed: %s", str(e)[:200])
                continue
            got = set()
            for item in (res.data or {}).get("results", []) if isinstance(res.data, dict) else []:
                try:
                    n = int(item["n"]) - 1
                except (KeyError, TypeError, ValueError):
                    continue
                tag = _norm(item.get("answer")) if isinstance(item, dict) else None
                if 0 <= n < len(chunk) and n not in got and tag:
                    got.add(n)
                    cache.setdefault(_key(chunk[n]["text"]), []).append(tag)

    if router is not None:
        # first asking for lines never answered; then everything with one answer, the lines in reverse order
        ask([i for i in lines if not cache.get(_key(i["text"]))])
        ask(list(reversed([i for i in lines if len(cache.get(_key(i["text"])) or []) == 1])))
        if cache != (an.get("context_tags") or {}):
            an["context_tags"] = cache
            store.exec(update(stories).where(stories.c.id == story_id).values(analysis=an))
    tags = {_key(i["text"]): resolve(cache.get(_key(i["text"])) or []) for i in lines}
    return place(payload, tags)


def assign_topics(store: Store, router: Router | None, story_id: int, payload: dict) -> int:
    """A topic number on every statement (`topic`), so a paragraph is never two subjects. One grouping call
    (dupes.topics, cached by the statements' texts); a statement and what it must be written with (its response,
    its contradiction, the figure it updates) share a topic. Returns the number of topics; 0 when the call could not
    be made (plan.py then falls back to shared words)."""
    from . import dupes, plan
    from .narrative import ordered_items
    if router is None:
        return 0
    items = [i for i in ordered_items(payload) if i.get("text")]
    if len(items) < 3:
        return 0
    row = store.one(select(stories.c.analysis).where(stories.c.id == story_id)) or {}
    an = dict(row.get("analysis") or {})
    cache: dict = dict(an.get("topic_groups") or {})
    groups = dupes.topics(router, {i["id"]: i["text"] for i in items}, cache)
    if cache != (an.get("topic_groups") or {}):
        an["topic_groups"] = cache
        store.exec(update(stories).where(stories.c.id == story_id).values(analysis=an))
    if not groups:
        return 0
    by_id = {i["id"]: i for i in items}
    topic = {x: n for n, g in enumerate(groups) for x in g}
    for i in items:                                  # linked statements share the topic of the first
        for x in plan._links(i):
            if x in topic and i["id"] in topic:
                topic[x] = topic[i["id"]]
    for i in items:
        i["topic"] = topic.get(i["id"])
    return len({t for t in topic.values()})

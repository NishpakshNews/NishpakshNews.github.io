"""Pairing a story's names across languages, before its articles are read (session 4 of the translation/learning
plan; owner, Oct 15 2026).

The problem: each article is read on its own, and a Hindi outlet's name came back spelt the reading model's way
("Rimpoche" beside the English outlets' "Rimpochee"), so a Hindi and an English statement of the same fact did not
merge. Now, for each story about to be read:

1. LEARN (stories with English and Hindi sources). The English names are taken by code from the English outlets'
   text (people.py's reading of capitalised names), exactly as spelt. A name whose stored Hindi form appears word for
   word in a Hindi outlet's text is confirmed with no model call. For the rest, one closed question on the quality
   tier (the Translator key): "copy, character for character, the words this Hindi report uses for each name, or
   NONE". THE MODEL POINTS, IT NEVER TYPES: an answer counts only if it is found verbatim in a Hindi outlet's text,
   has as many words as the English name, is not given for two names, and is the same when the question is asked
   again with the names in the other order. Each name is then stored part by part in the registry (names.py) with
   the independent sources that wrote each spelling.
2. HINT (every Hindi article). Hindi words the registry knows are found in the article by exact lookup and given to
   the reading model with their English spelling, so the Hindi outlet's statement spells names the way the English
   outlets do before matching starts.

No quality quota, a refusal or any error: the story is read exactly as before (consolidate.py's spelling step stays
the backstop). Nothing here touches the publication quota.
"""
from __future__ import annotations

import collections
import logging
import re

from . import names as N

log = logging.getLogger(__name__)

MAX_NAMES = 25              # English names asked about per story
MAX_STORIES = 8             # stories asked about per run (two calls each)
MAX_HINDI_CHARS = 8000      # of the Hindi report shown to the model
MAX_HINTS = 30              # names hinted to one reading
_DEV_WORD = re.compile(r"[ऀ-ॣ॰-ॿ‌‍]+(?:-[ऀ-ॣ॰-ॿ‌‍]+)*")
_DEV = "ऀ-ॿ"
# English words that name the KIND of place after a name ("Kushok Bakula Rimpochee Airport"): Hindi translates them
# (हवाई अड्डा), so they are not part of a spelling and are taken off the end
KIND_WORDS = {"airport", "station", "terminal", "park", "hospital", "road", "bridge", "temple", "mosque", "church",
              "gurdwara", "dam", "project", "stadium", "lake", "river", "hills", "fort", "ghat", "market", "airbase",
              "port", "highway", "expressway", "tunnel", "canal", "palace", "museum", "school", "village", "city",
              "island", "islands", "valley", "pass", "camp", "base", "district", "tehsil", "block", "colony", "sector"}

PAIR_PROMPT = """Below are names from English news reports, and a Hindi news report on the same story.

For each English name, find the words the Hindi report uses for the same person, place or organisation, and COPY
them from the report character for character: the name only, without a title (श्री, जी, मंत्री) and without the
little words after it (ने, का, की, के, को, से, में). Copy, do not transliterate: if the Hindi report does not name it,
write NONE. Never write a spelling that is not in the report.

English names:
{items}

HINDI REPORT:
\"\"\"{text}\"\"\"

Answer as JSON: {{"names": ["...", "..."]}} with exactly {n} entries, in the same order as the English names."""


# -- pure code -------------------------------------------------------------------------------------------------------

def english_names(text: str) -> list[str]:
    """The names an English report gives people and places, exactly as spelt, most named first: capitalised runs
    with titles taken off (people.py). Not bodies ("Supreme Court": a translation, not a spelling, in Hindi) and not
    acronyms (BJP is बीजेपी or भाजपा by choice, not by spelling)."""
    from .people import BODY_END, NAME, _clean, _ok, _single_ok
    text = text or ""
    counts: collections.Counter = collections.Counter()
    for m in NAME.finditer(text):
        c = _clean(m.group(0))
        if not c or not _ok(c):
            continue
        ws = N.parts(c)
        while len(ws) > 1 and ws[-1].lower() in KIND_WORDS:
            ws = ws[:-1]
        if not ws or ws[-1].lower() in BODY_END or any(w.isupper() and len(w) > 1 for w in ws):
            continue
        if not all(N.valid_en(w) for w in ws):
            continue
        if len(ws) == 1 and not _single_ok(ws[0], text):
            continue
        counts[" ".join(ws)] += 1
    forms: list[str] = []
    for c in sorted(counts, key=lambda x: (-len(x.split()), -counts[x], x)):
        if not any(set(c.split()) <= set(f.split()) for f in forms):
            forms.append(c)
    return sorted(forms, key=lambda f: (-counts[f], f))[:MAX_NAMES]


def in_text(form: str, text: str, lang: str) -> bool:
    """`form` appears word for word in `text` (whole words only)."""
    if not form or not text:
        return False
    if lang == "hi":
        pat = rf"(?<![{_DEV}]){re.escape(form)}(?![{_DEV}])"
    else:
        pat = rf"(?<![\w-]){re.escape(form)}(?![\w-])"
    return re.search(pat, text) is not None


def agreed(names: list[str], first: list, second: list, hindi_texts: list[str]) -> dict[str, str]:
    """{English name: Hindi words} from two answers (`second` asked with the names in reverse order and given back in
    that order). Kept only when both answers are the same string, found verbatim in a Hindi text, with as many words
    as the English name, and not given for another name too."""
    if len(first) != len(names) or len(second) != len(names):
        return {}
    back = list(reversed(second))
    out: dict[str, str] = {}
    for en, a, b in zip(names, first, back):
        a, b = str(a or "").strip(), str(b or "").strip()
        if not a or a != b or a.upper() == "NONE":
            continue
        if len(N.parts(a)) != len(N.parts(en)) or not N.pair_parts(en, a):
            continue
        if not any(in_text(a, t, "hi") for t in hindi_texts):
            continue
        out[en] = a
    used = collections.Counter(N.fold_hi(h) for h in out.values())
    return {en: h for en, h in out.items() if used[N.fold_hi(h)] == 1}


def hints(text: str, reg: N.Registry) -> list[tuple[str, str]]:
    """(Hindi words, English spelling) for the names the registry knows in a Hindi text, longest runs first: runs of
    up to 4 known words in a row ("कुशोक बकुला रिम्पोछे" -> "Kushok Bakula Rimpochee"). Exact lookup only."""
    words = _DEV_WORD.findall(text or "")
    out: dict[str, str] = {}
    i = 0
    while i < len(words):
        run: list[tuple[str, str]] = []
        for w in words[i:i + 4]:
            c = reg.english(w)
            if c is None:
                break
            run.append((w, c.form))
        if run:
            out.setdefault(" ".join(h for h, _ in run), " ".join(e for _, e in run))
            i += len(run)
        else:
            i += 1
    return list(out.items())[:MAX_HINTS]


def hint_block(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return ""
    lines = "\n".join(f"{h} = {e}" for h, e in pairs)
    return ("\nNAMES: where the article names these, write them in English exactly so (the spelling English "
            f"outlets use):\n{lines}\n")


# -- the run ---------------------------------------------------------------------------------------------------------

def _ask(router, en_names: list[str], hindi: str) -> list | None:
    from .router import parse_json
    res = router.call("quality", PAIR_PROMPT.format(
        items="\n".join(f"{k + 1}. {n}" for k, n in enumerate(en_names)), text=hindi[:MAX_HINDI_CHARS],
        n=len(en_names)), json_out=True, max_output_tokens=60 + 30 * len(en_names))
    data = res.data if getattr(res, "data", None) is not None else parse_json(res.text or "")
    got = data.get("names") if isinstance(data, dict) else None
    return got if isinstance(got, list) else None


def learn_story(router, reg: N.Registry, story_id, english: list[dict], hindi: list[dict], when=None,
                stats: dict | None = None) -> int:
    """Pairs from one story. `english` / `hindi`: [{"text", "source"}] (source = names.source_key). Returns the
    number of name pairs stored."""
    from .router import CallFailed, QuotaExhausted
    stats = stats if stats is not None else collections.Counter()
    en_text = "\n".join(a["text"] or "" for a in english)
    hi_texts = [a["text"] or "" for a in hindi if a.get("text")]
    names_ = english_names(en_text)
    if not names_ or not hi_texts:
        return 0
    found: dict[str, str] = {}
    unknown = []
    for n in names_:
        h, _ = reg.hindi_name(n)
        if h and any(in_text(h, t, "hi") for t in hi_texts):
            found[n] = h                     # a stored form the Hindi outlet wrote too: no question needed
            stats["confirmed"] += 1
        else:
            unknown.append(n)
    if unknown and router is not None:
        try:
            if router.remaining_now("quality") > 0:
                main = max(hi_texts, key=len)
                first = _ask(router, unknown, main)
                second = _ask(router, list(reversed(unknown)), main) if first is not None else None
                stats["asked"] += 1
                if first is not None and second is not None:
                    got = agreed(unknown, first, second, hi_texts)
                    stats["agreed"] += len(got)
                    found.update(got)
        except (QuotaExhausted, CallFailed) as e:
            stats["skipped"] += 1
            log.info("namepair: story %s not asked (%s)", story_id, str(e)[:100])
    stored = 0
    for en, hi in found.items():
        en_src = [a["source"] for a in english if in_text(en, a["text"] or "", "en")]
        hi_src = [a["source"] for a in hindi if in_text(hi, a["text"] or "", "hi")]
        for e, h in N.pair_parts(en, hi):
            if reg.add_evidence(e, h, en_src, hi_src, story_id, when) is not None:
                stored += 1
    stats["pairs"] += stored
    return stored


def prepare(store, router, pending: list[dict], deadline: float | None = None) -> dict[int, str]:
    """Before the articles chosen this run are read: learn pairs from the stories with both languages, then
    {article id: names block for its reading prompt} for the Hindi articles. Never raises."""
    import time
    from .db import utcnow
    stats: collections.Counter = collections.Counter()
    try:
        reg = N.load(store)
        by_story: dict[int, list[dict]] = collections.defaultdict(list)
        for a in pending:
            if a.get("story_id"):
                by_story[a["story_id"]].append(a)
        now = utcnow()
        asked = 0
        for sid, arts in by_story.items():
            hindi = [dict(text=a.get("text"), source=N.source_key(a)) for a in arts if a.get("lang") == "hi"]
            if not hindi or asked >= MAX_STORIES or (deadline and time.time() > deadline):
                continue
            english = [dict(text=a.get("text"), source=N.source_key(a)) for a in arts if a.get("lang") == "en"]
            english += _read_english(store, sid, {a["id"] for a in arts})
            if not english:
                continue
            before = stats["asked"]
            learn_story(router, reg, sid, english, hindi, now, stats)
            asked += stats["asked"] - before
        N.save(store, reg)
        out = {}
        for a in pending:
            if a.get("lang") == "hi":
                h = hints(a.get("text") or "", reg)
                if h:
                    out[a["id"]] = hint_block(h)
                    stats["hinted"] += 1
        log.info("namepair: %s", dict(stats) or "nothing to do")
        return out
    except Exception as e:  # noqa: BLE001 - names improve a reading, they never stop one
        log.warning("namepair failed: %s", str(e)[:200])
        return {}


def _read_english(store, story_id: int, skip: set[int]) -> list[dict]:
    """English articles of the story read in earlier runs: their statements (the text itself is not fetched again,
    egress), one entry per article."""
    from sqlalchemy import select
    from .db import articles, claims
    rows = store.rows(select(articles.c.id, articles.c.outlet, articles.c.url, articles.c.agency,
                             articles.c.wire_group, claims.c.text)
                      .select_from(claims.join(articles, articles.c.id == claims.c.article_id))
                      .where(claims.c.story_id == story_id, articles.c.lang == "en"))
    by: dict[int, dict] = {}
    for r in rows:
        if r["id"] in skip:
            continue
        a = by.setdefault(r["id"], dict(r, text=""))
        a["text"] += " " + (r["text"] or "") + "."
    return [dict(text=a["text"], source=N.source_key(a)) for a in by.values()]

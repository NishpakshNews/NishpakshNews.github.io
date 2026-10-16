"""The Hindi page made the way the owner's Translator makes a book (session 6 of the translation/learning plan,
Oct 16 2026).

What was wrong: English-only stories reached the Hindi page with names in Latin letters ("Amrit Vats ने Djibouti
में ..."): the prompt said keep names "as they are", and nothing checked a mostly-Hindi string for English inside it.
Small words could be lost or added (fidelity.py), and nothing reviewed a draft against its source.

How a batch of English strings becomes Hindi now:
  1. NAMES BEFORE: the people and places in the batch are looked up in the name registry (names.py), exactly; a name
     no outlet pair covers is transliterated once on the quality tier and stored. The batch's prompt lists them
     ("Vats = वत्स"), with our binding terms (glossary `terms`) that occur in the batch. Nothing else is added.
  2. DRAFT on the page tier, as before, with the prompt asking for Devanagari names the way Hindi newspapers write
     them, and the formal news register.
  3. NAMES AFTER, by code: a known name left in Latin letters is replaced by its registry form (Hindi names do not
     change form in a sentence: "Vats ने"), longest first. This runs again whenever a page is rendered, so a name
     learned later mends pages translated before.
  4. CHECK by code: translation_problem (empty, echo, numbers) and fidelity.check_translation (small words lost or
     added, English left inside, binding terms not used).
  5. EDIT on the quality tier (the Translator key), Translator's second pass: the English and the draft side by
     side, each string's problems named; it returns corrected Hindi. An edited string replaces the draft only when
     it passes the hard checks and has no more problems than the draft. No quality quota: the draft stands.
Only strings with no hard problem are cached; a string with a remaining small problem keeps the better version.
"""
from __future__ import annotations

import json
import logging
import re

from . import fidelity as F
from . import names as N

log = logging.getLogger(__name__)
STATS: dict[str, int] = {}

_LATIN_NAME = re.compile(r"(?<![\w/.@-])[A-Z][a-z][A-Za-z'’-]*")

EDIT_PROMPT = """You are the editor of a Hindi news site. Below are English sentences and their Hindi drafts.
Correct each draft so that it says exactly what the English says, in the plain formal Hindi of Hindi newspapers:
  - keep every fact, number and date; add nothing, drop nothing, soften or strengthen nothing;
  - keep the small words that change a claim (not, never, only, at least, up to, more than, directly, alleged);
  - names of people and places in Devanagari as Hindi newspapers write them (use the NAMES list exactly);
    abbreviations as Hindi newspapers write them (BJP = भाजपा, ITF = आईटीएफ);
  - natural Hindi word order, not English sentence structure; gender and number agreement right;
  - anything in brackets (...) or [...] is copied letter for letter.
Where a line lists PROBLEMS, fix them. If a draft is already right, return it unchanged.
{names}
Return a JSON object with the same keys and the corrected Hindi as each value.

{items}"""


def stat(k: str, n: int = 1) -> None:
    STATS[k] = STATS.get(k, 0) + n


# -- names -----------------------------------------------------------------------------------------------------------

def name_parts(strings: list[str]) -> list[str]:
    """The name parts of people and places in English strings, exactly as spelt (namepair.english_names: no titles,
    bodies or acronyms)."""
    from .namepair import english_names
    out: dict[str, None] = {}
    for s in strings:
        for n in english_names(s):
            for w in N.parts(n):
                out.setdefault(w, None)
    return list(out)


def name_map(store, router, strings: list[str], reg: N.Registry | None = None) -> dict[str, str]:
    """{English part: Devanagari} for the people and places in these strings: the registry, then one
    transliteration on the quality tier for parts no pair covers (stored). Never raises."""
    try:
        reg = reg if reg is not None else N.load(store)
        words = name_parts(strings)
        if not words:
            return {}
        got = N.resolve(store, router, words, "hi", reg=reg)
        stat("names_known", sum(1 for c in got.values() if c.status != "translated"))
        stat("names_translated", sum(1 for c in got.values() if c.status == "translated"))
        stat("names_unknown", len(words) - len(got))
        return {w: c.form for w, c in got.items()}
    except Exception as e:  # noqa: BLE001 - names improve a translation, they never stop one
        log.warning("hindi names failed: %s", str(e)[:150])
        return {}


def known_names(reg: N.Registry, texts: list[str]) -> dict[str, str]:
    """{English part: Devanagari} for Latin words in these texts the registry knows (no call)."""
    out = {}
    for t in texts:
        for w in _LATIN_NAME.findall(t or ""):
            c = reg.hindi(w)
            if c is not None:
                out[w] = c.form
    return out


def devanagari_names(hindi: str, names: dict[str, str]) -> str:
    """Latin name parts left in a Hindi string replaced by their Devanagari forms, longest first, whole words only;
    a name in brackets (copied on purpose, refs.py) is left as it is."""
    if not hindi or not names:
        return hindi
    keep = [(m.start(), m.end()) for m in re.finditer(r"[\(\[][^()\[\]]*[\)\]]", hindi)]
    pat = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in sorted(names, key=len, reverse=True))
                     + r")(?![\w-])")

    def sub(m):
        if any(a <= m.start() < b for a, b in keep):
            return m.group(0)
        return names[m.group(1)]
    return pat.sub(sub, hindi)


def names_block(names: dict[str, str], strings: list[str]) -> str:
    joined = " ".join(strings)
    used = [(e, h) for e, h in names.items() if re.search(rf"(?<![\w-]){re.escape(e)}(?![\w-])", joined)]
    if not used:
        return ""
    return "\nNAMES (write them exactly so): " + "; ".join(f"{e} = {h}" for e, h in used) + "\n"


def terms_block(strings: list[str]) -> str:
    found: dict[str, str] = {}
    for s in strings:
        for en, hi in F.terms_in(s):
            found.setdefault(en, hi)
    if not found:
        return ""
    return "\nTERMS (always this Hindi): " + "; ".join(f"{e} = {h}" for e, h in found.items()) + "\n"


# -- checks and the edit pass ----------------------------------------------------------------------------------------

def problems(en: str, hi: str) -> tuple[str | None, list[F.Problem]]:
    """(the hard problem that keeps a string out of the cache, or None; the small ones)."""
    from .compose import translation_problem
    return translation_problem(en, hi), F.check_translation(en, hi)


def better(en: str, draft: str | None, edited: str | None) -> str | None:
    """The edited string when it passes the hard checks and has no more small problems than the draft."""
    if not edited:
        return draft
    hard_e, small_e = problems(en, edited)
    if hard_e:
        return draft
    if draft is None:
        return edited
    hard_d, small_d = problems(en, draft)
    return edited if hard_d or len(small_e) <= len(small_d) else draft


def edit(router, pairs: list[tuple[str, str | None]], names: dict[str, str]) -> dict[int, str]:
    """{index: edited Hindi} from one call on the quality tier for (English, draft) pairs; a missing draft is
    written from the English. No quota or a refusal: {}."""
    from .router import CallFailed, QuotaExhausted, parse_json
    if router is None or not pairs:
        return {}
    try:
        if router.remaining_now("quality") <= 0:
            stat("edit_no_quota")
            return {}
    except Exception:  # noqa: BLE001
        return {}
    lines = []
    for i, (en, hi) in enumerate(pairs):
        lines.append(f'{i}. EN: {en}')
        lines.append(f'   HI: {hi or "(none: translate it)"}')
        if hi:
            hard, small = problems(en, hi)
            notes = ([hard] if hard else []) + [_describe(p) for p in small]
            if notes:
                lines.append("   PROBLEMS: " + "; ".join(notes))
    prompt = EDIT_PROMPT.format(names=names_block(names, [e for e, _ in pairs]), items="\n".join(lines))
    try:
        res = router.call("quality", prompt, json_out=True, max_output_tokens=200 + 120 * len(pairs))
    except (QuotaExhausted, CallFailed) as e:
        stat("edit_refused")
        log.info("hindi edit skipped: %s", str(e)[:120])
        return {}
    data = res.data if getattr(res, "data", None) is not None else parse_json(res.text or "")
    if not isinstance(data, dict):
        return {}
    stat("edit_calls")
    out = {}
    for k, v in data.items():
        if str(k).isdigit() and int(k) < len(pairs) and isinstance(v, str) and v.strip():
            out[int(k)] = v.strip()
    return out


def _describe(p: F.Problem) -> str:
    if p.kind == "latin":
        return f"'{p.what}' is still in English letters"
    if p.kind == "term":
        return f"'{p.what}' must be {dict(F.glossary()['terms']).get(p.what, '')}"
    q = {q.id: q for q in F.glossary()["qualifiers"]}.get(p.what)
    words = "/".join(q.en[:3]) if q else p.what
    return (f"the draft drops '{words}'" if p.kind == "lost" else f"the draft adds '{words}', which the English lacks")


def finish(router, chunk: list[str], drafts: dict[int, str], names: dict[str, str]) -> tuple[dict[int, str], dict]:
    """The batch after names, checks and the edit pass: ({index: Hindi to cache}, {index: reason not cached})."""
    fixed = {i: devanagari_names(h, names) for i, h in drafts.items()}
    flagged = [i for i in range(len(chunk))
               if i not in fixed or problems(chunk[i], fixed[i])[0] or problems(chunk[i], fixed[i])[1]]
    stat("strings", len(chunk))
    stat("drafts_with_problem", len(flagged))
    need = list(range(len(chunk)))          # Translator edits every batch (grammar and register too), one call each
    if need:
        edited = edit(router, [(chunk[i], fixed.get(i)) for i in need], names)
        for j, i in enumerate(need):
            if j in edited:
                e = devanagari_names(edited[j], names)
                b = better(chunk[i], fixed.get(i), e)
                if b is not None and b is not fixed.get(i):
                    stat("edit_accepted")
                fixed[i] = b if b is not None else fixed.get(i)
    keep, why = {}, {}
    for i, h in fixed.items():
        if h is None:
            continue
        hard, small = problems(chunk[i], h)
        if hard:
            why[i] = hard
            continue
        if small:
            stat("cached_with_small_problem")
        keep[i] = h
    for i in range(len(chunk)):
        if i not in keep and i not in why:
            why[i] = "not translated"
    return keep, why


def cache_version() -> str:
    """Part of every cached translation's key: our binding terms (glossary `terms`). Changing one translates again;
    names learned later need no new translation (devanagari_names mends them on every render)."""
    import hashlib
    body = json.dumps(sorted(F.glossary()["terms"]), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]

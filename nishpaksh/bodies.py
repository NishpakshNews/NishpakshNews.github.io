"""Which body a speaker is, from Wikidata (entity linking), not from a list of aliases (owner, Oct 25 2026).

"The Centre", "the Central government", "Union government" and "Government of India" are ONE speaker; "Washington Post" is
a newspaper and never a government; "Allahabad High Court" is not the "Supreme Court". Wikidata, an established
knowledge base, knows this: its search matches a name against labels and aliases, and its class tree says whether the
thing is a government, a court or something else. We take its strongest attributes only:
  * an EXACT label / alias match (a fuzzy match is no match);
  * several exact matches (\"Supreme Court\" exists in many countries): the one in the context country (India) or none;
  * the class tree (instance of / subclass of): a GOVERNMENT is the speaker `gov:<country>`; a COURT is `court:<id>`;
    anything else it knows is `org:<id>` (ministries stay separate speakers from the government: two ministries are
    not one voice).
Each name is asked once and kept for good in the table `body_links` (a "not found" is asked again after 30 days).
`key_for(name)` reads the cache only (no network): speaker_key is called in many places; the lookups are done once per
story by `prefetch(store, names)` before the writer runs. Tri-state: a lookup that could not be made (network, quota,
circuit open) is not cached and is not an answer; the name then keeps its own key, exactly as written.
`set_backend(fn)` for tests: fn(name, context_country) -> dict | None | UNAVAILABLE.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("nishpaksh.bodies")

API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
UA = {"User-Agent": "NishpakshNews/1.0 (https://nishpakshnews.github.io)"}
CONTEXT_COUNTRY = "Q668"              # India: the site is about India; a name with another country in it matches that one
# Wikidata classes (the knowledge base's own, not words): government, court
GOVERNMENT = ("Q7188",)
COURT = ("Q41487",)
RECHECK_DAYS = 30
UNAVAILABLE = object()

_backend = None
_cache: dict[str, "Body"] = {}
_missing: dict[str, dt.datetime] = {}      # names Wikidata does not know: when it was asked


@dataclass
class Body:
    name: str
    key: str | None                # gov:Q668 / court:Q.. / org:Q.. ; None = Wikidata does not know it
    kind: str = ""
    label: str = ""
    country: str = ""
    words: list[str] = field(default_factory=list)       # label + aliases: what a sentence may call the speaker
    checked: dt.datetime | None = None


def set_backend(fn) -> None:
    global _backend
    _backend = fn


def reset() -> None:
    _cache.clear()
    _missing.clear()


def norm(name: str | None) -> str:
    n = re.sub(r"^(?:the|a|an)\s+", "", (name or "").strip().lower())
    return re.sub(r"\s+", " ", n.replace("’", "'"))


def _candidate(name: str) -> bool:
    """Only Latin-letter names are looked up (Hindi names go through the name registry's English form); a person's
    name is the entity table's business, not a body's: more than five words or no letters is not asked."""
    return bool(re.search(r"[A-Za-z]", name)) and not re.search(r"[^\x00-\x7f’]", name) and 1 <= len(name.split()) <= 7


def key_for(name: str | None) -> str | None:
    b = _cache.get(norm(name))
    return b.key if b else None


def body_of(name: str | None) -> Body | None:
    b = _cache.get(norm(name))
    return b if b and b.key else None


def words_of(name: str | None) -> set[str]:
    b = body_of(name)
    return {w for x in (b.words if b else []) for w in re.findall(r"[a-z]{3,}", x.lower())}


def is_known_body(name: str | None) -> bool:
    return body_of(name) is not None


# ------------------------------------------------------------------ asking Wikidata
def _get(url: str, params: dict):
    import requests
    from .reliable import HttpFailure
    r = requests.get(url, params=params, headers=UA, timeout=15)
    if r.status_code != 200:
        raise HttpFailure(r.status_code, r.text)
    return r.json()


def lookup(name: str, context_country: str = CONTEXT_COUNTRY):
    """A dict (found / not found) or UNAVAILABLE. The one place that talks to Wikidata."""
    from . import reliable
    want = norm(name)

    def search():
        return _get(API, {"action": "wbsearchentities", "search": re.sub(r"^(?:the|The)\s+", "", name.strip()),
                          "language": "en", "limit": 8, "format": "json"})
    out = reliable.call("wikidata", search)
    if not out.ok:
        return UNAVAILABLE
    exact = []
    for r in out.value.get("search", []):
        m = r.get("match") or {}
        if norm(m.get("text")) == want:
            exact.append(r)
    if not exact:
        return {"found": False}
    ids = " ".join(f"wd:{r['id']}" for r in exact)
    q = ("SELECT ?e ?country ?gov ?court WHERE { VALUES ?e { %s } OPTIONAL { ?e wdt:P17 ?country } "
         "OPTIONAL { ?e wdt:P1001 ?juris } "
         "BIND(EXISTS { ?e wdt:P31/wdt:P279* ?g . VALUES ?g { %s } } AS ?gov) "
         "BIND(EXISTS { ?e wdt:P31/wdt:P279* ?c . VALUES ?c { %s } } AS ?court) }"
         % (ids, " ".join("wd:" + x for x in GOVERNMENT), " ".join("wd:" + x for x in COURT)))
    out2 = reliable.call("wikidata", lambda: _get(SPARQL, {"query": q, "format": "json"}))
    if not out2.ok:
        return UNAVAILABLE
    info: dict[str, dict] = {}
    for b in out2.value.get("results", {}).get("bindings", []):
        qid = b["e"]["value"].rsplit("/", 1)[-1]
        d = info.setdefault(qid, {"countries": set(), "gov": False, "court": False})
        if "country" in b:
            d["countries"].add(b["country"]["value"].rsplit("/", 1)[-1])
        d["gov"] |= b.get("gov", {}).get("value") == "true"
        d["court"] |= b.get("court", {}).get("value") == "true"
    cands = []
    for r in exact:
        d = info.get(r["id"], {"countries": set(), "gov": False, "court": False})
        cands.append({"id": r["id"], "label": r.get("label") or "", "aliases": r.get("aliases") or [],
                      "countries": sorted(d["countries"]), "gov": d["gov"], "court": d["court"]})
    return {"found": True, "candidates": cands}


def choose(name: str, answer: dict, context_country: str = CONTEXT_COUNTRY) -> Body:
    """Turn Wikidata's exact matches into one body, or into 'not known'. Several matches: the one in the context
    country; none of them there (and no country named in the text): unknown, never a guess."""
    cands = answer.get("candidates") or []
    if len(cands) > 1:
        here = [c for c in cands if context_country in c["countries"]]
        cands = here if len(here) == 1 else []
    if not cands:
        return Body(name, None)
    c = cands[0]
    country = c["countries"][0] if c["countries"] else ""
    if c["gov"]:
        kind, key = "government", f"gov:{country or c['id']}"
    elif c["court"]:
        kind, key = "court", f"court:{c['id']}"
    else:
        kind, key = "org", f"org:{c['id']}"
    return Body(name, key, kind, c["label"], country, [c["label"], *c["aliases"]])


def resolve(name: str) -> Body | None:
    """Ask for one name (cache first). None = could not ask; a Body with key None = Wikidata does not know it."""
    n = norm(name)
    if not n or not _candidate(name):
        return Body(name or "", None)
    if n in _cache:
        return _cache[n]
    asked = _missing.get(n)
    if asked and (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - asked).days < RECHECK_DAYS:
        return Body(name, None)
    ans = (_backend or lookup)(name, CONTEXT_COUNTRY)
    if ans is UNAVAILABLE or ans is None:
        return None
    body = choose(name, ans)
    body.checked = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if body.key:
        _cache[n] = body
    else:
        _missing[n] = body.checked
    return body


# ------------------------------------------------------------------ the table
def load(store) -> int:
    from sqlalchemy import select
    from .db import body_links
    try:
        rows = store.rows(select(body_links))
    except Exception as e:  # noqa: BLE001 - a copy from before the table existed
        log.info("bodies: no body_links table yet (%s)", str(e)[:80])
        return 0
    for r in rows:
        n = r["name"]
        if r["key"]:
            _cache[n] = Body(n, r["key"], r["kind"] or "", r["label"] or "", r["country"] or "", list(r["words"] or []), r["checked_at"])
        else:
            _missing[n] = r["checked_at"] or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return len(rows)


def prefetch(store, names, limit: int = 25) -> dict:
    """Before a story is written: look up every speaker name not yet known (at most `limit`), keep the answers.
    Never raises; a lookup that could not be made is left for the next run."""
    stats = {"asked": 0, "found": 0, "unknown": 0, "unavailable": 0}
    try:
        load(store)
        todo = [n for n in dict.fromkeys(names or []) if n and norm(n) not in _cache and norm(n) not in _missing and _candidate(n)]
        new: list[Body] = []
        for n in todo[:limit]:
            b = resolve(n)
            stats["asked"] += 1
            if b is None:
                stats["unavailable"] += 1
                if stats["unavailable"] >= 2:
                    break                      # the service is down: stop asking, try next run
                continue
            stats["found" if b.key else "unknown"] += 1
            new.append(b)
        _save(store, new)
    except Exception as e:  # noqa: BLE001 - identity then falls back to the names as written
        log.warning("bodies.prefetch failed: %s", str(e)[:120])
    return stats


def _save(store, bodies: list[Body]) -> None:
    if not bodies:
        return
    from sqlalchemy import delete, insert
    from .db import body_links
    with store.route(insert(body_links)).engine.begin() as c:
        for b in bodies:
            n = norm(b.name)
            c.execute(delete(body_links).where(body_links.c.name == n))
            c.execute(insert(body_links).values(name=n, key=b.key, kind=b.kind, label=b.label, country=b.country,
                                                words=b.words, checked_at=b.checked))

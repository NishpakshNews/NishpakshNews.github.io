"""Which sections of the site an article belongs to.

THREE LEVELS OF THREE (owner, Oct 28 2026; "I want them like 3 and 3 only, in all levels"): India · World · Business,
three sections under each and three under each of those. Chosen after looking at how other outlets cut the news
(Inshorts flat, Al Jazeera by region; Indian dailies India / World / Business / Sports / Entertainment, flat or two
levels). The live feed then had politics, crime and courts as most of India; sport and films (the express lane) about
a seventh of all articles, so they are a third-level section under India > Life (owner kept that knowingly).

An article gets up to two of each level ("Supreme Court refuses to suspend the CEC" is India > Justice > Courts and
India > Politics > Elections). One page-tier call when the article is published, from its headline, its lead and its
main statements; asked once (a section can make nothing green and merge nothing). Code checks the answer: only listed
keys, a lower level brings its parents with it, at most two of each, the higher level alone when the model is unsure.
No answer = no section: the article is published anyway, it is never held back for this.

Stored as `payload.category = {"v": 2, "primary": [...], "secondary": [...], "tertiary": [...]}` (keys, first = main),
the same in the Hindi payload. A record WITHOUT "v" is from the earlier five-by-five tree (Oct 9 2026: Politics,
Justice, Business, World, Life and the Domains lens): `normalize` maps it into this tree by code (no model call, no
stored page rewritten, reversible), and `fill_live` asks the new question for live articles a few per run, so their
third level fills in. Readers' follows of earlier paths map the same way (`follow_path`).
"""
from __future__ import annotations

import logging
import re

from .router import QuotaExhausted, Router

log = logging.getLogger(__name__)

VERSION = 2

# key: (English, Hindi, what belongs there, for the prompt). Keys are unique across ALL levels (the site filters
# over one flat set of keys).
SECTIONS: dict[str, dict[str, tuple[str, str, str]]] = {
    "india": {
        "politics": ("Politics", "राजनीति", "governments, parties, leaders, Parliament and assemblies, elections, political protests"),
        "justice": ("Justice", "न्याय", "crime, police, courts, investigating agencies and corruption cases"),
        "life": ("Life", "जीवन", "health, schools and colleges, sport, films, weather, disasters and accidents in India"),
    },
    "world": {
        "diplomacy": ("Diplomacy", "कूटनीति", "India's relations with other countries, Indians abroad, the UN and summits"),
        "conflicts": ("Conflicts", "संघर्ष", "wars, the armed forces, terror outside India or across its borders"),
        "abroad": ("Abroad", "विदेश", "news from other countries that is not about India"),
    },
    "business": {
        "economy": ("Economy", "अर्थव्यवस्था", "economic policy, official figures, jobs and work"),
        "companies": ("Companies", "कंपनियां", "firms: results, deals, launches, their leaders"),
        "markets": ("Markets", "बाज़ार", "shares, the rupee, gold and oil prices, what things cost a household"),
    },
}
TERTIARY: dict[str, dict[str, tuple[str, str, str]]] = {
    "politics": {
        "government": ("Government", "सरकार", "decisions, schemes, appointments and rules of the Centre or a state; Parliament, assemblies and bills"),
        "parties": ("Parties", "दल", "parties and leaders: alliances, splits, posts in a party, attacks on each other, their protests and marches"),
        "elections": ("Elections", "चुनाव", "polls, by-elections, voter lists, the Election Commission, candidates, results"),
    },
    "justice": {
        "crime": ("Crime", "अपराध", "murders, assaults, rape, theft, fraud, cyber crime; terror and militancy cases inside India"),
        "courts": ("Courts", "अदालत", "Supreme Court, High Courts and other courts: hearings, orders, bail, verdicts"),
        "probes": ("Probes", "जांच", "police, CBI, ED, NIA and vigilance at work: raids, arrests, FIRs, charge sheets, corruption cases"),
    },
    "life": {
        "health": ("Health & schools", "सेहत और शिक्षा", "hospitals, diseases, medicines, food safety; schools, universities, exams, students, research"),
        "sport-films": ("Sport & films", "खेल और फ़िल्में", "sport, cinema, TV, music, actors and players"),
        "weather": ("Weather & accidents", "मौसम और हादसे", "weather, pollution, wildlife, climate; road, rail and air accidents, fires, collapses, floods, earthquakes"),
    },
    "diplomacy": {
        "visits": ("India abroad", "विदेश में भारत", "India's talks, visits, statements and agreements with other countries"),
        "diaspora": ("Indians abroad", "प्रवासी भारतीय", "Indians, Indian crews, students and workers in trouble or in the news abroad"),
        "global": ("Global", "वैश्विक", "the UN, summits and international bodies, and agreements between other countries"),
    },
    "conflicts": {
        "wars": ("Wars", "युद्ध", "wars, attacks and fighting outside India"),
        "defence": ("Defence", "रक्षा", "India's armed forces, defence deals, weapons tests, DRDO, service chiefs, the borders"),
        "terror": ("Terror", "आतंक", "terror groups and attacks abroad, cross-border terror against India"),
    },
    "abroad": {
        "foreign-politics": ("Politics", "राजनीति", "other countries' governments, leaders, elections and protests"),
        "disasters": ("Disasters", "आपदाएं", "earthquakes, floods, storms, crashes and accidents in other countries"),
        "other": ("Other news", "अन्य ख़बरें", "anything else from other countries: courts, science, business, people"),
    },
    "economy": {
        "policy": ("Policy", "नीति", "RBI decisions, the budget, GST, taxes, trade rules, economic policy"),
        "data": ("Data", "आंकड़े", "GDP, inflation, trade, jobs and other official figures"),
        "jobs": ("Jobs & work", "नौकरी और काम", "hiring, recruitment drives and exams, layoffs, pay, labour law, PF, work visas, workplace rules"),
    },
    "companies": {
        "results": ("Results & deals", "नतीजे और सौदे", "earnings, mergers, IPOs, funding, banks and insurers as businesses, regulators acting on a firm"),
        "launches": ("Launches & tech", "लॉन्च और टेक", "new products and services, technology, telecom, apps, AI, advertising and brands"),
        "leaders": ("Leaders", "लीडर", "a company's founders, chiefs and boards: appointments, exits, remarks"),
    },
    "markets": {
        "stocks": ("Stocks", "शेयर", "Sensex and Nifty, share prices, listings, SEBI and the stock exchanges"),
        "rupee": ("Rupee & commodities", "रुपया और कमोडिटी", "the rupee, gold, silver, crude oil and other commodity prices"),
        "money": ("Your money", "आपका पैसा", "prices, EMIs, taxes on people, fares, fees, savings rates: what things cost a household"),
    },
}
PRIMARY_LABELS = {"india": ("India", "भारत"), "world": ("World", "दुनिया"), "business": ("Business", "बिज़नेस")}
PARENT = {s: p for p, subs in SECTIONS.items() for s in subs}
PARENT3 = {t: s for s, subs in TERTIARY.items() for t in subs}
MAX_EACH = 2

# the daily brief's sections: India's three, then World and Business (recap.py)
RECAP_LABELS = {"politics": ("Politics", "राजनीति"), "justice": ("Justice", "न्याय"), "life": ("Life", "जीवन"),
                "world": ("World", "दुनिया"), "business": ("Business", "बिज़नेस")}

# ---- the earlier tree (Oct 9 2026) in this one: every old key -> (primary, secondary or None, tertiary or None) ----
OLD_PRIMARY = {"politics": ("india", "politics", None), "justice": ("india", "justice", None), "life": ("india", "life", None),
               "business": ("business", None, None), "world": ("world", None, None)}
OLD_SECONDARY = {
    "elections": ("india", "politics", "elections"), "parties": ("india", "politics", "parties"),
    "government": ("india", "politics", "government"), "parliament": ("india", "politics", "government"),
    "protests": ("india", "politics", None),
    "crime": ("india", "justice", "crime"), "police": ("india", "justice", "probes"), "courts": ("india", "justice", "courts"),
    "corruption": ("india", "justice", "probes"), "terror": ("india", "justice", "crime"),
    "economy": ("business", "economy", None), "companies": ("business", "companies", None),
    "markets": ("business", "markets", None), "money": ("business", "markets", "money"), "domains": ("business", None, None),
    "diplomacy": ("world", "diplomacy", None), "indians-abroad": ("world", "diplomacy", "diaspora"),
    "conflicts": ("world", "conflicts", None), "defence": ("world", "conflicts", "defence"), "abroad": ("world", "abroad", None),
    "health": ("india", "life", "health"), "education": ("india", "life", "health"), "accidents": ("india", "life", "weather"),
    "environment": ("india", "life", "weather"), "sport-films": ("india", "life", "sport-films"),
    "jobs": ("business", "economy", "jobs"), "tech": ("business", "companies", "launches"),   # keys from before Oct 9
}
OLD_TERTIARY = {"hr": ("business", "economy", "jobs"), "finance": ("business", "companies", "results"),
                "marketing": ("business", "companies", "launches"), "analytics": ("business", "companies", "launches"),
                "operations": ("business", "companies", None)}


def labels(lang: str = "en") -> dict:
    """{"primary": {key: label}, "secondary": {key: label}, "tertiary": {key: label},
    "tree": {primary: [secondary, ...]}, "tree3": {secondary: [tertiary, ...]}} for the site."""
    k = 1 if lang == "hi" else 0
    return {"primary": {p: PRIMARY_LABELS[p][k] for p in SECTIONS},
            "secondary": {s: SECTIONS[PARENT[s]][s][k] for s in PARENT},
            "tertiary": {t: TERTIARY[PARENT3[t]][t][k] for t in PARENT3},
            "tree": {p: list(subs) for p, subs in SECTIONS.items()},
            "tree3": {s: list(subs) for s, subs in TERTIARY.items()}}


def chain(key: str) -> tuple[str, ...]:
    """A key's whole path in today's tree: ("india", "justice", "courts"); () for an unknown key."""
    if key in PARENT3:
        return (PARENT[PARENT3[key]], PARENT3[key], key)
    if key in PARENT:
        return (PARENT[key], key)
    return (key,) if key in SECTIONS else ()


def _menu() -> str:
    out = []
    for p, subs in SECTIONS.items():
        out.append(f"{p}  ({PRIMARY_LABELS[p][0]})")
        for s, (label, _, d) in subs.items():
            out.append(f"  {p}/{s}  ({label}: {d})")
            out += [f"    {p}/{s}/{t}: {dt}" for t, (_, _, dt) in TERTIARY[s].items()]
    return "\n".join(out)


def _build(paths) -> dict:
    """A record from (primary, secondary, tertiary) paths in order: at most two of each level, a lower level only
    with its parents in the record."""
    prim: list[str] = []
    sec: list[str] = []
    ter: list[str] = []
    for p, s, t in paths:
        if p not in prim:
            if len(prim) >= MAX_EACH:
                continue
            prim.append(p)
        if s and s not in sec:
            if len(sec) >= MAX_EACH:
                continue
            sec.append(s)
        if t and s in sec and t not in ter and len(ter) < MAX_EACH:
            ter.append(t)
    if not prim:
        return {}
    return {"v": VERSION, "primary": prim, "secondary": sec, **({"tertiary": ter} if ter else {})}


def normalize(cat: dict | None) -> dict:
    """A stored section record in today's tree. A record of the earlier tree (no "v") is mapped key by key: its
    secondaries first (the main one first), then its tertiaries, then any primary left without a secondary."""
    cat = dict(cat or {})
    prim, sec, ter = list(cat.get("primary") or []), list(cat.get("secondary") or []), list(cat.get("tertiary") or [])
    if not prim and not sec and not ter:
        return {}
    if cat.get("v") == VERSION:
        paths = [(c + (None, None))[:3] for c in (chain(k) for k in [*ter, *sec, *prim]) if c]
        out = _build(sorted(paths, key=lambda c: prim.index(c[0]) if c[0] in prim else 9))
        return out
    paths = [OLD_SECONDARY[s] for s in sec if s in OLD_SECONDARY]
    paths += [OLD_TERTIARY[t] for t in ter if t in OLD_TERTIARY]
    paths += [OLD_PRIMARY[p] for p in prim if p in OLD_PRIMARY]
    return _build(paths)


def follow_path(key: str) -> str:
    """A reader's followed section ("justice/courts", "business/domains/hr", "india/justice") as a path of today's
    tree. A path valid today stays; an earlier one maps like an article's record."""
    parts = [x for x in str(key or "").strip("/").split("/") if x]
    if parts and tuple(parts) == chain(parts[-1]):
        return "/".join(parts)
    last = parts[-1] if parts else ""
    old = OLD_TERTIARY.get(last) if len(parts) == 3 else OLD_SECONDARY.get(last) if len(parts) == 2 else OLD_PRIMARY.get(last)
    if not old:
        return str(key or "")
    return "/".join(x for x in old if x)


def paths(cat: dict | None) -> set[str]:
    """Every path an article is in: "india", "india/justice", "india/justice/courts"."""
    cat = normalize(cat)
    out: set[str] = set()
    for k in [*(cat.get("primary") or []), *(cat.get("secondary") or []), *(cat.get("tertiary") or [])]:
        c = chain(k)
        out |= {"/".join(c[:i]) for i in range(1, len(c) + 1)}
    return out


PROMPT = """Put this Indian news article in the sections of a news site.

Sections: three main ones, three sections under each, and three under each of those:
{menu}

Pick 1 to 3 sections, the main one first, as a full path like "india/justice/courts".
Pick another only if the article is really about that too, not because a word appears.
If you are unsure of the last level, give the path one level up (for example "india/life").
Judge by what the NEWS is (the headline), not by who is in it.

Examples:
- "Supreme Court refuses to suspend Chief Election Commissioner" -> ["india/justice/courts", "india/politics/elections"]
- "Police detain Rahul Gandhi at Jantar Mantar protest" -> ["india/politics/parties"]  (a political protest, not a crime)
- "Supreme Court orders actor Rajpal Yadav to pay Rs 5 crore" -> ["india/justice/courts"]  (an actor, but the news is the order)
- "Actor Nana Patekar dies at 75" -> ["india/life/sport-films"]
- "Defence Ministry signs Rs 661 crore BrahMos deal" -> ["world/conflicts/defence"]
- "23 Indian crew rescued from burning tanker in Black Sea" -> ["world/diplomacy/diaspora", "world/conflicts/wars"]
- "RBI raises repo rate to 5.50 per cent" -> ["business/economy/policy", "business/markets/money"]
- "TCS to cut 12,000 jobs" -> ["business/economy/jobs", "business/companies/results"]
- "Sensex falls 900 points as oil jumps" -> ["business/markets/stocks"]
- "Four students die cleaning a water tank in Vrindavan" -> ["india/life/weather"]
- "CBI raids Punjab CM's office over graft claims" -> ["india/justice/probes", "india/politics/government"]
- "Three terrorists killed in encounter in Kupwara" -> ["india/justice/crime", "world/conflicts/defence"]
- "Pakistan-based group behind Pahalgam attack, says NIA" -> ["world/conflicts/terror", "india/justice/probes"]
- "Earthquake of magnitude 6.8 hits Japan" -> ["world/abroad/disasters"]
- "Rain and strong winds forecast in 24 states" -> ["india/life/weather"]

Also give the Indian states or union territories where the news HAPPENS, at most 3, main first: where the event
took place, or the state of a High Court or of a state government acting; NOT the city a central minister or the
Centre speaks from, and not a person's home state when the news is elsewhere. Use [] for news abroad or for news
about all of India. Keys: {states}

HEADLINE: {headline}
THE ARTICLE OPENS: {lead}
OTHER FACTS:
{facts}

Reply with JSON only: {{"sections": ["...", "..."], "states": ["..."]}}"""


def _key(x: str) -> str:
    return re.sub(r"[\s_&]+", "-", str(x or "").strip().lower().strip('"\'')).strip("-")


def parse(picks) -> dict | None:
    """The model's picks, checked by code: a pick counts by its deepest listed key, and every other key it names must
    lie on that key's path (else it is dropped, no guess); a lower level brings its parents; at most two of each
    level, in the model's order."""
    if isinstance(picks, str):
        picks = [picks]
    paths_: list[tuple] = []
    for raw in picks or []:
        parts = [_key(x) for x in str(raw or "").split("/") if _key(x)]
        known = [chain(x) for x in parts]
        if not parts or not all(known):
            continue
        deepest = max(known, key=len)
        if not all(p in deepest for p in parts):
            continue
        paths_.append((deepest + (None, None))[:3])
    out = _build(paths_)
    return out or None


def classify(router: Router | None, headline: str, lead: str, facts: list[str]) -> dict | None:
    """The article's sections; {} when the model answered twice with no listed section; None when it could
    not be asked (quota, errors). Either way the article is published, without a section."""
    if router is None or not headline:
        return None
    from .places import menu as state_menu
    prompt = PROMPT.format(menu=_menu(), states=state_menu(), headline=headline, lead=lead or headline,
                           facts="\n".join(f"- {f}" for f in facts[:5]) or "- (none)")
    for _ in range(2):                     # a second call only when the first gave nothing usable
        try:
            res = router.call("page", prompt, json_out=True, max_output_tokens=160)
        except (QuotaExhausted, Exception) as e:  # noqa: BLE001
            log.info("no sections: %s", e)
            return None
        data = res.data if isinstance(res.data, dict) else {}
        got = parse(data.get("sections"))
        if got:
            got["states"] = data.get("states") or []   # taken off by `take_places`, checked by code there
            return got
        prompt += '\n\nThat answer used no listed section. Use only the keys above, like "life/health".'
    return {}


def for_payload(router: Router | None, payload: dict) -> dict | None:
    """Sections from a published or about-to-publish payload: its headline, lead and best statements."""
    from .narrative import ordered_items
    paras = (payload.get("narrative") or {}).get("paragraphs") or [[]]
    lead = " ".join(x.get("text") or "" for x in paras[0]) if paras else ""
    items = [i for i in ordered_items(payload) if (i.get("role") or "core") == "core"]
    items.sort(key=lambda i: -(i.get("n_sources") or 0))
    return classify(router, payload.get("headline") or "", lead, [i["text"] for i in items if i.get("text")])


def take_places(cat: dict | None, payload: dict) -> list[str] | None:
    """The states the model named, taken off the section record and kept only where the article names them
    (places.confirm). None when the model was not asked."""
    if cat is None:
        return None
    from .places import article_text, confirm
    return confirm(cat.pop("states", []) or [], article_text(payload))


def fill_live(store, router: Router, limit: int = 5) -> list[int]:
    """Live articles get the section question the desk asks today, up to `limit` per run: those published before
    sections existed (no record), then those whose record is from the earlier tree (no "v"; mapped by `normalize`
    until asked, so they show in the right place meanwhile and gain their third level here). Only the section is
    changed: the article's text, headline and colours are untouched; an old record keeps its places and people."""
    from .db import published, select, update
    from sqlalchemy import text as sql_text
    done: list[int] = []
    pg = store.engine.dialect.name == "postgresql"
    q = select(published.c.story_id, published.c.payload_en, published.c.payload_hi)
    if pg:
        q = q.where(sql_text("(payload_en -> 'category' IS NULL OR payload_en -> 'category' -> 'v' IS NULL)"))
    rows = store.rows(q.order_by(published.c.updated_at.desc()).limit(limit * 3 if pg else 10_000))
    rows.sort(key=lambda r: "category" in (r["payload_en"] or {}))      # none at all first
    for r in rows:
        if len(done) >= limit:
            break
        pe = dict(r["payload_en"] or {})
        old = pe.get("category")
        if isinstance(old, dict) and old.get("v") == VERSION:
            continue
        cat = for_payload(router, pe)
        if cat is None:
            break                          # the page models cannot be asked now: the next run tries again
        pl = take_places(cat, pe)
        ph = dict(r["payload_hi"] or {})
        if "category" not in pe:
            pe["places"] = ph["places"] = pl
            from .people import from_payload
            pe["people"] = ph["people"] = from_payload(pe)
            pe["category"] = cat or {"v": VERSION}   # asked, no section: kept so it is not asked again
        else:                              # an earlier tree's record: the new answer, else the mapped one
            pe["category"] = cat or normalize(old) or {"v": VERSION}
        ph["category"] = pe["category"]
        store.exec(update(published).where(published.c.story_id == r["story_id"]).values(payload_en=pe, payload_hi=ph))
        done.append(r["story_id"])
    return done


def fill_places(store, router: Router, limit: int = 5) -> list[int]:
    """Live articles published before places existed (Oct 9 2026) get theirs, and their people (by code). The
    section question is asked again for the states only; the article's sections, text and colours are untouched."""
    from .db import published, select, update
    from .people import from_payload
    from sqlalchemy import text as sql_text
    done: list[int] = []
    pg = store.engine.dialect.name == "postgresql"
    q = select(published.c.story_id, published.c.payload_en, published.c.payload_hi)
    if pg:
        q = q.where(sql_text("payload_en -> 'places' IS NULL"))
    for r in store.rows(q.order_by(published.c.updated_at.desc()).limit(limit * 4 if pg else 10_000)):
        if len(done) >= limit:
            break
        pe = dict(r["payload_en"] or {})
        if "places" in pe:
            continue
        cat = for_payload(router, pe)
        if cat is None:
            break                          # the page models cannot be asked now
        pl = take_places(cat, pe)
        ppl = from_payload(pe)
        ph = dict(r["payload_hi"] or {})
        pe["places"] = ph["places"] = pl
        pe["people"] = ph["people"] = ppl
        store.exec(update(published).where(published.c.story_id == r["story_id"]).values(payload_en=pe, payload_hi=ph))
        done.append(r["story_id"])
    return done

"""Shadow run of the entity table (nishpaksh/entities.py) over every live article: what it would change against the
current speaker keys (`voice.speaker_key`) and the current shortening (`style.people`). Read-only, no model; the
summary goes to `diagnostics` (kind 'entities_shadow'). Run: workflow `audit`, tool `entities_shadow`.

How to read it (adoption rule: replace the old code only when this wins on stored data):
  keys.split      stories where one old key covered 2+ people the table keeps apart (the Banerjee / Singh case)
  keys.merged     stories where 2+ old keys are one person to the table (check `examples`: right or wrong?)
  short.gained    full names the table would shorten and `style.people` does not (the 49% of articles repeating a name)
  short.lost      full names `style.people` shortens and the table would not (each one is a possible regression: read them)
  short.review    gained names whose only evidence is weak (age / passive / apposition): are they people?"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter

from sqlalchemy import text as sql

from ..config import database_url
from ..db import Store, published, select
from ..editions import _all_items

log = logging.getLogger(__name__)
EXAMPLES = 40


def story_text(payload: dict) -> tuple[str, list[str], list[str]]:
    paras = (payload.get("narrative") or {}).get("paragraphs") or []
    text = " ".join(s.get("text", "") for p in paras for s in p)
    items = _all_items(payload)
    speakers = sorted({str(i["speaker"]) for i in items if i.get("speaker")})
    sources = [str(i.get("text") or "") for i in items]
    return text, speakers, sources


def compare(payload: dict) -> dict:
    """One article: old against new. Pure function of the payload (tested)."""
    from .. import style, voice
    from ..entities import EntityTable, parse
    text, speakers, sources = story_text(payload)
    t = EntityTable()
    for sp in speakers:
        t.add(sp, "speaker", text)
    t.add_text(" ".join([text, *sources]))
    t.build()

    out: dict = {"speakers": len(speakers)}
    # persons only: a body ("Ministry of External Affairs") is not this table's business and made noise in the first run
    old = {sp: voice.speaker_key(sp) for sp in speakers if not voice.is_body(sp)
           and t.entity(sp) is not None and t.entity(sp).person}
    new = {sp: (t.entity(sp).id if t.entity(sp) is not None and t.entity(sp).person else None) for sp in old}
    split, merged = [], []
    by_old: dict[str, set] = {}
    by_new: dict[int, set] = {}
    for sp in old:
        by_old.setdefault(old[sp], set()).add(new[sp] if new[sp] is not None else ("x", sp))
        if new[sp] is not None:
            by_new.setdefault(new[sp], set()).add(old[sp])
    for k, ids in by_old.items():
        if len(ids) > 1:
            split.append({"old_key": k, "people": sorted(sp for sp in old if old[sp] == k)})
    for i, ks in by_new.items():
        if len(ks) > 1:
            merged.append({"old_keys": sorted(ks), "names": sorted(sp for sp in old if new[sp] == i)})
    out["split"], out["merged"] = split, merged

    o = style._people_old(" ".join([text, *sources]), speakers)
    n = t.shortenable()
    out["old_short"], out["new_short"] = len(o), len(n)
    out["gained"] = sorted(set(n) - set(o))
    # the old code kept the title in the name ("Student Jasim Ali"); a name is lost only if its bare name is not shortened too
    out["lost"] = sorted(nm for nm in set(o) - set(n) if parse(nm).text not in n)
    why_lost = {}
    for name in out["lost"]:
        e = t.entity(name)
        if e is None or not e.person:
            why_lost[name] = "not a person to the table" + (f" (kind {parse(name).kind}, why {sorted(e.why) if e else '-'})")
        elif e.ambiguous:
            why_lost[name] = "ambiguous"
        elif len(e.fullest.tokens) < 2:
            why_lost[name] = "one word"
        else:
            sk = voice_key = None
            from ..entities import _tok_key
            sk = _tok_key(e.surname)
            clash = [x.name for x in t.entities if x is not e and sk in {k for m in x.mentions for k in m.keys}]
            why_lost[name] = "surname is a word of " + ", ".join(clash[:3]) if clash else "other"
    out["lost_why"] = why_lost
    weak = []
    for name in out["gained"]:
        e = t.entity(name)
        if e is not None and not ({"title", "speaker", "speech"} & e.why) and not any(m.titled for m in e.mentions):
            weak.append({"name": name, "why": sorted(e.why)})
    out["weak"] = weak
    # how often the article writes the name in full: what shortening would save
    out["repeats_gained"] = sum(max(0, len(re.findall(rf"(?<![\w-]){re.escape(nm)}(?![\w-])", text)) - 1) for nm in out["gained"])
    out["persons"] = [{"name": e.name, "why": sorted(e.why), "ambiguous": e.ambiguous} for e in t.persons()]
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = Store(database_url())
    rows = store.rows(select(published.c.story_id, published.c.payload_en))
    agg = Counter()
    ex: dict[str, list] = {"split": [], "merged": [], "gained": [], "lost": [], "weak": []}
    for r in rows:
        try:
            c = compare(r["payload_en"] or {})
        except Exception as e:  # noqa: BLE001 - one article must not stop the report
            agg["errors"] += 1
            log.warning("story %s: %s", r["story_id"], str(e)[:200])
            continue
        agg["stories"] += 1
        agg["with_speakers"] += bool(c["speakers"])
        agg["split_stories"] += bool(c["split"])
        agg["merged_stories"] += bool(c["merged"])
        agg["gained_names"] += len(c["gained"])
        agg["lost_names"] += len(c["lost"])
        agg["stories_gaining"] += bool(c["gained"])
        agg["repeats_gained"] += c["repeats_gained"]
        for k in ("split", "merged"):
            for x in c[k]:
                ex[k].append({"story": r["story_id"], **x})
        for nm in c["gained"]:
            ex["gained"].append({"story": r["story_id"], "name": nm})
        for nm in c["lost"]:
            ex["lost"].append({"story": r["story_id"], "name": nm, "why": c["lost_why"].get(nm)})
        for w in c["weak"]:
            ex["weak"].append({"story": r["story_id"], **w})
    report = {"counts": dict(agg), "examples": {k: v[:EXAMPLES] for k, v in ex.items()}}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    with store.readers.engine.begin() as c:
        c.execute(sql("insert into diagnostics (kind, report) values ('entities_shadow', :r)"),
                  {"r": json.dumps(report, ensure_ascii=False)})


if __name__ == "__main__":
    main()

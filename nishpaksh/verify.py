"""Stage 7: verdicts.

Most verdicts are arithmetic over who says what (code):
  corroborated - see established(): 3+ independent outlets, 2+ independent origins, a checkable
                 fact, nobody denies it, standing 6+ hours (before that: developing)
  disputed     - someone asserts it and someone denies or contradicts it
  unverified   - only one source, or only one perspective, says it
Two verdicts need outside evidence and two independent models agreeing:
  false        - primary evidence (FIR, court record, official data, video) contradicts it
  confirmed    - primary evidence supports it
Any disagreement between the two models leaves the code verdict in place.
This is the false-positive rule: we would rather leave a false claim "unverified"
than call a true claim false.
"""
from __future__ import annotations

import collections
import re

import datetime as dt
import logging
from collections import defaultdict

from .config import EVIDENCE_WEIGHT, PRIMARY_EVIDENCE, SETTINGS
from .db import Store, articles, canonical, claims, select, stories, update, utcnow
from .router import QuotaExhausted, Router

log = logging.getLogger(__name__)

GROUNDED_PROMPT = """Search the web for PRIMARY evidence about this statement from an Indian news story.

Story: {signature}
Statement: "{text}"

Look for: FIR details, court orders or filings, official data, verifiable video, and named officials'
on-record statements. Report what each source actually says about the statement, one line per source,
with its URL. If you find nothing relevant, reply exactly: NONE"""

JUDGE_PROMPT = """You are checking one statement from a news story against evidence. Be strict.

Story: {signature}
Statement: "{text}"

What news reports say about it:
{reports}

Evidence found by web search (may be empty):
{evidence}

Decide:
- "contradicted": primary evidence shows the statement is untrue.
- "supported": primary evidence shows the statement is true.
- "insufficient": anything else. Outlets disagreeing with each other is NOT evidence either way.
Primary evidence means an FIR, a court record, official data, or verifiable video. Statements by police,
officials or politicians are claims, not primary evidence: use basis "official_statement" for them.

Reply with JSON only:
{{"verdict": "contradicted|supported|insufficient",
  "basis": "fir|court_record|official_data|video|official_statement|none",
  "reason": "at most 30 words",
  "evidence_urls": ["..."]}}"""


RETRY_HOURS = 3
STATS = collections.Counter()      # E15: statements held back by a defaulted stance


def relation_text(rel: dict, texts: dict[int, str]) -> str:
    """The two statements of a relation as one sentence, or "" when an endpoint is missing (E13: never a "?" in a page).
    A clause's first word is lower-cased unless the parse says it starts a name; an acronym is never lower-cased."""
    ta, tb = texts.get(rel.get("from")), texts.get(rel.get("to"))
    if not ta or not tb:
        return ""
    a, b = ta.rstrip(". "), tb.rstrip(". ")

    def lower(x: str) -> str:
        """The clause's first word in lower case, unless it starts a name (NER) or is an acronym / has inner capitals."""
        if not x or x[:2].isupper() or any(c.isupper() for c in x.split(" ")[0][1:]):
            return x
        try:
            from . import nlp
            if any(e.start == 0 for e in nlp.ents(x)):
                return x
        except Exception:  # noqa: BLE001
            pass
        return x[:1].lower() + x[1:]
    if rel.get("type") == "caused":
        return f"{b} because {lower(a)}."
    return f"{a}, and after that {lower(b)}."


def _story_context(store: Store, story_id: int):
    story = store.one(select(stories).where(stories.c.id == story_id))
    analysis = story["analysis"] or {}
    agroup = {int(k): v for k, v in (analysis.get("article_group") or {}).items()}
    gpersp = {g: info.get("perspective") for g, info in (analysis.get("groups") or {}).items()}
    arts = {a["id"]: a for a in store.rows(select(articles.c.id, articles.c.outlet, articles.c.url)
                                            .where(articles.c.story_id == story_id))}
    canon = {c["id"]: c for c in store.rows(select(canonical).where(canonical.c.story_id == story_id))}
    members = defaultdict(list)
    for r in store.rows(select(claims).where(claims.c.story_id == story_id, claims.c.canonical_id.is_not(None))):
        members[r["canonical_id"]].append(r)
    return story, agroup, gpersp, arts, canon, members


def support_summary(cid: int, members, agroup, gpersp) -> dict:
    sup, deny = {}, {}
    for r in members.get(cid, []):
        g = agroup.get(r["article_id"])
        if g is None:
            continue
        w = EVIDENCE_WEIGHT.get(r["evidence"], 1.0) * (0.5 if r["stance"] == "attributes" else 1.0)
        target = deny if r["stance"] == "denies" else sup
        target[g] = max(target.get(g, 0.0), w)
    from .wire import is_state
    return {
        # state media are their government speaking (origins), never an outlet: not counted as one
        "support_groups": sorted(g for g in sup if not is_state(g)), "deny_groups": sorted(deny),
        "support_weight": round(sum(sup.values()), 2),
        "support_perspectives": sorted({gpersp.get(g) for g in sup if gpersp.get(g)}),
        "deny_perspectives": sorted({gpersp.get(g) for g in deny if gpersp.get(g)}),
        "n_articles": len({r["article_id"] for r in members.get(cid, [])}),
    }


def meets_rule(c: dict, s: dict, mode: str | None) -> bool:
    """Everything the established rule asks for except time. The caller has already checked that
    nobody denies or contradicts the statement."""
    o = c.get("origins") or {}
    if not (o.get("outlets", 0) >= SETTINGS.established_min_outlets
            and o.get("n_origins", 0) >= SETTINGS.established_min_origins
            and c.get("checkable") is True):
        return False
    return not (mode == "global" and len(s["support_perspectives"]) < 2)


def established(c: dict, s: dict, mode: str | None, now=None) -> str | None:
    """'corroborated', 'developing', or None (not established). The rule, all of which must hold:
    3+ independent outlets (owner groups, wire copies merged) that were actually read report it;
    it traces to 2+ independent origins (origins.py; unattributed repetition never counts);
    nobody denies or contradicts it (checked by the caller); it is a checkable fact, not a
    characterisation; and once perspectives exist, it is reported across 2+ of them.
    It must then STAND for 6 hours, counted from the moment all of that first held (not from the
    first report): until then it is only 'developing'."""
    if not meets_rule(c, s, mode):
        return None
    met = (c.get("origins") or {}).get("met_at")
    now = now or utcnow()
    try:
        age_h = (now - dt.datetime.fromisoformat(met)).total_seconds() / 3600 if met else 0
    except ValueError:
        age_h = 0
    return "corroborated" if age_h >= SETTINGS.established_after_hours else "developing"


def base_verdicts(store: Store, story_id: int) -> int:
    """Recompute the code verdicts; returns how many changed (the page is rebuilt if any did)."""
    story, agroup, gpersp, arts, canon, members = _story_context(store, story_id)
    mode = (story["analysis"] or {}).get("mode")
    # the reports do not agree WHO did it (a different company or person named for the same fact):
    # whatever else holds, that statement is not established
    name_conf = set((story["analysis"] or {}).get("name_conflicts") or {})
    # a possible contradiction nobody could settle (consolidate.py): not shown as a dispute, but not
    # established either
    name_conf |= {str(x) for x in (story["analysis"] or {}).get("doubtful_conflicts") or []}
    now = utcnow()
    changed = 0
    # the same fact on another page of the thread (threads.py, owner Oct 16 2026): one fact, one colour
    from .threads import pooled_origins, twin_rows
    twins = twin_rows(store, canon)
    from . import truth                  # B25: belief from who supports and denies; an extra gate that can only hold back
    sums = {cid: support_summary(cid, members, agroup, gpersp) for cid in canon}
    belief = truth.beliefs({cid: set(x["support_groups"]) for cid, x in sums.items()},
                           {cid: set(x["deny_groups"]) for cid, x in sums.items()})
    for cid, c in canon.items():
        s = sums[cid]
        conflict_live = any(support_summary(o, members, agroup, gpersp)["support_groups"]
                            for o in (c["conflicts"] or []) if o in canon)
        contested = bool(s["deny_groups"] and s["support_groups"] or conflict_live)
        mine = [twins[t] for t in ((c.get("rel") or {}).get("twins") or []) if t in twins]
        judged_c = c                    # what the rule is judged on: with the twins' evidence (stored: its own only)
        if mine:
            contested = contested or any(t["verdict"] in ("disputed", "false") for t in mine)
            pooled = pooled_origins(c.get("origins"), mine)
            if pooled is not None:
                judged_c = dict(c, origins=pooled,
                                checkable=c.get("checkable") if c.get("checkable") is not None
                                else next((t["checkable"] for t in mine if t["checkable"] is not None), None))
        # the 6-hour clock starts when the rule is first met, and restarts if it stops being met
        o = dict(c.get("origins") or {})
        meets = (not contested and bool(s["support_groups"]) and meets_rule(judged_c, s, mode)
                 and str(cid) not in name_conf and belief.get(cid, 0.0) >= truth.BELIEF_MIN)
        if meets and not o.get("met_at"):
            o["met_at"] = now.isoformat(timespec="minutes")
        elif not meets and o.get("met_at"):
            # E12: one failing run is not enough to restart the 6-hour clock (a late denial, a flickering origin); the
            # second in a row clears it, and the reason is kept
            o["miss"] = int(o.get("miss") or 0) + 1
            o["miss_reason"] = ("contested" if contested else "no support" if not s["support_groups"]
                                else "name conflict" if str(cid) in name_conf else "belief" if belief.get(cid, 0.0) < truth.BELIEF_MIN
                                else "rule")
            if o["miss"] >= 2:
                o.pop("met_at")
                o.pop("miss")
        elif meets and o.get("miss"):
            o.pop("miss")
            o.pop("miss_reason", None)
        if o != (c.get("origins") or {}) and c.get("origins") is not None:
            store.exec(update(canonical).where(canonical.c.id == cid).values(origins=o))
            c = dict(c, origins=o)
        if contested:
            v = "disputed"
        elif not s["support_groups"]:
            v = "unverified"  # only denials: the denial itself is the claim on record
        elif str(cid) in name_conf:
            v = "unverified"  # the reports name different actors: not established, not even developing
        else:
            v = established(dict(judged_c, origins=dict(judged_c.get("origins") or {}, met_at=o.get("met_at"))),
                            s, mode, now) or "unverified"
        # E15: a statement any member of which had its stance defaulted (the model's value was missing or invalid) is
        # never "corroborated": it stays "developing" at most
        if v == "corroborated" and any((r.get("rel") or {}).get("stance_defaulted") for r in members.get(cid, [])):
            v = "developing"
            STATS["held_defaulted_stance"] += 1
        # E11: a verdict set by evidence ("false", "confirmed") is never overwritten by arithmetic; arithmetic may only
        # make a "confirmed" statement "disputed" (more cautious); "false" by primary evidence stands. (Re-judging after the story grew is verify_story's job, which sets the verdict itself.)
        keep = c["verdict"] == "false" or (c["verdict"] == "confirmed" and v != "disputed")
        if not keep and v != c["verdict"]:
            store.exec(update(canonical).where(canonical.c.id == cid).values(verdict=v))
            changed += 1
    return changed


def _reports(cid: int, canon, members, arts) -> str:
    lines = []
    for oid in [cid] + list(canon[cid]["conflicts"] or []):
        if oid not in canon:
            continue
        for r in members.get(oid, [])[:12]:
            outlet = arts.get(r["article_id"], {}).get("outlet", "?")
            what = canon[oid]["text"] if oid == cid else f'(contradicting statement) "{canon[oid]["text"]}"'
            lines.append(f"- {outlet}: {r['stance']} {what}; source given: {r['attributed_to']}; "
                         f"evidence cited: {r['evidence']}")
    return "\n".join(lines) or "- none"


def verify_story(store: Store, router: Router, story_id: int, budget: dict) -> int:
    story, agroup, gpersp, arts, canon, members = _story_context(store, story_id)
    texts = {cid: c["text"] for cid, c in canon.items()}
    cands = []
    for cid, c in canon.items():
        n = len({r["article_id"] for r in members.get(cid, [])})
        checked_before = (c["detail"] or {}).get("checked")
        if c["verdict"] in ("corroborated", "developing"):
            # E11: a statement already judged is judged again once the story has grown by more than 2 articles
            if not (checked_before and abs((c["checked_members"] or 0) - n) > 2):
                continue
        elif c["verdict"] not in ("disputed", "unverified"):
            continue
        if n < SETTINGS.min_articles_to_verify:
            continue
        if checked_before and abs((c["checked_members"] or 0) - n) <= 2:
            continue
        # E14: a statement tried without its second opinion waits (retry_after) and goes to the back of the line
        retry = (c["detail"] or {}).get("retry_after")
        if retry and retry > utcnow().isoformat(timespec="minutes"):
            continue
        cands.append((n, cid))
    # most-covered first, but the ones tried longest ago before the ones tried just now (rotation)
    cands.sort(key=lambda t: (((canon[t[1]]["detail"] or {}).get("tried") or ""), -t[0], -t[1]))
    checked = 0
    for n, cid in cands:
        if budget.get("judge", 0) <= 0:
            break
        c = canon[cid]
        text = relation_text(c["rel"], texts) if c["kind"] == "relation" else c["text"]
        evidence, web = "none found", []
        if budget.get("grounded", 0) > 0:
            try:
                res = router.call("grounded", GROUNDED_PROMPT.format(signature=story["signature"], text=text),
                                  json_out=False, grounded=True, max_output_tokens=1200)
                budget["grounded"] -= 1
                if res.text.strip() and res.text.strip().upper() != "NONE":
                    evidence, web = res.text.strip()[:3000], res.sources
            except QuotaExhausted:
                budget["grounded"] = 0
            except Exception as e:  # noqa: BLE001
                log.warning("grounded search failed: %s", e)
        prompt = JUDGE_PROMPT.format(signature=story["signature"], text=text,
                                     reports=_reports(cid, canon, members, arts), evidence=evidence)
        opinions = []
        for tier in ("judge", "second"):  # two model families must agree independently
            try:
                res = router.call(tier, prompt, json_out=True, max_output_tokens=600)
                d = res.data if isinstance(res.data, dict) else {}
                opinions.append({"model": res.model, "verdict": d.get("verdict"), "basis": d.get("basis"),
                                 "reason": str(d.get("reason") or "")[:300],
                                 "evidence_urls": [u for u in (d.get("evidence_urls") or []) if isinstance(u, str)][:5]})
                if tier == "judge":
                    budget["judge"] -= 1
            except QuotaExhausted:
                if tier == "judge":
                    budget["judge"] = 0
                break
            except Exception as e:  # noqa: BLE001
                log.warning("%s opinion failed: %s", tier, e)
                break
        if len(opinions) < 2:
            now_ = utcnow()
            store.exec(update(canonical).where(canonical.c.id == cid).values(detail={
                **(c["detail"] or {}), "tried": now_.isoformat(timespec="minutes"),
                "retry_after": (now_ + dt.timedelta(hours=RETRY_HOURS)).isoformat(timespec="minutes"),
                "missing": "second opinion" if opinions else "both opinions"}))
            if budget.get("judge", 0) <= 0:
                break
            continue
        a, b = opinions
        primary = a["basis"] in PRIMARY_EVIDENCE and b["basis"] in PRIMARY_EVIDENCE
        verdict = c["verdict"]
        from . import groundjudge       # B26: the passage must settle it by meaning too, not only two opinions
        if primary and a["verdict"] == b["verdict"] == "contradicted" and groundjudge.holds(text, evidence, web, "contradicted"):
            verdict = "false"
        elif primary and a["verdict"] == b["verdict"] == "supported" and groundjudge.holds(text, evidence, web, "supported"):
            verdict = "confirmed"
        detail = {"checked": True, "checked_at": utcnow().isoformat(timespec="minutes"),
                  "opinions": opinions, "web_sources": web[:8], "outcome": verdict}
        store.exec(update(canonical).where(canonical.c.id == cid)
                   .values(verdict=verdict, detail=detail, checked_members=n))
        checked += 1
    return checked

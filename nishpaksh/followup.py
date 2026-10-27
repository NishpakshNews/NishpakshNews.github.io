"""What a follow-up article is made of (owner, Oct 27 2026).

A story that develops a published one is judged and written like any other story, but only on what is NEW:

  1. `editions.judge_follow_up` says which of its statements the parent already told (and which line of the parent says it).
  2. `drop_told` leaves those out of the article. They are not written again; their evidence is shared with the parent's line
     as before (threads.save_links), so the same fact has one colour on every page. A statement that something else in the
     article leans on (a dispute, an answer, an old and a new figure) stays whatever the parent said.
  3. `choose_background` picks the few lines of the parent the article needs to be understood. There is no rule against
     repeating a parent line: some are needed for a coherent story (owner). Which ones is a small optimisation, the
     standard greedy for a monotone submodular objective (selection.greedy; within 1 - 1/e of the best choice, Nemhauser,
     Wolsey and Fisher 1978). A line is worth:
       - a fixed credit when the later reports restate it (they treat it as part of the story, yet it was dropped above);
       - the weight of each name of the new part that the lines chosen before it have not yet explained (weighted maximum
         coverage; a name every line has is the setting and weighs nothing: idf.py);
       - the closeness (embedding cosine above a floor) it brings to each new statement, counted only as far as the lines
         chosen before it do not already reach that statement (facility location: two near-identical lines add once).
     A line the article would only repeat, or contradict, is never offered: a near copy of a new statement, a line some
     new statement replaces (`updates`, the old toll), a line a kept statement already says.
     Untuned guesses, to read in the audit: RESTATED, ENTITY_WEIGHT, SERVICE_FLOOR, MIN_GAIN, REPEAT_SIM, BUDGET.
"""
from __future__ import annotations

import logging

import numpy as np

from . import embed, idf, selection

log = logging.getLogger(__name__)

BUDGET = 4                                         # lines of the parent offered to the writer (it was the first four)
RESTATED = 1.0                                     # credit for a line the later reports restate
ENTITY_WEIGHT = 0.5                                # credit per unit idf weight of a name of the new part the line explains
SERVICE_FLOOR = {"bi-encoder": 0.40, "tfidf": 0.15}    # cosine under which a line says nothing about a new statement
REPEAT_SIM = {"bi-encoder": 0.90, "tfidf": 0.60}   # cosine over which a line is a copy of a new statement
MIN_GAIN = 0.10                                    # a line that adds less than this to what is chosen is not offered


def partnered(i: dict) -> bool:
    """A statement other statements of the article lean on: disputed or false, a contradiction or answer with a partner,
    an old and a new figure, a line another is the detail of. Taking one out would leave its partner pointing at nothing."""
    return bool(i.get("verdict") in ("disputed", "false") or i.get("conflicts_with") or i.get("responds_to")
                or i.get("responded_by") or i.get("update_of") or i.get("updated_by") or i.get("adds_to"))


def drop_told(payload: dict, told: set[int]) -> list[int]:
    """Leave the statements the parent already told out of the payload. Returns the ids taken out."""
    gone: set[int] = set()
    seen: dict[int, dict] = {}
    for tier in payload.get("timeline") or []:
        for i in tier:
            seen[i["id"]] = i
    for k in ("undated", "established", "contested", "context"):
        for i in payload.get(k) or []:
            seen[i["id"]] = i
    for sid in told:
        i = seen.get(sid)
        if i is not None and not partnered(i):
            gone.add(sid)
    if not gone:
        return []
    payload["timeline"] = [[i for i in tier if i["id"] not in gone] for tier in payload.get("timeline") or []]
    for k in ("undated", "established", "contested", "context"):
        payload[k] = [i for i in payload.get(k) or [] if i["id"] not in gone]
    return sorted(gone)


def candidates(parents: dict[int, dict], order: list[int]) -> list[dict]:
    """The parents' lines that may be offered as background, in the parents' own order, as background items: the
    established lines of each page (its timeline and established lists), else its best-supported reports, still as reports."""
    out, seen = [], set()
    for pid in order:
        pe = (parents.get(pid) or {}).get("payload_en") or {}
        est = [i for tier in pe.get("timeline") or [] for i in tier] + list(pe.get("established") or [])
        if not est:
            est = sorted(pe.get("contested") or [], key=lambda i: -i.get("n_articles", 0))
        for i in est:
            if i.get("kind") == "relation" or i.get("id") is None or not i.get("text") or i["id"] in seen:
                continue
            seen.add(i["id"])
            out.append(dict(i, id=-int(i["id"]), kind="background", parent=pid))
    return out


def choose_background(cands: list[dict], kept: list[dict], restated: set[int], excluded: set[int],
                      budget: int = BUDGET) -> tuple[list[dict], list[dict]]:
    """(the lines chosen, in the parents' order; what each was chosen for). `kept`: the statements the article will tell;
    `restated`: ids of parent lines the later reports restate; `excluded`: ids of parent lines never offered."""
    from .threads import _names
    cands = [c for c in cands if -c["id"] not in excluded]
    kept_texts = [i["text"] for i in kept if i.get("text")]
    if not cands or not kept_texts:
        return [], []
    texts = [c["text"] for c in cands]
    sim, how = None, "bi-encoder"
    try:
        v, how = embed.vectors(kept_texts + texts)
        sim = v[len(kept_texts):] @ v[:len(kept_texts)].T          # candidates x kept statements
    except Exception as e:  # noqa: BLE001 - names and restatements still decide
        log.warning("followup: lines not scored by meaning (%s)", str(e)[:100])
    if sim is not None:                      # a copy of a new statement says nothing the article does not
        keep = [k for k in range(len(cands)) if float(sim[k].max()) < REPEAT_SIM[how]]
        cands, sim = [cands[k] for k in keep], sim[keep]
        texts = [texts[k] for k in keep]
        if not cands:
            return [], []
    floor = SERVICE_FLOOR[how]
    served = np.maximum(sim - floor, 0.0) if sim is not None else np.zeros((len(cands), 1))
    weights = idf.Weights(kept_texts + texts)
    wanted = set().union(*(_names(t) for t in kept_texts))
    cand_names = [_names(t) & wanted for t in texts]
    m = max(1, served.shape[1])

    def gain(k: int, chosen: list[int]) -> float:
        g = RESTATED if -cands[k]["id"] in restated else 0.0
        have = set().union(*(cand_names[c] for c in chosen)) if chosen else set()
        g += ENTITY_WEIGHT * sum(weights.w(e) for e in cand_names[k] - have)
        cur = served[chosen].max(axis=0) if chosen else np.zeros(served.shape[1])
        g += float(np.maximum(served[k] - cur, 0.0).sum()) / m
        return g if g >= MIN_GAIN else 0.0

    picked = selection.greedy(list(range(len(cands))), budget, lambda k: 1.0, gain)
    trace, have = [], set()
    for k in picked:                                           # why each was chosen, in the order chosen
        trace.append({"id": -cands[k]["id"], "parent": cands[k]["parent"], "restated": -cands[k]["id"] in restated,
                      "names": sorted(cand_names[k] - have), "reach": round(float(served[k].max()), 2)})
        have |= cand_names[k]
    return [cands[k] for k in sorted(picked)], trace


def apply(payload: dict, fu) -> dict:
    """Make the payload of a judged follow-up: leave out what the parent told, offer the parent lines it needs.
    Returns the record for the story's dossier."""
    told = set(fu.told)
    dropped = drop_told(payload, told)
    judged = fu.judged
    restated = {judged[x]["same_as"] for x in dropped if judged[x].get("same_as") is not None}
    # never offered: a line something new replaces (the old toll), a line a statement kept in the article already says
    excluded = {judged[x]["updates"] for x in fu.new if judged[x].get("updates") is not None}
    excluded |= {judged[x]["same_as"] for x in told if x not in set(dropped) and judged[x].get("same_as") is not None}
    from .narrative import ordered_items
    kept = [i for i in ordered_items(payload) if i.get("kind") != "background"]
    order = [x["story_id"] for x in payload.get("parents") or [] if x["story_id"] in fu.parents]
    trace: list[dict] = []
    try:
        lines, trace = choose_background(candidates(fu.parents, order), kept, restated, excluded)
        payload["background"] = lines
    except Exception as e:  # noqa: BLE001 - the lines the page was built with (the parents' first four) stand
        log.warning("followup: parent lines not chosen (%s); the default lines stand", str(e)[:120])
    return {"parent": fu.parent_id, "new": len(fu.new), "told": len(told), "dropped": dropped, "kept_told": sorted(told - set(dropped)),
            "background": trace}

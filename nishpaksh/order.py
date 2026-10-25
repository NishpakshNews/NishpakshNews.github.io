"""Chronological order of statements as a graph (B5, B15): a topological sort, not a sort by one key.

Edges (an earlier statement points at a later one), strongest first:
  1. time: the first one's interval ends before the second's begins (days; a clock time is not required);
  2. a stated relation (extraction's "after" / "caused" between two statements);
  3. event type: on the SAME day, with no clock time to say, a statement whose event is earlier in the usual course
     (events.py: the average place of its verb in the dated stories we have stored; detained before released) comes first.
Statements with no time and no edge keep the order they were given, after those that are placed. A cycle (two sources
disagreeing on order) loses its weakest edge instead of failing. networkx does the sorting.
"""
from __future__ import annotations

import datetime as dt

import networkx as nx

from . import events


def _iv(i: dict) -> tuple[dt.datetime, dt.datetime] | None:
    t = i.get("time") or {}
    try:
        s = dt.datetime.fromisoformat(t["start"]) if t.get("start") else None
        e = dt.datetime.fromisoformat(t["end"]) if t.get("end") else s
    except (ValueError, TypeError, KeyError):
        return None
    return (s, e or s) if s else None


def _clock(i: dict) -> bool:
    """Does the statement carry a time of day (so the clock, not the stage, orders it within its day)?"""
    t = i.get("time") or {}
    return (t.get("precision") or "") in ("minute", "hour")


def chronological(items: list[dict], relations: list[tuple[int, int]] | None = None) -> list[dict]:
    """`items` in the order the events happened. Items are dicts with id, text, time{start,end,precision}."""
    if len(items) < 2:
        return list(items)
    pos = {i["id"]: n for n, i in enumerate(items)}
    by = {i["id"]: i for i in items}
    iv = {i["id"]: _iv(i) for i in items}
    st = {i["id"]: events.rank_of(i.get("text") or "") for i in items}
    G = nx.DiGraph()
    G.add_nodes_from(by)
    ids = list(by)
    for a in ids:
        for b in ids:
            if a == b:
                continue
            ia, ib = iv[a], iv[b]
            if ia and ib and ia[1].date() < ib[0].date():
                G.add_edge(a, b, kind="time")
    for a, b in relations or ():
        if a in by and b in by and a != b and not G.has_edge(a, b) and not G.has_edge(b, a):
            G.add_edge(a, b, kind="relation")
    for n, a in enumerate(ids):                          # same day, no clock: the usual course of events decides
        for b in ids[n + 1:]:
            ia, ib = iv[a], iv[b]
            if not (ia and ib) or ia[0].date() != ib[0].date() or _clock(by[a]) or _clock(by[b]):
                continue
            first = events.earlier(st[a], st[b])
            if first is not None and not G.has_edge(a, b) and not G.has_edge(b, a):
                x, y = (a, b) if first else (b, a)
                G.add_edge(x, y, kind="stage")
    weight = {"time": 3, "relation": 2, "stage": 1}
    while True:                                          # a cycle loses its weakest edge
        try:
            cyc = nx.find_cycle(G)
        except nx.NetworkXNoCycle:
            break
        u, v = min(((u, v) for u, v, *_ in cyc), key=lambda e: weight[G.edges[e]["kind"]])
        G.remove_edge(u, v)

    def key(n):                                          # dated first by their time, then undated in the given order
        s = iv[n][0] if iv[n] else dt.datetime.max
        return (s, pos[n])
    return [by[n] for n in nx.lexicographical_topological_sort(G, key=key)]

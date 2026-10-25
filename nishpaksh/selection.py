"""Choosing what to spend a budget on (S4, S6): greedy maximum coverage.

Picking k items so that together they cover the most is NP-hard, but when the value of an item can only shrink as others are
already chosen (submodular), picking the best marginal gain per cost, again and again, is within 1 - 1/e of the best
possible choice (Nemhauser, Wolsey and Fisher 1978; Khuller, Moss and Naor 1999 for a budget). Used for the pages a story is
READ from (`extract.select_for_extraction`: a page that adds words nobody chosen has) and the pages Tavily is paid to fetch
(`extract.read_blocked_pages`: a page that brings its story nearer the publishing rule). Ties keep the order given, so
the caller's own order (newest first) is the tie-break and nothing here is random.
"""
from __future__ import annotations

from typing import Callable, Sequence, TypeVar

T = TypeVar("T")


def greedy(items: Sequence[T], budget: float, cost: Callable[[T], float],
           gain: Callable[[T, list[T]], float]) -> list[T]:
    """The items chosen, in the order chosen. `gain(item, chosen_so_far)` is the item's value given what is chosen."""
    left = list(items)
    chosen: list[T] = []
    spent = 0.0
    while left:
        best, best_score = None, 0.0
        for k, it in enumerate(left):
            c = max(float(cost(it)), 1e-9)
            if spent + c > budget + 1e-9:
                continue
            score = gain(it, chosen) / c
            if score > best_score + 1e-12:
                best, best_score = k, score
        if best is None:
            break
        it = left.pop(best)
        spent += max(float(cost(it)), 1e-9)
        chosen.append(it)
    return chosen

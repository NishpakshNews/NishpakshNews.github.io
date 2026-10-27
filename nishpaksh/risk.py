"""What a headline is about, read by the local entailment model, not by word lists (owner, Oct 27 2026).

The express lane (express.py) takes stories from ONE or TWO outlets, so it must keep out what is dangerous on so little
evidence: crime and accusation, a government acting, share prices and tips, rumour, celebrity gossip, service pieces. Until
now that was ~300 hand-written words ("court", "alleged", "ED", "May"): a word says nothing of meaning ("Federation moves
court against ban" and "Sindhu stays on court" share a word), each failure was patched with another entry (`allow_phrases`),
and Hindi was matched by fragments. The rebuild's rule is no word lists, so the question moved to the model that already
decides "does this sentence say that?" (nli.py: multilingual, local, no quota, the same answer every time).

A CONCERN is a short definition sentence in config/express.yaml (`concerns:`; several per kind, because a sentence that joins
several ideas is read poorly). The headline and its opening words are the premise, the definition the hypothesis. A concern
fires when P(entailment) reaches `concern_min`. Which concerns apply to a lane is the `apply:` map (a share-price move is the
news in markets, "a rally" a tennis word).

Rules that keep it safe:
  - A pair the model could not read is never "fine": the headline is UNREAD, the caller leaves it undecided and asks again on
    the next run (as every tri-state in this code base: None = could not ask, never "no").
  - One concern that fires is enough to exclude, even if another pair could not be read.
  - The reason is `concern:definition` (e.g. "harm:crime"), so the ledger shows which sentence does the work.
  - Pure function of its inputs (`reasons`): express.py passes the configuration and the texts; nothing is stored here.

Untuned: `concern_min` and the sentences. `python -m nishpaksh.express_replay --audit` shows on stored headlines what each
sentence catches and where it disagrees with the verdicts the word lists gave."""
from __future__ import annotations

import logging

from . import nli

log = logging.getLogger("nishpaksh.risk")

DEFAULT_MIN = 0.5            # entailment probability that counts as "the headline says this"
LEAD_CHARS = 300             # how much of the opening is read with the headline (as the word lists did)


class _Unread:
    """The headline could not be read by the model (no model, a failed batch): neither fine nor excluded."""
    def __repr__(self) -> str:
        return "UNREAD"

    def __bool__(self) -> bool:
        return False


UNREAD = _Unread()


def text_of(title: str | None, lead: str | None = "") -> str:
    """The premise: the headline, then the opening words."""
    return f"{(title or '').strip()}. {(lead or '')[:LEAD_CHARS].strip()}".strip(" .") if (title or lead) else ""


def applies(apply_: dict, concern: str, lane: str | None) -> bool:
    """Does this concern count in this lane? With no lane known only the concerns that apply to every lane do."""
    where = apply_.get(concern, "all")
    return where == "all" or (lane is not None and lane in set(where or []))


def pairs_for(definitions: dict[str, dict[str, str]], apply_: dict, lane: str | None) -> list[tuple[str, str, str]]:
    """[(concern, key, sentence)] that count in this lane, in the configuration's order."""
    return [(c, k, s) for c, keys in (definitions or {}).items() if applies(apply_, c, lane)
            for k, s in (keys or {}).items() if s]


def scores(texts: list[str], lanes: list[str | None], definitions: dict[str, dict[str, str]], apply_: dict) -> list[dict]:
    """One dict per text: {"concern:key": P(entailment) or None (not read)} for the definitions that count in its lane.
    The model is asked once for all pairs (batched, cached by nli.py)."""
    n = len(texts)
    wanted = [pairs_for(definitions, apply_, lanes[i]) if texts[i] else [] for i in range(n)]
    asks: dict[tuple[str, str], None] = {}
    for i in range(n):
        for _c, _k, sentence in wanted[i]:
            asks[(texts[i], sentence)] = None
    keys = list(asks)
    got: dict[tuple[str, str], tuple | None] = {}
    if keys:
        try:
            got = dict(zip(keys, nli.predict(keys)))
        except Exception as e:  # noqa: BLE001 - a model that fails leaves the headlines undecided, never passed
            log.warning("risk: model failed (%s)", str(e)[:120])
    return [{f"{c}:{k}": (got[(texts[i], sentence)][0] if got.get((texts[i], sentence)) is not None else None)
             for c, k, sentence in wanted[i]} for i in range(n)]


def decide(one: dict, bar: float = DEFAULT_MIN):
    """"concern:key" of the strongest definition at or over the bar, else UNREAD if any definition was not read, else None."""
    fired = [(p, name) for name, p in one.items() if p is not None and p >= bar]
    if fired:
        return max(fired)[1]
    return UNREAD if any(p is None for p in one.values()) else None


def reasons(texts: list[str], lanes: list[str | None], definitions: dict[str, dict[str, str]], apply_: dict,
            bar: float = DEFAULT_MIN) -> list:
    """One entry per text: "concern:key" (the strongest definition that fired), None (read and fine), or UNREAD.
    `lanes[i]` is the lane text i is judged for (None: only the concerns for every lane)."""
    return [decide(one, bar) for one in scores(texts, lanes, definitions, apply_)]

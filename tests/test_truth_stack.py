"""B25 truth discovery, B26 evidence gate, B28 copy detection, B29 check-worthiness, B30 interval groups, B31 concepts."""
import numpy as np
import pytest

from nishpaksh import checkworthy, concepts, embed, groundjudge, independence, nli, positions, truth


def test_belief_rises_with_independent_supporters_and_falls_with_a_denier():
    b = truth.beliefs({1: {"a", "b", "c"}, 2: {"a"}}, {})
    assert b[1] >= truth.BELIEF_MIN > b[2]
    assert truth.beliefs({1: {"a", "b", "c"}}, {1: {"d"}})[1] < truth.BELIEF_MIN


def test_a_source_that_backs_doubted_statements_is_trusted_less():
    sup = {1: {"a", "b", "c"}, 2: {"x"}, 3: {"x"}}
    deny = {2: {"a", "b", "c"}, 3: {"a", "b", "c"}}
    b = truth.beliefs(sup, deny)
    assert b[1] > b[2]


TEXT = " ".join(f"word{i}" for i in range(60))


def test_a_reproduced_article_is_a_copy_of_the_earlier_one():
    arts = {1: {"text": TEXT, "published_at": 1}, 2: {"text": TEXT[:300] + " extra opening", "published_at": 2},
            3: {"text": " ".join(f"other{i}" for i in range(60)), "published_at": 3}}
    assert independence.copies(arts) == {2: 1}
    assert independence.merge_groups({1: "a", 2: "b", 3: "c"}, {2: 1}) == {1: "a", 2: "a", 3: "c"}


def test_short_blurbs_are_not_judged():
    assert independence.copies({1: {"text": "a b c", "published_at": 1}, 2: {"text": "a b c", "published_at": 2}}) == {}


def _nli(table):
    def f(pairs):
        out = []
        for p, h in pairs:
            out.append(table(p, h))
        return out
    return f


def test_check_worthiness_has_a_reject_option(monkeypatch):
    def fake(pairs):
        res = []
        for p, h in pairs:
            fact_h = h == checkworthy.FACT
            if "arrested" in p:
                res.append((0.9, 0.05, 0.05) if fact_h else (0.05, 0.9, 0.05))
            elif "failed" in p:
                res.append((0.05, 0.9, 0.05) if fact_h else (0.9, 0.05, 0.05))
            else:
                res.append((0.5, 0.4, 0.1))
        return res
    monkeypatch.setattr(nli, "predict", fake)
    assert checkworthy.classify(["Police arrested him.", "The policy failed farmers.", "Something vague."]) == [True, False, None]
    monkeypatch.setattr(nli, "predict", lambda pairs: [None] * len(pairs))
    assert checkworthy.classify(["x"]) == [None]


def test_the_evidence_gate_needs_a_passage_a_source_and_a_meaning_match(monkeypatch):
    ev = "The FIR records that the accused was not present in the city on that date.\nA second line of ordinary evidence here."
    monkeypatch.setattr(nli, "predict", lambda pairs: [(0.02, 0.1, 0.9)] + [(0.1, 0.8, 0.1)] * (len(pairs) - 1))
    assert groundjudge.holds("He was in the city.", ev, ["https://x"], "contradicted")
    assert not groundjudge.holds("He was in the city.", ev, [], "contradicted")                  # no source address
    assert not groundjudge.holds("He was in the city.", ev, ["https://x"], "supported")
    monkeypatch.setattr(nli, "predict", lambda pairs: [None] * len(pairs))
    assert not groundjudge.holds("He was in the city.", ev, ["https://x"], "contradicted")      # could not ask: no change


def test_position_groups_merge_overlapping_intervals_and_split_clear_gaps():
    pos = [{"unit": "A", "theta": -1.0, "lo": -1.3, "hi": -0.7}, {"unit": "B", "theta": -0.6, "lo": -0.9, "hi": -0.3},
           {"unit": "C", "theta": 1.0, "lo": 0.7, "hi": 1.3}]
    assert positions.groups(pos) == {"A": 0, "B": 0, "C": 1}


class _Store:
    def __init__(self):
        self.t = {}
    def translation_get(self, keys):
        return {k: self.t[k] for k in keys if k in self.t}
    def translation_put(self, d):
        self.t.update(d)


def test_hindi_loaded_words_map_to_the_nearest_english_concept(monkeypatch):
    space = {"दंगाई": [1, 0], "rioters": [0.99, 0.1], "fruit": [0, 1]}
    monkeypatch.setattr(embed, "vectors", lambda texts: (np.array([space[t] for t in texts], float) / np.array(
        [[np.linalg.norm(space[t])] for t in texts]), "bi-encoder"))
    st = _Store()
    assert concepts.map_new(st, None, {"दंगाई", "rioters", "fruit"}) == 1
    assert concepts.lookup(st, {"दंगाई"})["दंगाई"] == "rioters"
    monkeypatch.setattr(embed, "vectors", lambda texts: (np.zeros((len(texts), 2)), "tfidf"))
    assert concepts.map_new(_Store(), None, {"दंगाई", "rioters"}) == 0

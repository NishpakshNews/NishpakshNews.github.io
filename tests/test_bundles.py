"""Facts two outlets share inside bundled sentences (bundles.py, owner Oct 26 2026)."""
import re

from sqlalchemy import insert

from nishpaksh import bundles, nlp, sentences
from nishpaksh.db import Store, articles, claims, select, stories

A = "Cyclone Montha made landfall on the Andhra coast on Tuesday morning with winds of 100 km/h."
B = "Cyclone Montha made landfall on the Andhra coast, officials said."

# the parse of A by hand: (dep, head index); tokens in the order of TOKENS
#  0 Cyclone 1 Montha 2 made 3 landfall 4 on 5 the 6 Andhra 7 coast 8 on 9 Tuesday 10 morning 11 with 12 winds 13 of 14 100 15 km/h 16 .
A_DEPS = [("compound", 1), ("nsubj", 2), ("ROOT", 2), ("dobj", 2), ("prep", 2), ("det", 7), ("compound", 7), ("pobj", 4),
          ("prep", 2), ("compound", 10), ("pobj", 8), ("prep", 2), ("pobj", 11), ("prep", 12), ("nummod", 15), ("pobj", 13),
          ("punct", 2)]


def _parser_for(spec: dict):
    def parse(text):
        deps = spec.get(text)
        if deps is None:
            return None
        found = list(re.finditer(r"[\w'/-]+|[^\w\s]", text))
        assert len(found) == len(deps), (len(found), len(deps))
        return [nlp.Tok(i, m.group(0), m.start(), m.end(), {"said": "say"}.get(m.group(0).lower(), m.group(0).lower()), "NN",
                        "VERB" if dep in ("ROOT", "ccomp") else "NOUN",
                        dep, head) for i, (m, (dep, head)) in enumerate(zip(found, deps))]
    return parse


def _model(pairs):
    """A small stand-in for the NLI model: the premise entails the hypothesis when it has all the hypothesis's words (a figure
    the hypothesis lacks does not matter: it says less) or the two share most of their words."""
    out = []
    for p, h in pairs:
        wp = set(re.findall(r"[a-z0-9]+", p.lower()))
        wh = set(re.findall(r"[a-z0-9]+", h.lower()))
        near = len(wp & wh) / max(1, len(wp | wh))
        out.append((0.93, 0.05, 0.02) if wh <= wp or near >= 0.75 else (0.08, 0.87, 0.05))
    return out


def _use(spec):
    import numpy as np
    from nishpaksh import embed, nli
    nlp.set_parser(_parser_for(spec))
    nli.set_backend(_model)
    embed.set_backend(lambda texts: np.tile(np.array([[0.6, 0.8]]), (len(texts), 1)))     # every text close to every other


import pytest


@pytest.fixture(autouse=True)
def _reset_embed():
    yield
    from nishpaksh import embed
    embed.set_backend(None)


def test_a_sentence_is_cut_into_its_core_and_details():
    _use({A: A_DEPS})
    d = bundles.decompose(A)
    assert d is not None and len(d.details) == 3
    assert d.build([]) == "Cyclone Montha made landfall."
    assert d.build([0]) == "Cyclone Montha made landfall on the Andhra coast."
    assert d.build([1]) == "Cyclone Montha made landfall on Tuesday morning."
    assert d.build([2]) == "Cyclone Montha made landfall with winds of 100 km/h."
    assert d.build([0, 2]) == "Cyclone Montha made landfall on the Andhra coast with winds of 100 km/h."


def test_a_sentence_with_one_detail_is_one_fact():
    deps = list(A_DEPS)
    deps[8] = ("prep", 7)                  # "on Tuesday morning" and "with winds" hang on the coast, not on the verb
    deps[11] = ("prep", 7)
    _use({A: deps})
    assert bundles.decompose(A) is None
    assert bundles.decompose("Too short.") is None
    nlp.set_parser(lambda t: None)         # no parse: nothing is cut
    assert bundles.decompose(A) is None


def test_a_speaker_stays_with_every_piece():
    s = "Police said that the cyclone made landfall near Bapatla on Tuesday with winds of 100 km/h on the coast."
    #  0 Police 1 said 2 that 3 the 4 cyclone 5 made 6 landfall 7 near 8 Bapatla 9 on 10 Tuesday 11 with 12 winds 13 of 14 100
    #  15 km/h 16 on 17 the 18 coast 19 .
    deps = [("nsubj", 1), ("ROOT", 1), ("mark", 5), ("det", 4), ("nsubj", 5), ("ccomp", 1), ("dobj", 5), ("prep", 5), ("pobj", 7),
            ("prep", 5), ("pobj", 9), ("prep", 5), ("pobj", 11), ("prep", 12), ("nummod", 15), ("pobj", 13), ("prep", 15),
            ("det", 18), ("pobj", 16), ("punct", 1)]
    nlp.set_parser(lambda t: None)
    _use({s: deps})
    d = bundles.decompose(s)
    assert d is not None
    assert d.build([1]).startswith("Police said the cyclone made landfall on Tuesday")


def test_the_shared_detail_is_what_the_other_report_says():
    _use({A: A_DEPS})
    got = bundles.examine(A, B, bundles.decompose(A), None)
    assert got["pa"] == "Cyclone Montha made landfall on the Andhra coast."
    assert got["ra"] == "Cyclone Montha made landfall on Tuesday morning with winds of 100 km/h."
    assert "pb" not in got                                      # the other statement is already one fact: it is the shared part


def test_nothing_shared_nothing_cut():
    _use({A: A_DEPS})
    other = "Parliament passed the finance bill after a long debate on Tuesday morning in the capital."
    assert bundles.examine(A, other, bundles.decompose(A), None) == {}


def test_the_model_could_not_be_read():
    from nishpaksh import nli
    _use({A: A_DEPS})
    nli.set_backend(lambda ps: [None] * len(ps))
    assert bundles.examine(A, B, bundles.decompose(A), None) is None


def test_the_pieces_must_carry_every_figure_once():
    _use({A: A_DEPS})
    d = bundles.decompose(A)
    assert bundles.faithful(A, d, [d.build([0]), d.build([1, 2])]) is None
    assert bundles.faithful(A, d, [d.build([0]), d.build([1])]) == "number_lost"
    assert bundles.faithful(A, d, [d.build([0, 2]), d.build([1, 2])]) == "number_shared"


# ------------------------------------------------------------------ the pass, through the database
def _story(tmp_path, rows):
    s = Store(f"sqlite:///{tmp_path / 'b.db'}")
    s.init()
    with s.engine.begin() as c:
        c.execute(insert(stories), [dict(id=1, analysis={})])
        for aid in sorted({r[0] for r in rows}):
            c.execute(insert(articles), [dict(id=aid, url=f"u{aid}", lang="en", outlet=f"Outlet {aid}")])
        c.execute(insert(claims), [dict(story_id=1, article_id=aid, local_id=lid, kind="event", text=t, stance="asserts",
                                        attributed_to="", evidence="none", rel={}) for aid, lid, t in rows])
    return s


def test_two_reports_that_bundle_different_details_are_cut_at_what_they_share(tmp_path):
    _use({A: A_DEPS})
    s = _story(tmp_path, [(1, "e1", A), (2, "e1", B)])
    out = bundles.split_bundles(s, 1)
    assert out["split"] == 1 and out["rows"] == 1
    texts = sorted(r["text"] for r in s.rows(select(claims).where(claims.c.story_id == 1)))
    assert texts == sorted([B, "Cyclone Montha made landfall on the Andhra coast.",
                            "Cyclone Montha made landfall on Tuesday morning with winds of 100 km/h."])
    pieces = [r for r in s.rows(select(claims)) if (r["rel"] or {}).get("bundle")]
    assert {(r["rel"]["bundle"]["role"], r["rel"]["bundle"]["root"]) for r in pieces} == {("shared", "1:e1"), ("rest", "1:e1")}
    assert all(r["rel"]["split"] == "piece" for r in pieces)
    # the story is not read again while nothing changed, and the answer is remembered
    again = bundles.split_bundles(s, 1)
    assert again["split"] == 0
    assert s.one(select(stories.c.analysis).where(stories.c.id == 1))["analysis"]["bundle_pairs"]


def test_one_report_alone_is_never_cut(tmp_path):
    _use({A: A_DEPS})
    s = _story(tmp_path, [(1, "e1", A), (1, "e2", B)])
    assert bundles.split_bundles(s, 1)["split"] == 0


def test_a_pair_the_model_could_not_read_is_asked_again(tmp_path):
    from nishpaksh import nli
    _use({A: A_DEPS})
    s = _story(tmp_path, [(1, "e1", A), (2, "e1", B)])
    saved = nli._backend
    nli.set_backend(lambda ps: [None] * len(ps))
    assert bundles.split_bundles(s, 1)["split"] == 0
    assert not (s.one(select(stories.c.analysis).where(stories.c.id == 1))["analysis"].get("bundle_pairs"))
    nli.set_backend(saved)
    assert bundles.split_bundles(s, 1)["split"] == 1


# ------------------------------------------------------------------ the writer gets the pieces as one sentence
def _item(i, text, roots, **kw):
    return dict(id=i, text=text, bundle_roots=roots, verdict="unverified", **kw)


def test_pieces_of_one_report_sentence_are_one_group_even_through_a_chain():
    items = [_item(1, "x", ["1:e1", "2:e1"]), _item(2, "y", ["1:e1"]), _item(3, "z", ["2:e1"]), _item(4, "w", ["9:e9"]),
             _item(5, "v", [])]
    assert sentences.bundle_sets(items) == [[1, 2, 3]]


def test_a_chain_too_long_for_one_sentence_stays_apart():
    items = [_item(n, "x", ["r"]) for n in range(1, 9)]
    assert sentences.bundle_sets(items) == []


def test_the_writer_is_told_to_join_the_pieces():
    one, two = _item(1, "a", ["r"], bundle=[1, 2]), _item(2, "b", ["r"], bundle=[1, 2])
    line = sentences.link_line(two, one)
    assert line and line.startswith("PIECES of one sentence with #1")


def test_the_plan_keeps_the_pieces_in_one_paragraph():
    from nishpaksh import plan
    items = [dict(id=n, text=t, bundle_roots=r, verdict="unverified", n_articles=1) for n, t, r in (
        (1, "Cyclone Montha made landfall on the Andhra coast.", ["a"]),
        (2, "Parliament passed the finance bill after a long debate.", []),
        (3, "Cyclone Montha made landfall on Tuesday morning with winds of 100 km/h.", ["a"]))]
    units = plan._units(items)
    assert sorted(len(u) for u in units) == [1, 2]


def test_the_sentence_has_one_coloured_part_for_each_piece():
    from nishpaksh import narrative
    texts = {1: "Cyclone Montha made landfall on the Andhra coast.",
             2: "Cyclone Montha made landfall on Tuesday morning.",
             3: "Cyclone Montha made landfall with winds of 100 km/h."}
    by = {n: dict(id=n, kind="event", text=t, verdict=v, speaker=None, sources=[], time=None, check=None,
                  bundle_roots=["r"] if n else [], bundle=[1, 2, 3], parallel=[1, 2, 3])
          for (n, t), v in zip(texts.items(), ("corroborated", "unverified", "single"))}
    sent = {"text": "Cyclone Montha made landfall on the Andhra coast on Tuesday morning, with winds of 100 km/h.",
            "ids": [1, 2, 3]}
    parts = {"parts": [{"text": "Cyclone Montha made landfall on the Andhra coast", "ids": [1]},
                       {"text": "on Tuesday morning,", "ids": [2]},
                       {"text": "with winds of 100 km/h.", "ids": [3]}]}
    out = narrative._with_parts(dict(sent), parts, by)
    assert [p["ids"] for p in out["parts"]] == [[1], [2], [3]]               # three colours in one sentence
    assert sentences.link_line(by[3], by[2]).startswith("PIECES of one sentence")

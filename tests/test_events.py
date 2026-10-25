"""events.py (B15): ranks learned from dated stories, decisive acts by meaning."""
from nishpaksh import events, nlp


def _parser(text):
    import re
    out = []
    for i, m in enumerate(re.finditer(r"[A-Za-z]+", text)):
        w = m.group(0).lower()
        lem = {"detained": "detain", "released": "release"}.get(w, w)
        verb = w in ("detained", "released")
        out.append(nlp.Tok(i, m.group(0), m.start(), m.end(), lem, "VBD" if verb else "NN", "VERB" if verb else "NOUN",
                           "ROOT" if verb else "dep", i))
    return out


def test_learn_places_verbs_by_where_they_fall_in_the_dated_story(monkeypatch):
    monkeypatch.setattr(nlp, "parse", _parser)
    events._lemma_cache.clear()
    rows = []
    for s in range(1, 10):
        rows.append({"story_id": s, "text": "Police detained him", "time": {"start": "2026-10-01T00:00:00"}})
        rows.append({"story_id": s, "text": "Court released him", "time": {"start": "2026-10-05T00:00:00"}})
    got = events.learn(rows)
    assert got["detain"][0] < 0.1 and got["release"][0] > 0.9
    assert events.learn(rows[:6]) == {}                       # fewer than MIN_N sightings: no rank
    events._lemma_cache.clear()


def test_acts_by_meaning_and_unavailable_model_is_zero(monkeypatch):
    from nishpaksh import nli
    events._act_cache.clear()
    nli.set_backend(lambda pairs: [(0.9, 0.05, 0.05) if h == events.DEATH else (0.1, 0.8, 0.1) for t, h in pairs])
    assert events.act_score("Five people died") == 3
    events._act_cache.clear()
    nli.set_backend(lambda pairs: [(0.1, 0.8, 0.1)] * len(pairs))
    assert events.act_score("A speech was given") == 0
    events._act_cache.clear()
    nli.set_backend(lambda pairs: [None] * len(pairs))
    assert events.act_score("Anything") == 0
    events._act_cache.clear()

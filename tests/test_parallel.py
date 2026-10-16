"""Parallel statements joined into one sentence (sentences.parallel_groups, context plan session 7; owner Oct 16 2026:
"If Modi has said it, they should be joined")."""
from nishpaksh import narrative, plan, sentences


def item(i, what, verdict="corroborated", who="Prime Minister Narendra Modi", action="inaugurate", **k):
    text = f"{who} will {action} {what} in Leh"
    return {"id": i, "kind": "event", "text": text, "verdict": verdict, "speaker": None, "sources": [],
            "time": None, "check": None, "frame": {"who": who, "action": action, "what": what, "value": "",
                                                   "where": "Leh", "negated": False}, **k}


def ladakh():
    return {1: item(1, "a petroglyph park"), 2: item(2, "40 water bodies", "single"),
            3: item(3, "a 9 MW hydro project", who="Modi"), 4: item(4, "the new Leh airport terminal"),
            5: item(5, "a hospital", who="Chief Minister Omar Abdullah"),
            6: item(6, "the new Leh airport terminal", action="visit")}


def test_one_actor_one_action_several_things_is_a_group():
    by = ladakh()
    pl = [plan.Para(1, "happened", [1, 5, 2, 6, 3, 4])]
    g = sentences.parallel_groups(pl, by)
    assert g[1] == [1, 2, 3, 4] and 5 not in g and 6 not in g     # another actor; another action
    sentences.keep_together(pl, g)
    assert pl[0].ids == [1, 2, 3, 4, 5, 6]


def test_speech_disputes_and_different_times_are_not_parallel():
    by = {1: item(1, "the budget", action="say"), 2: item(2, "the economy", action="say"),
          3: item(3, "a park", verdict="disputed"), 4: item(4, "a road"),
          5: item(5, "a bridge", time={"when_text": "Friday"}), 6: item(6, "a school", time={"when_text": "Monday"})}
    g = sentences.parallel_groups([plan.Para(1, "happened", [1, 2, 3, 4, 5, 6])], by)
    assert not ({1, 2, 3} & set(g)) and g.get(5) is None


def test_the_writer_is_told_to_join_and_parts_keep_each_colour():
    by = ladakh()
    pl = [plan.Para(1, "happened", [1, 2, 3, 4])]
    g = sentences.parallel_groups(pl, by)
    for x in g:
        by[x] = dict(by[x], parallel=g[x])
    assert "PARALLEL with #1" in sentences.link_line(by[2], by[1])
    sent = {"text": "Modi will inaugurate a petroglyph park, 40 water bodies, a 9 MW hydro project and the new Leh "
                    "airport terminal in Leh.", "ids": [1, 2, 3, 4]}
    parts = {"parts": [{"text": "Modi will inaugurate a petroglyph park,", "ids": [1]},
                       {"text": "40 water bodies,", "ids": [2]},
                       {"text": "a 9 MW hydro project", "ids": [3]},
                       {"text": "and the new Leh airport terminal in Leh.", "ids": [4]}]}
    out = narrative._with_parts(dict(sent), parts, by)
    assert [p["ids"] for p in out["parts"]] == [[1], [2], [3], [4]]          # four parts: each its own colour
    stats = sentences.stats([[out]], by)
    assert stats["parallel"] == 1 and stats["parallel_apart"] == 0
    apart = sentences.stats([[{"text": "a.", "ids": [1]}, {"text": "b.", "ids": [2, 3, 4]}]], by)
    assert apart["parallel_apart"] == 1

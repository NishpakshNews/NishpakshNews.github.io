"""A very large story is written from its best-supported statements (compose.trim_to_cap)."""
from nishpaksh import compose


def item(i, n=1, role="core", **kw):
    d = {"id": i, "kind": "event", "text": f"t{i}", "verdict": "unverified", "n_sources": n, "n_articles": n,
         "minor": n <= 1, "role": role, "time": None, "conflicts_with": [], "responds_to": [], "responded_by": []}
    d.update(kw)
    return d


def payload(items):
    core = [i for i in items if i["role"] == "core"]
    return {"timeline": [], "undated": core, "established": [], "contested": [],
            "context": [i for i in items if i["role"] != "core"], "news": [], "lead": []}


def test_small_story_untouched():
    p = payload([item(i) for i in range(10)])
    assert compose.trim_to_cap(p, 60) == 0 and not p.get("also")


def test_context_goes_first_then_least_supported_and_locked_stay():
    items = [item(i, n=3) for i in range(5)] + [item(10 + i, n=1, role="background") for i in range(4)]
    items += [item(20, n=1, verdict="disputed"), item(21, n=1, conflicts_with=[20]), item(22, n=1)]
    p = payload(items)
    moved = compose.trim_to_cap(p, 7)                      # 12 statements, 5 over
    assert moved == 5
    gone = {i["id"] for i in p["also"]}
    assert {10, 11, 12, 13} <= gone                        # context first
    assert 20 not in gone and 21 not in gone              # disputed / paired lines are never moved
    assert gone == {10, 11, 12, 13, 22}
    assert all(i["id"] not in gone for i in p["undated"] + p["context"])

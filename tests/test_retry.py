"""In-run retry of a story written short, and the coherence guard at a lowered bar (owner, Oct 28 2026)."""
import time

from nishpaksh import compose, desk
from nishpaksh import narrative as N


def S(t):
    return {"text": t, "ids": [1]}


def test_lone_paragraphs_join_their_neighbour_of_the_same_section_by_code():
    paras = [[S("Lead one.")], [S("Back one."), S("Back two.")], [S("Lone back.")], [S("Say one.")], [S("Say two.")]]
    keys = ["news", "background", "background", "say", "say"]
    out, k, n = N.merge_lone_paragraphs(paras, keys)
    assert n == 2 and k == ["news", "background", "say"]
    assert [[s["text"] for s in p] for p in out] == [["Lead one."], ["Back one.", "Back two.", "Lone back."], ["Say one.", "Say two."]]
    assert [[s["text"] for s in p] for p in paras][1] == ["Back one.", "Back two."]      # the input is untouched


def test_the_lead_is_never_changed_and_a_lone_sentence_of_its_own_section_stays():
    paras = [[S("The lead sentence is here.")], [S("Numbers only are here.")], [S("Say one."), S("Say two.")]]
    out, k, n = N.merge_lone_paragraphs(paras, ["news", "numbers", "say"])
    assert n == 0 and len(out) == 3
    assert N.lowered_bar_problems(out) == ["1 one-sentence paragraph(s)"]
    out2, _, n2 = N.merge_lone_paragraphs([[S("The lead sentence is here.")], [S("A lone sentence is here.")], [S("Two a is here."), S("Two b is here.")]], ["news", "say", "say"])
    assert n2 == 1 and len(out2) == 2 and len(out2[0]) == 1          # not joined into the lead


def test_a_paragraph_is_not_grown_past_six_sentences():
    big = [S(f"Sentence {i}.") for i in range(6)]
    out, _, n = N.merge_lone_paragraphs([[S("The lead sentence is here.")], big, [S("A lone sentence is here.")]], ["news", "say", "say"])
    assert n == 0 and len(out) == 3


def test_the_guard_names_cut_off_and_repeated_text_and_passes_clean_text():
    assert N.lowered_bar_problems([[S("The lead sentence is here.")], [S("On Sunday, US chief Adm."), S("A fine sentence here.")]]) == ["1 cut-off sentence(s)"]
    rep = "The Chief Minister Chandrababu said that the Chief Minister Chandrababu will come."
    assert N.lowered_bar_problems([[S("The lead sentence is here.")], [S(rep), S("Another one.")]]) == ["1 repeated run(s)"]
    assert N.lowered_bar_problems([[S("The lead sentence is here.")], [S("One sentence here."), S("Two sentences here.")]]) == []


def _run(monkeypatch, outcomes, tries_after, until=None, now_left=None):
    """outcomes: what each publish_story call does; tries_after: the writer-tries count after each call."""
    calls = []
    seq = iter(outcomes)
    counts = iter(tries_after)
    state = {"n": 0}

    def fake_publish(store, router, sid):
        calls.append(sid)
        ok, why, detail = next(seq)
        state["n"] = next(counts)
        compose.LAST_OUTCOME.clear()
        compose.LAST_OUTCOME.update(story=str(sid), outcome=why, detail=detail)
        return ok
    monkeypatch.setattr(compose, "publish_story", fake_publish)
    monkeypatch.setattr(compose, "_writer_tries", lambda store, sid: state["n"])
    stats: dict = {}
    ok = desk._write_with_retries(None, None, 7, until, stats)
    return ok, calls, stats


SHORT = lambda bar: (False, "written short", {"why": "coverage", "bar": bar})      # noqa: E731


def test_a_short_story_is_retried_at_once_until_it_publishes(monkeypatch):
    ok, calls, stats = _run(monkeypatch, [SHORT(0.8), SHORT(0.75), (True, "published", None)], [1, 2, 2])
    assert ok and len(calls) == 3 and stats["retries"] == {"7": 2}


def test_a_story_has_three_tries_a_run_and_then_waits(monkeypatch):
    ok, calls, stats = _run(monkeypatch, [SHORT(0.8), SHORT(0.75), SHORT(0.7), SHORT(0.65)], [1, 2, 3, 4])
    assert not ok and len(calls) == desk.RUN_TRIES


def test_no_retry_after_a_try_at_the_floor_or_when_the_bar_did_not_step(monkeypatch):
    ok, calls, _ = _run(monkeypatch, [SHORT(0.5), SHORT(0.5)], [6, 7])
    assert not ok and len(calls) == 1
    ok, calls, _ = _run(monkeypatch, [SHORT(0.8), SHORT(0.8)], [0, 0])           # an overloaded model: no try used
    assert not ok and len(calls) == 1


def test_only_a_coverage_shortfall_is_retried(monkeypatch):
    for why in ("most sentences rejected", "no essay", "coherence guard: 1 one-sentence paragraph(s)"):
        ok, calls, _ = _run(monkeypatch, [(False, "written short", {"why": why, "bar": 0.8}), SHORT(0.75)], [1, 2])
        assert len(calls) == 1
    ok, calls, _ = _run(monkeypatch, [(False, "headline failed", None), SHORT(0.75)], [1, 2])
    assert len(calls) == 1


def test_no_retry_when_the_run_is_nearly_over(monkeypatch):
    ok, calls, stats = _run(monkeypatch, [SHORT(0.8), SHORT(0.75)], [1, 2], until=time.time() + 60)
    assert len(calls) == 1 and "retries" not in stats

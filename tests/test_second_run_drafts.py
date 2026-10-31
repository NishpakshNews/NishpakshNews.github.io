"""The second desk run takes the story with the least writing left, a kept draft first; a draft that fails the lowered-bar
guard is mended, never thrown away (owner, Oct 31 2026)."""
import datetime as dt

from nishpaksh import compose, desk
from nishpaksh import narrative as N


def S(t, ids=(1,)):
    return {"text": t, "ids": list(ids)}


# --- remaining work -------------------------------------------------------------------------------------------------

def test_fill_need_is_the_count_behind_fill_bar():
    for n in (1, 3, 5, 12, 20, 21, 40, 80):
        for t in range(10):
            need = N.fill_need(t, n)
            assert next(k for k in range(n + 1) if k >= N.fill_bar(t, n) * n) == need


def test_a_story_with_no_draft_needs_the_whole_bar():
    assert compose.remaining_work({}, 5) == N.fill_need(0, 5) == 4
    assert compose.remaining_work({}, 40) == N.fill_need(0, 40) == 32


def test_a_draft_needs_only_what_it_lacks():
    an = {"writer_draft": {"sections": [["say", []]], "covers": 30},
          "writer_failures": {"n": 1, "shortfall": {"total": 40, "why": "coverage"}}}
    assert compose.remaining_work(an, 40) == N.fill_need(1, 40) - 30 == 0        # the next bar (30 of 40) is already met
    an["writer_draft"]["covers"] = 25
    assert compose.remaining_work(an, 40) == 5


def test_a_draft_finished_but_for_its_headline_costs_nothing():
    an = {"writer_draft": {"sections": [["news", []]], "covers": 5}}              # no failure recorded: only the headline failed
    assert compose.remaining_work(an, 5) == 0


def test_a_draft_never_costs_more_than_a_fresh_write():
    an = {"writer_draft": {"sections": [["say", []]], "covers": 0}, "writer_failures": {"n": 2, "shortfall": {"total": 10}}}
    assert compose.remaining_work(an, 10) <= N.fill_need(0, 10)


def test_a_draft_without_sections_is_not_counted():
    assert compose.remaining_work({"writer_draft": {"covers": 9}}, 5) == N.fill_need(0, 5)


# --- the pause at the lowest bar ------------------------------------------------------------------------------------

def test_a_story_tried_at_the_floor_a_moment_ago_is_resting_likely():
    now = compose.utcnow()
    floor_try = {"writer_failures": {"n": 30, "at": (now - dt.timedelta(hours=1)).isoformat(timespec="minutes")}}
    assert compose.resting_likely(floor_try, 8, now)
    old = {"writer_failures": {"n": 30, "at": (now - dt.timedelta(hours=compose.FLOOR_WAIT_HOURS + 1)).isoformat(timespec="minutes")}}
    assert not compose.resting_likely(old, 8, now)
    high_bar = {"writer_failures": {"n": 1, "at": now.isoformat(timespec="minutes")}}     # still well above the floor: tried at once
    assert not compose.resting_likely(high_bar, 40, now)
    assert not compose.resting_likely({}, 8, now)


# --- the order of the second run --------------------------------------------------------------------------------------

def test_the_fill_run_takes_the_draft_that_lacks_least_and_a_resting_story_last(monkeypatch):
    from nishpaksh import consolidate, verify
    sizes = {1: 12, 2: 5, 3: 30, 4: 8}
    # story 3 is big but its draft lacks nothing; story 2 has no draft; story 4 is resting; story 1 has a draft lacking 2
    works = {1: (2, False), 2: (4, False), 3: (0, False), 4: (0, True)}
    monkeypatch.setattr(desk, "published_this_hour", lambda *a, **k: 0)
    monkeypatch.setattr(desk, "ready", lambda store, now=None, refused_out=None: [1, 2, 3, 4])
    monkeypatch.setattr(desk, "story_size", lambda store, sid: sizes[sid])
    monkeypatch.setattr(desk, "story_work", lambda store, sid, size, now: works[sid])
    monkeypatch.setattr(desk, "_review_open", lambda *a: False)
    monkeypatch.setattr(consolidate, "consolidate_story", lambda *a, **k: None)
    monkeypatch.setattr(verify, "base_verdicts", lambda *a, **k: None)
    seen = []

    def fake_publish(store, router, sid):
        seen.append(sid)
        compose.LAST_OUTCOME = {"outcome": "published"}
        return sid != 3
    monkeypatch.setattr(compose, "publish_story", fake_publish)
    st = desk.fill_work(None, None)
    assert [x[0] for x in st["fill"]["order"]] == [3, 1, 2, 4]          # least writing first, the resting story last
    assert seen[:2] == [3, 1] and st["published"] == [1] and st["fill"]["resting"] == [4]


def test_a_failure_reading_the_work_falls_back_to_the_statement_count():
    class Broken:
        def one(self, *a, **k):
            raise RuntimeError("no database")
    assert desk.story_work(Broken(), 7, 6, compose.utcnow()) == (6, False)


# --- the guard repair -----------------------------------------------------------------------------------------------

def _paras(n_lone):
    out = [[S("The lead sentence says the main thing.")]]
    keys = ["news"]
    for k in range(n_lone):
        out.append([S(f"Lone sentence number {k} about a different thing.", (k + 2,))])
        keys.append(f"sec{k}")                      # every lone sentence is alone in its own section
    out.append([S("A closing paragraph one."), S("A closing paragraph two.")])
    keys.append("next")
    return out, keys


def test_lone_paragraphs_in_their_own_sections_join_a_neighbour_until_the_guard_passes():
    paras, keys = _paras(5)
    assert len(N.lowered_bar_problems(paras)) == 1 and "one-sentence" in N.lowered_bar_problems(paras)[0]
    out, ks, joined = N.join_lone_across_sections(paras, keys)
    assert joined == 1 and not N.lowered_bar_problems(out)      # one join removes two lone paragraphs (a lone one joined to a lone one)
    before = [s["text"] for p in paras for s in p]
    assert [s["text"] for p in out for s in p] == before                    # no sentence changed, added, lost or reordered
    assert len(ks) == len(out) and ks[0] == "news" and len(out[0]) == 1      # the lead is left alone
    assert len(paras) == 7                                                   # the input is untouched


def test_nothing_is_joined_when_the_guard_already_passes():
    paras, keys = _paras(3)
    out, ks, joined = N.join_lone_across_sections(paras, keys)
    assert joined == 0 and out == paras and ks == keys


def test_a_join_that_makes_the_coherence_count_worse_is_not_made(monkeypatch):
    paras, keys = _paras(5)
    calls = {"n": 0}

    def counts(p):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 5            # the baseline is 0, every trial join is worse
    monkeypatch.setattr(N, "_coherence_problems", counts)
    out, ks, joined = N.join_lone_across_sections(paras, keys)
    assert joined == 0 and out == paras


def test_when_the_coherence_cannot_be_measured_nothing_is_joined(monkeypatch):
    paras, keys = _paras(5)
    monkeypatch.setattr(N, "_coherence_problems", lambda p: None)
    assert N.join_lone_across_sections(paras, keys)[2] == 0


def test_a_lone_sentence_is_never_joined_into_the_lead_or_a_full_paragraph(monkeypatch):
    big = [S(f"Sentence {k} of a long paragraph.") for k in range(N.LONE_MERGE_MAX + 1)]
    paras = [[S("Lead.")], [S("Lone one.", (2,))], big, [S("Lone two.", (3,))], big, [S("Lone three.", (4,))], big,
             [S("Lone four.", (5,))]]
    keys = ["news", "a", "b", "c", "d", "e", "f", "g"]
    monkeypatch.setattr(N, "_coherence_problems", lambda p: 0)
    out, ks, joined = N.join_lone_across_sections(paras, keys)
    assert [s["text"] for s in out[0]] == ["Lead."] and len(out[0]) == 1
    assert all(len(p) <= N.LONE_MERGE_MAX + 1 or p is big for p in out)


class FakeRouter:
    def __init__(self, data):
        self.data, self.calls = data, []

    def call(self, tier, prompt, **kw):
        self.calls.append((tier, prompt))

        class R:
            pass
        r = R()
        r.data = self.data
        return r


def test_repair_asks_nothing_when_no_sentence_is_cut_off(monkeypatch):
    monkeypatch.setattr(N, "cut_off", lambda t: False)
    r = FakeRouter({})
    out, asked, fixed = N.repair_cut_off(r, [[S("A fine sentence.")]], {}, set())
    assert (asked, fixed) == (0, 0) and not r.calls


def test_repair_without_a_router_changes_nothing(monkeypatch):
    monkeypatch.setattr(N, "cut_off", lambda t: True)
    out, asked, fixed = N.repair_cut_off(None, [[S("Adm.")]], {}, set())
    assert (asked, fixed) == (0, 0) and out[0][0]["text"] == "Adm."


def test_a_cut_off_sentence_is_rewritten_once_and_checked(monkeypatch):
    payload = {"sources": [{"outlet": "A", "url": "u"}]}
    by_id = {7: {"id": 7, "text": "Police arrested two men on Sunday.", "verdict": "x", "sources": [], "speaker": None}}
    monkeypatch.setattr(N, "cut_off", lambda t: t.startswith("On Sunday"))
    monkeypatch.setattr(N, "_context", lambda p, b: ([by_id[7]], [], by_id, [], set()))
    monkeypatch.setattr(N, "_statement_line", lambda i: f"#{i['id']} {i['text']}")
    monkeypatch.setattr(N.entities, "use", lambda *a, **k: None)
    monkeypatch.setattr(N.entities, "for_items", lambda *a, **k: None)
    monkeypatch.setattr(N, "_check_one", lambda sent, *a, **k: (sent, list(sent["ids"])))
    r = FakeRouter({"text": "Police arrested two men on Sunday.", "ids": [7]})
    out, asked, fixed = N.repair_cut_off(r, [[S("Lead."), S("On Sunday, police.", (7,))]], payload, set())
    assert (asked, fixed) == (1, 1) and len(r.calls) == 1 and r.calls[0][0] == "writer"
    assert out[0][1]["text"] == "Police arrested two men on Sunday." and out[0][1]["ids"] == [7]


def test_a_rewrite_that_drops_a_cited_statement_or_still_cut_off_or_fails_a_check_is_refused(monkeypatch):
    by_id = {7: {"id": 7, "text": "x"}, 8: {"id": 8, "text": "y"}}
    monkeypatch.setattr(N, "cut_off", lambda t: t.startswith("On Sunday"))
    monkeypatch.setattr(N, "_context", lambda p, b: ([], [], by_id, [], set()))
    monkeypatch.setattr(N, "_statement_line", lambda i: "line")
    monkeypatch.setattr(N.entities, "use", lambda *a, **k: None)
    monkeypatch.setattr(N.entities, "for_items", lambda *a, **k: None)
    monkeypatch.setattr(N, "_check_one", lambda sent, *a, **k: (sent, list(sent["ids"])))
    start = [[S("Lead."), S("On Sunday, police.", (7, 8))]]
    for data in ({"text": "Police arrested two men.", "ids": [7]},            # drops statement 8
                 {"text": "On Sunday, still cut off.", "ids": [7, 8]},          # still not a sentence
                 {"text": "", "ids": [7, 8]}, {}):
        out, asked, fixed = N.repair_cut_off(FakeRouter(data), start, {}, set())
        assert fixed == 0 and out[0][1]["text"] == "On Sunday, police."
    monkeypatch.setattr(N, "_check_one", lambda sent, *a, **k: (sent, None))      # fails a per-sentence check
    out, asked, fixed = N.repair_cut_off(FakeRouter({"text": "Police arrested two men.", "ids": [7, 8]}), start, {}, set())
    assert fixed == 0 and out[0][1]["text"] == "On Sunday, police."


def test_repair_lowered_bar_only_acts_on_the_part_that_fails(monkeypatch):
    paras, keys = _paras(3)                                  # lone count within the allowance
    monkeypatch.setattr(N, "cut_off", lambda t: False)
    out, ks, st = N.repair_lowered_bar(None, paras, keys, {}, set())
    assert st == {"joined": 0, "cut_asked": 0, "cut_fixed": 0} and out == paras
    paras, keys = _paras(5)
    out, ks, st = N.repair_lowered_bar(None, paras, keys, {}, set())
    assert st["joined"] == 1 and not N.lowered_bar_problems(out)

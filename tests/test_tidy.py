"""nishpaksh/tidy.py: repeated lines inside a finished paragraph (B9 step 2). Shadow module: nothing in the pipeline calls it."""
from nishpaksh import tidy
from nishpaksh.relate import Profile

from .tidy_pairs import PAIRS


def L(text, ids, cls="established", sources=(1,)):
    return {"text": text, "ids": list(ids), "class": cls, "sources": list(sources)}


def _verdicts():
    lines = [t for _, a, b, _ in PAIRS for t in (a, b)]
    W = tidy.weights([Profile(t) for t in lines])
    return [(k, tidy.judge(0, 1, a, b, Profile(a), Profile(b), W), labels) for k, (_, a, b, labels) in enumerate(PAIRS)]


def test_a_line_is_never_dropped_where_no_reader_would_drop_it():
    """The precision rule on the labelled pairs: `same` / `covered` only where `covered` is an accepted label."""
    wrong = [(k, v.outcome) for k, v, labels in _verdicts() if v.outcome in ("same", "covered") and "covered" not in labels]
    assert wrong == []


def test_most_real_repeats_are_found_and_the_conflicts_are_named():
    rows = _verdicts()
    repeats = [(v, lab) for _, v, lab in rows if lab & {"covered", "overlap"} and not lab & {"distinct", "conflict"}]
    found = [v for v, _ in repeats if v.outcome in ("covered", "same", "overlap")]
    assert len(found) >= 0.8 * len(repeats)
    for k, v, lab in rows:
        if lab == {"conflict"}:
            assert v.outcome == "conflict", (k, v)


def test_a_contained_line_goes_and_its_sources_and_the_weaker_colour_join_the_other():
    a = L("Officials who have completed three years in the same district will be removed.", [1], "established", [1, 2])
    b = L("Officials who have completed three years in the same district will be removed, and the Commission removed 73 returning officers.",
          [2], "single", [3])
    out, rep = tidy.tidy([[a, b]])
    assert len(out[0]) == 1 and rep["folded"] == 1
    x = out[0][0]
    assert "73 returning officers" in x["text"] and x["ids"] == [2, 1] and x["sources"] == [1, 2, 3] and x["class"] == "single"
    assert a["text"] and len(([a, b])) == 2                    # the input is untouched


def test_two_different_figures_for_one_question_are_a_conflict_and_both_stay():
    a = L("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday 28 October.", [1])
    b = L("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Thursday 29 October.", [2])
    out, rep = tidy.tidy([[a, b]])
    assert len(out[0]) == 2 and rep["outcomes"].get("conflict") == 1


def test_a_different_ordinal_is_a_different_fact():
    a = L("For those under the 6th CPC, DA will rise from 262 per cent to 269 per cent of basic pay.", [1])
    b = L("For employees under the 5th CPC, the allowance will rise from 483 per cent to 497 per cent of basic pay.", [2])
    out, rep = tidy.tidy([[a, b]])
    assert len(out[0]) == 2 and "conflict" not in rep["outcomes"]


def test_a_quotation_inside_a_longer_one_is_folded_and_two_different_quotations_never_are():
    q1 = L("“You lack courage. We will ensure justice for these crimes,” Gandhi said.", [1])
    q2 = L("“Indian business is not a plaything. You lack courage. We will ensure justice for these crimes,” Gandhi said.", [2])
    out, _ = tidy.tidy([[q1, q2]])
    assert len(out[0]) == 1 and "plaything" in out[0][0]["text"]
    q3 = L("“We will hold a march at Ramlila Maidan on the first of November,” Venugopal said.", [3])
    out, rep = tidy.tidy([[q1, q3]])
    assert len(out[0]) == 2


def test_a_disputed_or_protected_line_is_never_folded():
    a = L("The Commission removed 73 returning officers in the state.", [1], "disputed")
    b = L("The Commission removed 73 returning officers in the state on Monday, officials said.", [2])
    out, rep = tidy.tidy([[a, b]])
    assert len(out[0]) == 2 and rep["skipped_guard"] == 1
    c = L("The Commission removed 73 returning officers in the state.", [7])
    out, rep = tidy.tidy([[c, b]], protect={7})
    assert len(out[0]) == 2


def test_an_overlap_is_only_merged_when_the_returned_sentence_passes_the_check():
    a = L("The 3% DA hike is effective from 1 July 2026.", [1])
    b = L("Since the DA hike is effective from 1 July 2026, central government employees and pensioners will get a higher salary this month.", [2])
    good = "The 3% DA hike, effective from 1 July 2026, gives central government employees and pensioners a higher salary this month."
    out, rep = tidy.tidy([[a, b]], rewrite=lambda x, y: good)
    assert rep["merged"] == 1 and len(out[0]) == 1 and out[0][0]["text"] == good and out[0][0]["ids"] == [1, 2]
    lost = "The DA hike is effective from 1 July 2026, giving central government employees and pensioners a higher salary this month."
    out, rep = tidy.tidy([[a, b]], rewrite=lambda x, y: lost)
    assert rep["merged"] == 0 and rep["merge_refused"] == 1 and len(out[0]) == 2
    out, rep = tidy.tidy([[a, b]])                                   # no writer: only reported
    assert rep["merged"] == 0 and rep["items"][0]["applied"] == "candidate"


def test_verify_merge_refuses_what_changes_a_fact():
    a = "Singh met Hegseth in Cebu on Wednesday."
    b = "Singh posted on X about his meeting with Hegseth."
    assert tidy.verify_merge(a, b, "Singh met Hegseth in Cebu on Wednesday and posted on X about the meeting.")[0]
    assert not tidy.verify_merge(a, b, "Singh met Hegseth in Manila on Wednesday and posted on X.")[0]          # a place: new word
    assert not tidy.verify_merge(a, b, "Singh met Hegseth in Cebu. He posted on X about it.")[0]               # two sentences
    assert not tidy.verify_merge(a, b, "Singh and Rajnath met Hegseth in Cebu on Wednesday and posted on X.")[0]   # a name invented
    assert not tidy.verify_merge(a, b, "Singh did not meet Hegseth in Cebu on Wednesday but posted on X.")[0]  # negation
    assert not tidy.verify_merge("Prices rose 40 per cent.", "Prices rose in March.", "Prices rose 42 per cent in March.")[0]
    q = "“We will win,” Rao said on Monday."
    assert not tidy.verify_merge(q, "Rao spoke in Patna on Monday.", "Rao said we will win in Patna on Monday.")[0]   # quotation changed


def test_a_precisely_written_figure_replaces_its_rounded_twin_in_a_merge():
    a = "The increase will benefit around 48 lakh central government employees."
    b = "The government said the increase will benefit 48.54 lakh employees."
    ok, why = tidy.verify_merge(a, b, "The government said the increase will benefit 48.54 lakh central government employees.")
    assert ok, why


def test_the_reader_can_only_turn_an_overlap_into_covered_when_the_gates_agree():
    a = "Police arrested the engineer in Patna on Monday."
    b = "Police arrested the engineer in Patna on Monday, officials said, after a month-long search."
    others = ["The court heard the plea on Tuesday.", "Rain is expected in Kerala this week.", "The minister inaugurated a bridge in Ranchi.",
              "Shares of two banks fell on Friday.", "A fire broke out at a factory in Surat.", "The league will resume next month."]
    W = tidy.weights([Profile(a), Profile(b)] + [Profile(t) for t in others])
    yes = lambda pairs: [True for _ in pairs]                          # a reader that says "yes" to everything
    v = tidy.judge(0, 1, a, b, Profile(a), Profile(b), W, nli_fn=yes)
    assert v.outcome in ("covered", "same") and v.drop == 0
    c = "Police arrested two engineers in Patna on Monday."            # a figure the other line lacks: a gate
    v = tidy.judge(0, 1, c, b, Profile(c), Profile(b), W, nli_fn=yes)
    assert v.outcome not in ("covered", "same")


def test_a_weekday_that_is_not_the_day_of_the_date_is_reported():
    assert tidy.weekday_errors("On Tuesday, 28 October 2026, the Cabinet approved it.") == ["Tuesday, 28 October 2026 (a wednesday)"]
    assert tidy.weekday_errors("On Wednesday, 28 October 2026, the Cabinet approved it.") == []


def test_a_paragraph_that_falls_to_one_sentence_is_counted():
    a = L("The deadline for the Station Master posts is 25 November 2026.", [1])
    b = L("The deadline for the Station Master posts is 25 November 2026, the Board said on Tuesday.", [2])
    out, rep = tidy.tidy([[a, b], [L("Applications opened on Tuesday.", [3])]])
    assert rep["to_one_sentence"] == 1 and [len(p) for p in out] == [1, 1]


def test_ledger_shadow_records_without_touching_pages():
    from nishpaksh import ledger
    pages = {"1": {"headline": "Cabinet approves container scheme", "lead": [],
                   "paragraphs": [[{"text": "The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday."},
                                   {"text": "The scheme aims to build domestic container production for Indian shipping lines."}]],
                   "also": []}}
    import copy
    before = copy.deepcopy(pages)
    out = ledger.shadow_from_pages(pages)
    assert pages == before and out["stories"] == 1 and "sample_folds" in out and out["also_would_insert"] == 0

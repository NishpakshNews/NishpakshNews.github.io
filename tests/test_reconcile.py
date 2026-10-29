"""nishpaksh/reconcile.py: how two lines about one thing differ (figures and dates as intervals, name aliases, negation scope)."""
from nishpaksh import reconcile as R, tidy, tidy_rewrite
from nishpaksh.relate import Profile


def D(a, b):
    return R.difference(a, b, Profile(a), Profile(b))


def L(text, ids, cls="established", sources=(1,)):
    return {"text": text, "ids": list(ids), "class": cls, "sources": list(sources)}


def test_two_readings_of_one_figure_are_reconcilable_and_a_count_off_by_one_is_a_conflict():
    d = D("It approved the scheme with an expenditure of ₹7,395.55 crore.", "The government approved ₹7,395 crore for the scheme.")
    assert d.status == "reconcilable" and d.notes and not d.conflicts
    d = D("Lula secured 51.75 per cent of the vote.", "Lula received 51.79 percent of the valid votes.")
    assert d.status == "reconcilable"
    d = D("Heavy rain is expected in 19 states including Bihar.", "Heavy rainfall warnings were issued in 20 states including Bihar.")
    assert d.conflicts and d.kind == "figure"                         # small whole counts are never "near"


def test_bounds_are_intervals_not_figures():
    assert not D("Winds of 125 to 135 kmph are expected.", "Wind speed will reach 125 kmph.").conflicts     # a point in a range
    assert D("Gusts up to 150 kmph are expected.", "Gusts up to 140 kmph are expected.").conflicts           # two tops differ
    assert not D("At least 40 people were hurt in the blast.", "Some 45 people were hurt in the blast.").conflicts


def test_a_smaller_count_in_a_narrower_place_is_a_part_not_a_conflict():
    d = D("At least 21 flights were cancelled at Vijayawada and Visakhapatnam airports.", "15 flights at Vijayawada airport were cancelled.")
    assert d.status == "part" and not d.conflicts


def test_a_total_is_not_a_disagreement_with_its_parts():
    d = D("The increase benefits 48 lakh employees and 68 lakh pensioners.", "The hike benefits over 1.17 crore employees and pensioners.")
    assert not d.conflicts


def test_dates_are_intervals_and_weekdays_are_evidence():
    assert not D("Shah was discharged in December 2014.", "Shah was discharged in 2014.").conflicts
    d = D("The roll will be published on 6 November.", "The roll will be published on 16 November.")
    assert d.kind == "date"
    d = D("On Tuesday, 28 October 2026, the Cabinet approved it.", "On Thursday, 29 October 2026, the Cabinet approved it.")
    assert d.kind == "date" and "weekday" in d.conflicts[0][1]


def test_names_match_by_prefix_acronym_and_near_spelling():
    a, b = R.compare_names(frozenset({"sco", "delhi"}), frozenset({"shanghai", "cooper", "organis", "delhi"}))
    assert not a and not b
    a, b = R.compare_names(frozenset({"yatra"}), frozenset({"rajmargyatra"}))
    assert not a and not b
    a, b = R.compare_names(frozenset({"khandu"}), frozenset({"sitharaman"}))
    assert a and b


def test_negation_is_read_with_its_scope():
    same = D("The declaration was not an amendment to Form 6, but a separate document.", "The declaration was a separate document rather than an amendment to the form.")
    assert not same.conflicts
    assert D("Police arrested the engineer in Patna.", "Police did not arrest the engineer in Patna.").kind == "negation"
    # a denial answers an allegation: never a conflict with the allegation
    assert not D("The petition alleges that Kumar took unilateral decisions.", "The Commission rejected allegations that Kumar took unilateral decisions.").conflicts
    # a negated detail the other line never mentions is an extra, not a contradiction
    assert not D("The cap applies to the MRP of the drug.", "The cap applies only to the MRP and not the price to the retailer.").conflicts


def test_a_near_figure_folds_and_the_second_reading_goes_in_brackets_only_when_asked():
    a = L("The scheme was approved with an outlay of ₹7,395 crore for rural works by the Cabinet on Wednesday.", [1])
    b = L("The scheme was approved with an outlay of ₹7,395.55 crore for rural works by the Cabinet on Wednesday, the minister said.", [2])
    out, rep = tidy.tidy([[a, b]])
    assert len(out[0]) == 1 and rep["folded"] == 1 and "(" not in out[0][0]["text"]
    out, rep = tidy.tidy([[a, b]], annotate=True)
    assert len(out[0]) == 1 and "in another account" in out[0][0]["text"]


def test_a_line_that_leans_on_the_one_before_is_not_the_one_that_stays():
    a = L("The student publicly apologized for the post.", [1])
    b = L("She also publicly apologized for the post in Pune.", [2])
    out, rep = tidy.tidy([[a, b]])
    assert rep["folded"] == 0 or "She" not in out[0][0]["text"]


def test_the_writer_is_asked_twice_and_both_answers_must_pass_the_check():
    a, b = "Singh met Hegseth in Cebu on Wednesday.", "Singh posted on X about his meeting with Hegseth."
    good = "Singh met Hegseth in Cebu on Wednesday and posted on X about the meeting."
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return good
    assert tidy_rewrite.make_rewrite(ask)(a, b) == good and len(calls) == 2
    answers = iter([good, "Singh met Hegseth in Manila."])
    assert tidy_rewrite.make_rewrite(lambda p: next(answers))(a, b) is None
    assert tidy_rewrite.make_rewrite(lambda p: "NO")(a, b) is None

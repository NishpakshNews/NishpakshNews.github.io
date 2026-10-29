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


def test_a_near_figure_folds_and_the_second_reading_is_kept_as_data_not_words():
    a = L("The scheme was approved with an outlay of ₹7,395 crore for rural works by the Cabinet on Wednesday.", [1], sources=(1,))
    b = L("The scheme was approved with an outlay of ₹7,395.55 crore for rural works by the Cabinet on Wednesday, the minister said.",
          [2], sources=(2,))
    out, rep = tidy.tidy([[a, b]])
    assert len(out[0]) == 1 and rep["folded"] == 1
    kept = out[0][0]
    assert "(" not in kept["text"] and "another" not in kept["text"]
    assert kept["variants"] == [{"shown": "7,395.55 crore", "value": "7,395 crore", "ids": [1], "sources": [1]}]


def test_a_line_is_not_taken_out_if_the_next_one_leans_on_it():
    first = L("The student publicly apologized for the post in Pune on Tuesday.", [1])
    mid = L("The student apologized publicly for the post in Pune on Tuesday, college officials said.", [2])
    lean = L("She also met the college principal.", [3])
    other = L("Officials said an inquiry was under way.", [4])
    out, rep = tidy.tidy([[first, other, mid, lean]])
    texts = [x["text"] for x in out[0]]
    assert texts[-1] == "She also met the college principal." and any("officials said" in t for t in texts if "inquiry" not in t) or len(texts) == 4


def test_two_overlapping_lines_are_merged_by_code_with_an_attachable_detail_only():
    from nishpaksh import fusion
    r = fusion.fuse("Representatives of dialogue partners and observer countries have also been invited.",
                    "Dialogue partner countries are also being invited to participate in the meeting.")
    assert r and r["text"].endswith("have also been invited to participate in the meeting.")
    r = fusion.fuse("The increase is expected to benefit around 48 lakh central government employees and 68 lakh pensioners.",
                    "The government said the increase will benefit 48.54 lakh employees and 68.71 lakh pensioners.")
    assert r and "48.54 lakh central government employees" in r["text"]            # the precise figure, the other line's detail
    r = fusion.fuse("Kalia made no statements about Chinese control over Arunachal Pradesh.",
                    "He made no such statement about Chinese control over Arunachal Pradesh.")
    assert r and r["text"].startswith("Kalia")                                      # a noun over a pronoun
    # a verb phrase is never grafted on, and a line that claims more or less ("only") is not merged with one that does not
    assert fusion.fuse("The Central Government may revise the annual fee rates on 1 April each year.",
                       "Revised rates will be effective from 1 April each year.") is None
    assert fusion.fuse("Only non-commercial vehicles with a valid FASTag are eligible for it.",
                       "Eligible non-commercial vehicle owners with a valid FASTag can choose between the monthly pass and the local pass.") is None


def test_the_model_fallback_is_asked_once_and_its_answer_is_checked_by_code():
    a, b = "Singh met Hegseth in Cebu on Wednesday.", "Singh posted on X about his meeting with Hegseth."
    good = "Singh met Hegseth in Cebu on Wednesday and posted on X about the meeting."
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return good
    assert tidy_rewrite.make_rewrite(ask)(a, b) == good and len(calls) == 1
    assert tidy_rewrite.make_rewrite(lambda p: "NO")(a, b) is None
    out, rep = tidy.tidy([[L(a, [1]), L(b, [2])]], rewrite=lambda x, y: "Singh met Hegseth in Manila.")
    assert rep["merged"] == 0                                                          # code refuses what changes a fact


def test_conflict_candidates_name_what_is_disputed_and_leave_other_subjects_alone():
    texts = {1: "The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday 28 October 2026.",
             2: "The Union Cabinet approved the Container Manufacturing Promotion Scheme on Thursday 29 October 2026.",
             3: "Rain fell over Kerala on Tuesday.",
             4: "Maximum temperature in Delhi may remain 30 degrees and in Bhopal 28 degrees."}
    got = R.conflict_candidates(texts)
    assert list(got) == [(1, 2)]
    d = got[(1, 2)]
    assert d["kind"] == "date" and len(d["values"]) == 2 and "Cabinet" in d["question"]


def test_conflict_judge_stages():
    from nishpaksh import conflict_judge as C
    punjab = ("Rain will continue in Punjab for 3 days.", "Rain will continue across north India for 5 days.")
    same = ("Police said 12 people were arrested in the raid.", "Police said 14 people were arrested in the raid.")
    calls = []

    def ask(p):
        calls.append(p)
        if "Punjab" in p and p.startswith("Two lines from news"):
            return "SCOPE"
        if "arrested in the raid" in p and p.startswith("Two lines from news"):
            return "EVENT"           # implausible: the lines differ only in the figure
        return "1: x\n2: y"          # not in the lines
    assert C.judge(*punjab, ask)["outcome"] == "different"
    assert C.judge(*same, ask)["outcome"] == "unresolved" and len(calls) == 3   # implausible -> other question -> unverified
    assert C.judge(*same, None)["outcome"] == "unresolved"
    assert C.judge(*same, lambda p: "SAME")["outcome"] == "real"
    ex = ("Four people were killed in the 2024 blast at the mill.", "One person was killed in the 2023 blast at the plant.")
    assert C.judge(*ex, lambda p: "UNSURE" if p.startswith("Two lines from") else "1: the 2024 blast at the mill\n2: the 2023 blast at the plant")["outcome"] == "different"

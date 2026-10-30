"""nishpaksh/insert.py: lines of "Also in these reports" that belong in the article (shadow)."""
from nishpaksh import insert


def L(text, ids, cls="established", sources=(1,)):
    return {"text": text, "ids": list(ids), "class": cls, "sources": list(sources)}


def A(text, id_, role="background", verdict="unverified", speaker=None, sources=()):
    return {"id": id_, "text": text, "role": role, "verdict": verdict, "n_sources": 1, "speaker": speaker, "sources": list(sources)}


PARAS = [
    [L("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday.", [1]),
     L("The scheme aims to build domestic container production for Indian shipping lines.", [2])],
    [L("Container shortages raised freight rates for Indian exporters this year.", [3]),
     L("The Shipping Ministry will run the scheme with an outlay of ₹10,000 crore.", [4])],
    [L("Rain fell over Kerala on Tuesday.", [7]), L("The court heard a plea on Monday.", [8])],       # filler for the weights
]


def run(also):
    return insert.insert([list(p) for p in PARAS], also, "Cabinet approves scheme to boost container production")


def test_a_line_about_the_same_scheme_goes_in_after_its_nearest_line():
    new, rep = run([A("Container manufacturing under the scheme will start with three Indian shipyards.", 10)])
    assert rep["inserted"] == 1
    flat = [x["text"] for p in new for x in p]
    assert any("three Indian shipyards" in t for t in flat)


def test_what_the_article_already_says_another_subject_a_pronoun_and_an_outlets_own_voice_stay_out():
    out = {
        "said": A("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday.", 11),
        "pron": A("She said the ministry would also review the scheme within a year.", 12),
        "other": A("The Cabinet approved the Khelo India Sports Goods Manufacturing Scheme with an outlay of ₹1,856 crore.", 13, "related"),
        "self": A("Satya Hindi is an effort by some journalists to build a newsroom.", 14, speaker="Satya Hindi",
                  sources=[{"outlet": "Satya Hindi"}]),
        "short": A("It was approved.", 15),
    }
    new, rep = run(list(out.values()))
    assert rep["inserted"] == 0, rep["why_not"]
    assert sum(rep["why_not"].values()) == 5


def test_a_clashing_line_is_not_inserted_quietly():
    new, rep = run([A("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Thursday.", 16, "core")])
    assert rep["inserted"] == 0 and any("clash" in k or "already" in k for k in rep["why_not"])


def test_the_inserted_line_keeps_its_own_colour_and_input_is_untouched():
    from nishpaksh.narrative import shade
    before = [[dict(x) for x in p] for p in PARAS]
    new, rep = insert.insert([list(p) for p in PARAS],
                             [A("Container manufacturing under the scheme will start with three Indian shipyards.", 10)], "", shade=shade)
    line = next(x for p in new for x in p if "shipyards" in x["text"])
    assert line["class"] == "single" and "_inserted" not in line
    assert PARAS == before


def test_a_sibling_subject_needs_the_model_and_stays_out_without_it():
    from nishpaksh import insert as I
    paras = [[{"text": "The Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday."},
              {"text": "The scheme will boost domestic container manufacturing in India."}]]
    also = [{"id": 1, "text": "The Cabinet also approved the Khelo India Sports Goods Manufacturing Scheme with an outlay of 1,856 crore rupees.", "role": "related"}]
    _, r = I.insert(paras, also, "Cabinet approves container manufacturing scheme")
    assert r["inserted"] == 0
    _, r = I.insert(paras, also, "Cabinet approves container manufacturing scheme", ask=lambda p: "ANOTHER")
    assert r["inserted"] == 0


# --- Oct 30 2026: the first day of shadow samples (an event is who + what + where + WHEN) ----------------------------
import datetime as dt

TODAY = dt.date(2026, 10, 30)


def run_on(also, ref=TODAY):
    return insert.insert([list(p) for p in PARAS], also, "Cabinet approves scheme to boost container production", ref=ref)


def test_a_dated_line_far_from_the_story_is_another_event_and_stays_out_near_dates_and_undated_lines_go_in():
    far = A("Container manufacturing under the scheme will start with three Indian shipyards in August.", 20)
    near = A("Container manufacturing under the scheme will start with three Indian shipyards on 27 October.", 21)
    _, rep = run_on([far])
    assert rep["inserted"] == 0 and any("another time" in k for k in rep["why_not"])
    _, rep = run_on([near])                                # near the day it is written: the time gate passes it (the place decides the rest)
    assert not any("another time" in k for k in rep["why_not"])
    _, rep = run_on([far], ref=None)                       # no day to compare with: the question has no answer
    assert not any("another time" in k for k in rep["why_not"])


def test_a_story_that_gives_its_own_old_date_makes_a_line_of_that_date_compatible():
    paras = [[L("The scheme was first announced in August after the shipping crisis.", [1]),
              L("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday.", [2])],
             [L("The Shipping Ministry will run the scheme with an outlay of ₹10,000 crore.", [4])]]
    new, rep = insert.insert(paras, [A("Container manufacturing under the scheme will start with three Indian shipyards in August.", 22)],
                             "Cabinet approves container scheme", ref=TODAY)
    assert rep["inserted"] == 1


def test_a_line_that_repeats_one_inserted_in_the_same_run_is_left_out():
    a = A("Container manufacturing under the scheme will start with three Indian shipyards.", 30)
    b = A("Container manufacturing under the scheme will start with three Indian shipyards, officials said.", 31)
    filler = [[L("Rain fell over Kerala on Tuesday.", [51]), L("The court heard a plea on Monday.", [52])],
              [L("Markets closed higher on Wednesday after the budget.", [53]), L("The league match ended in a draw at Pune.", [54])]]
    _, rep = insert.insert([list(p) for p in PARAS] + filler, [a, b], "Cabinet approves scheme to boost container production", ref=TODAY)
    assert rep["inserted"] == 1 and rep["why_not"].get("repeats a line inserted in this run") == 1


def test_a_line_tied_only_by_common_words_that_brings_new_names_is_a_sibling_and_stays_out():
    sib = A("The scheme resembles the Sagarmala Shipbuilding Programme run by the Gujarat Maritime Board with Kandla port.", 40)
    _, rep = run_on([sib])
    assert rep["inserted"] == 0


def test_a_weekday_or_tomorrow_has_no_anchor_in_another_article_unless_the_article_uses_it():
    line = "The Chief Minister will visit the container shipyards of the scheme on Thursday afternoon."
    assert insert.anchor_problem(line, ["The scheme was approved on Wednesday.", "Rain fell."]) is not None
    assert insert.anchor_problem(line, ["The Chief Minister reached the shipyards on Thursday."]) is None
    assert insert.anchor_problem("The scheme was launched on 27 October with three shipyards.", ["Rain fell."]) is None     # a date is anchored
    assert insert.anchor_problem("Three shipyards will start container manufacturing under the scheme.", ["Rain fell."]) is None
    _, rep = run_on([A("The Chief Minister will visit the container manufacturing shipyards of the scheme on Thursday afternoon.", 60)])
    assert rep["inserted"] == 0 and any("no anchor" in k for k in rep["why_not"])

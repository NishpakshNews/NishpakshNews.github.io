"""Matching across the forms Hindi- and English-sourced lines write the same fact in (Oct 16 2026 audit)."""
from nishpaksh.relate import relate


def test_currency_words_and_lower_case_names_are_one_fact():
    a = "The assistance under the Divyangjan Pension Scheme will be Rs 375 for the age group 0-79 years."
    b = "The assistance under the divyangjan pension scheme will be 375 rupees for the age group 0-79 years."
    assert relate(a, b) == "same"
    assert relate("The fee is ₹2,000 per transaction.", "The fee is Rs 2,000 per transaction.") == "same"


def test_different_facts_stay_apart():
    assert relate("The 2022 law increased the SC quota from 15 per cent to 17 per cent.",
                  "The 2022 law increased the ST quota from 3 per cent to 7 per cent.") == "different"
    assert relate("Himanta Sarma said the flood was severe.", "Rahul Sharma said the flood was severe.") == "different"
    assert relate("The fee is Rs 2,000.", "The fee is Rs 3,000.") == "different"


def test_a_clock_time_is_extra_detail_not_a_different_number_or_name():
    a = "Modi will inaugurate five projects worth 3,350 crore rupees via video conferencing on October 15."
    b = "Modi will inaugurate five projects worth Rs 3,350 crore via video conferencing on October 15 at 12:30 PM."
    assert relate(a, b) == "ask_b_covers_a"                  # the timed line may stand for both; the model decides
    assert relate("The meeting began at 10 am.", "The meeting began at 4 pm.") == "different"
    assert relate("The meeting began at 4 pm.", "The meeting began at 4 p.m.") == "same"


def test_one_result_however_it_is_worded():
    """Oct 16 2026: an express page wrote one match result twice ("defeated" / "overcame ... 21-8, 21-11")."""
    from nishpaksh import relate as R
    a = "Suhas LY defeated Joytu Dhar in the men's singles SL4 Group E opener on Friday."
    b = "Suhas LY overcame Joytu Dhar with scores of 21-8 and 21-11 during Friday's men's singles SL4 Group E match."
    c = "Manasi Joshi and Ruthick Raghupati lost to Khalimatus Sadiyah and Fredy Setiawan in the mixed doubles SL3-SU5 competition on Friday."
    d = "Khalimatus Sadiyah and Fredy Setiawan defeated Manasi Joshi and Ruthick Raghupati 21-15, 21-4 in their group fixture on Friday."
    assert R.relate(a, b) == "b_covers_a" and R.relate(c, d) == "b_covers_a"
    assert R.relate(a, "Joytu Dhar defeated Suhas LY in the men's singles on Friday.") == "different"
    assert R.relate("India beat Pakistan by 19 runs in the final.", "On Saturday, India defeated Pakistan by 19 runs in the final.") == "same"
    assert R.relate("India beat Pakistan by 19 runs in the final.", "India beat Pakistan by 25 runs in the final.") != "same"
    assert R.relate("India beat Pakistan in the hockey semifinal.", "India beat Pakistan in the cricket final.") not in ("same", "a_covers_b", "b_covers_a")


def test_blocking_keeps_a_story_of_any_size_close_pairs():
    from nishpaksh import relate
    texts = {i: f"Topic number {i} was discussed by the committee in district {i} on day {i}" for i in range(200)}
    texts[500] = "Police arrested 17 men near the Kalka bridge"
    texts[501] = "Police arrested 17 men near the Kalka bridge on Sunday"
    prof = {i: relate.Profile(t) for i, t in texts.items()}
    cand = relate.blocks(texts, prof)
    assert (500, 501) in cand
    assert len(cand) < 202 * 201 // 2                       # far fewer pairs than all of them
    same, covered, ask, ask_cover = relate.group(texts)
    assert (500, 501) in same or covered or ask or ask_cover


def test_time_is_a_soft_level_for_identical_words():
    from nishpaksh.relate import relate
    t = "Five people died in the stampede at the Bharat temple"
    sat = {"start": "2026-10-17", "end": "2026-10-17", "precision": "day"}
    sun = {"start": "2026-10-18", "end": "2026-10-18", "precision": "day"}
    mon = {"start": "2026-10-24", "end": "2026-10-24", "precision": "day"}
    assert relate(t, t, sat, sun) == "ask"            # one day apart, same words: the question decides, never code
    assert relate(t, t, sat, mon) == "different"       # a week apart: another event
    assert relate(t, t, sat, sat) == "same"


def test_a_different_place_for_the_same_action_is_proposed_as_a_conflict():
    from nishpaksh.frames import compare
    base = {"who": "Police", "action": "arrest", "what": "five men", "value": "", "negated": False}
    assert compare(dict(base, where="Pune"), dict(base, where="Mumbai")) == "conflict"
    assert compare(dict(base, where="Delhi"), dict(base, where="New Delhi")) != "conflict"
    assert compare(dict(base, where=""), dict(base, where="Mumbai")) != "conflict"


def test_normalise_makes_written_forms_equal():
    from nishpaksh.relate import normalise
    assert normalise("Fee is Rs. 375") == normalise("Fee is Rs 375") == normalise("Fee is ₹375")
    assert normalise("a rise of 10 per cent") == normalise("a rise of 10 percent") == normalise("a rise of 10%")
    assert normalise("Between 10 and 12 people") == normalise("10-12 people") == normalise("10–12 people")
    assert normalise("The  minister\u2019s plan") == normalise("The minister\u2019s plan")

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

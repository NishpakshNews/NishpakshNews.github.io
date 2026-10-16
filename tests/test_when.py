"""Dates and times read by code (nishpaksh/when.py). No database."""
import datetime as dt

from nishpaksh import when as w

PUB = dt.datetime(2026, 10, 15, 4, 0)        # UTC: Thursday 15 October 2026, 09:30 IST


def r(words, future=None, **kw):
    x = w.resolve(words, PUB, future=future, **kw)
    return x and (x["start"], x["end"], x["precision"])


def test_weekdays_and_relative_days_are_counted_from_the_report():
    assert r("Tuesday night") is None                # last Tuesday or next: the tense must say
    assert r("Tuesday night", future=False) == ("2026-10-13T18:00", "2026-10-13T23:59", "part_of_day")
    assert r("on Thursday", future=False) == ("2026-10-15T00:00", "2026-10-15T23:59", "day")
    assert r("on Friday", future=True)[0] == "2026-10-16T00:00"
    assert r("yesterday")[0] == "2026-10-14T00:00" and r("tonight")[2] == "part_of_day"
    assert r("last week")[:2] == ("2026-10-05T00:00", "2026-10-11T23:59")


def test_dates_in_every_form_and_both_languages():
    for words in ("October 15", "Oct. 15, 2026", "15th of October", "15 October", "15/10/2026", "15 अक्टूबर",
                  "१५ अक्टूबर", "Thursday, 15 October", "15 October this year"):
        assert r(words)[0] == "2026-10-15T00:00", words
    assert r("from October 17 to 22")[:2] == ("2026-10-17T00:00", "2026-10-22T23:59")
    assert r("17 से 22 अक्टूबर")[:2] == ("2026-10-17T00:00", "2026-10-22T23:59")
    assert r("July 2026")[2] == "month" and r("in 2019")[2] == "year"


def test_a_date_with_no_year_takes_the_year_the_tense_allows():
    assert r("28 December", future=False)[0] == "2025-12-28T00:00"
    assert r("28 December", future=True)[0] == "2026-12-28T00:00" and r("28 December")[0] == "2026-12-28T00:00"
    assert r("9 October", future=True) is None        # the next 9 October is a year away: refused, not 2027


def test_clock_times():
    assert r("October 14 at 12:30 PM") == ("2026-10-14T12:30", "2026-10-14T12:30", "exact")
    assert r("शाम 5 बजे, 14 अक्टूबर")[:1] == ("2026-10-14T17:00",)
    # another time zone is never converted: the day stays, the hour goes
    assert r("9 am local time on Tuesday", future=False)[2] == "day"


def test_never_guessed():
    assert r("कल") is None                         # yesterday or tomorrow: only the tense says
    assert r("कल", future=True)[0] == "2026-10-16T00:00"
    assert r("Monday, October 15") is None         # the 15th is a Thursday: two answers, none taken
    assert r("12:30 PM") is None                   # a time with no day
    assert r("24 hours") is None and r("Diwali") is None
    assert r("may 20 people") is None              # a verb, not a month
    # bounds and several dates are the model's to place (the audit's mistakes of code's first version)
    for words in ("quarter ended September 30, 2026", "October 2022 and February 6, 2026", "until October 17",
                  "April-September 2026", "11 and 12 December", "overnight before the morning of 15 October 2026"):
        assert r(words) is None, words
    assert r("December last year")[:2] == ("2025-12-01T00:00", "2025-12-31T23:59")
    assert r("1 November this year")[0] == "2026-11-01T00:00"


def test_reading_keeps_codes_dates_and_refuses_impossible_model_dates():
    w.STATS.clear()
    assert w.tense("Police arrested two men") is False and w.tense("The meeting is on Thursday") is None
    assert w.tense("He said the court will hear it") is None and w.tense("The court will hear it") is True
    t = w.read_time({"when_text": "Tuesday night", "start": "2026-10-14T18:00", "end": "2026-10-14T23:59",
                     "precision": "part_of_day"}, "Police arrested two men", PUB)
    assert t["start"] == "2026-10-13T18:00" and t["by"] == "code"
    t = w.read_time({"when_text": "on Diwali", "start": "2026-11-08T00:00", "precision": "day"}, "Lamps were lit", PUB)
    assert t["start"] is None and t["precision"] == "unknown"
    t = w.read_time({"when_text": "on Diwali", "start": "2026-11-08T00:00", "precision": "day"}, "Lamps will be lit", PUB)
    assert t["start"] == "2026-11-08T00:00" and t["by"] == "model"
    assert w.STATS == {"code_differs": 1, "model_refused": 1, "model_only": 1}


def test_date_of_keeps_the_old_contract():
    assert w.date_of("6 December 1986") == (1986, 12, 6) == w.date_of("1986-12-06")
    assert w.date_of("July 2026") == (2026, 7, None) and w.date_of("31st October") == (None, 10, 31)
    assert w.date_of("15 अक्टूबर") == (None, 10, 15) and w.date_of("in may 20 cases") is None
    assert w.date_values("17-22 October 2026") == [(2026, 10, 17), (2026, 10, 22)]


def test_house_dates_only_in_our_text_and_never_in_quotes():
    t = ('On October 15, 2026, the court met. Rubio visits from October 17 to 22. He said "on October 3". '
         'A 15th of October rally; may 20 people; Thursday, Oct. 8.')
    assert w.house_dates(t) == ('On 15 October 2026, the court met. Rubio visits from 17 to 22 October. He said '
                                '"on October 3". A 15 October rally; may 20 people; Thursday, 8 October.')
    assert w.house_dates("15 अक्टूबर को") == "15 अक्टूबर को"
    assert w.forms("October 15 and 15 October") == {"day_first", "month_first"}


def test_hindi_time_words_in_english():
    assert w.english("26 सितंबर") == "26 September" and w.english("मंगलवार रात") == "Tuesday night"
    assert w.english("कल") == "" and w.english("Tuesday") == "Tuesday"

"""A speaker is verified against the reports' own attributions or the statement's own words (speakers.py)."""
from nishpaksh import speakers


def test_the_placeholder_is_never_a_speaker():
    assert speakers.verify("article", {"article"}, "Evacuations will begin.") is None
    assert speakers.verify("the article", {"India Meteorological Department"}, "Evacuations will begin.") is None


def test_a_speaker_the_reports_gave_stands():
    assert speakers.verify("India Meteorological Department", {"India Meteorological Department", "article"},
                           "A red alert was issued.") == "India Meteorological Department"
    assert speakers.verify("senior official", {"a senior state disaster management official"}, "x") == "senior official"


def test_an_invented_speaker_is_dropped():
    assert speakers.verify("Defence Minister", {"article"}, "The storm will land on Wednesday.") is None

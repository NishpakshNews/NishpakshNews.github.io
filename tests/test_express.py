"""Express lane, part 1 (express.py, config/express.yaml): the door in code. No database, no model."""
from nishpaksh import express


def out(title, lead="", url="", lane=None):
    return express.excluded(title, lead, url, lane)


def test_config_is_sane():
    c = express.cfg()
    assert c["enabled"] is True
    assert set(express.lanes()) == {"companies", "sport", "entertainment", "tech"}   # round one: no economy, markets, health
    for name, lane in express.lanes().items():
        assert lane.get("label") and lane.get("describe"), name
    # every list named in `apply` exists, every list has a rule
    assert set(c["apply"]) <= set(c["exclude"])
    assert set(c["exclude"]) <= set(c["apply"])
    assert c["embed_daily_cap"] == 400


def test_plain_announcements_pass():
    assert out("Tata Motors opens new plant in Pune", lane="companies") is None
    assert out("India beat Australia by six wickets in second ODI", lane="sport") is None
    assert out("Netflix announces release date for new Hindi series", lane="entertainment") is None
    assert out("OnePlus launches Nord 5 with 6,000mAh battery at Rs 29,999", lane="tech") is None
    assert out("Infosys appoints new chief people officer", lane="companies") is None


def test_harm_is_excluded_in_every_lane():
    for lane in (None, "companies", "sport", "entertainment", "tech"):
        assert out("Founder arrested over funds diversion", lane=lane).startswith("harm:")
        assert out("Cricketer dies at 34", lane=lane).startswith("harm:")
        assert out("Actor accused of cheating producer", lane=lane).startswith("harm:")
        assert out("Bus crash kills six", lane=lane).startswith("harm:")
    assert out("शाहरुख खान के घर के बाहर हादसा").startswith("harm:")


def test_government_and_markets_are_company_matters():
    assert out("RBI imposes penalty on private bank", lane="companies").startswith("government:")
    assert out("Adani Group says ministry approved port expansion", lane="companies").startswith("government:")
    assert out("Reliance shares surge after quarterly results", lane="companies").startswith("market:")
    assert out("Sensex jumps 400 points as IT stocks rally", lane="companies").startswith("market:")
    # but "rally" is a tennis word and "surge" a sport word: markets do not apply to sport
    assert out("Sinner wins a long rally to take the set", lane="sport") is None
    # and with no lane known, only the all-lane lists are used
    assert out("Reliance shares surge after quarterly results", lane=None) is None


def test_agencies_are_matched_as_written_not_as_names():
    assert out("ED raids offices of builder", lane="companies") is not None
    assert out("Ed Sheeran announces India tour dates", lane="entertainment") is None
    assert out("Ed Sheeran announces India tour dates", lane=None) is None


def test_gossip_and_box_office_only_in_entertainment():
    assert out("Actor and singer dating, say fans", lane="entertainment").startswith("gossip:")
    assert out("Film earns Rs 50 crore on opening day", lane="entertainment").startswith("gossip:")
    assert out("Pakistan clash with India set for Sunday", lane="sport") is None       # a clash is a match in sport


def test_speculation_is_excluded_everywhere():
    assert out("Apple reportedly working on foldable iPhone", lane="tech").startswith("speculation:")
    assert out("Leaked images show next Galaxy design", lane="tech").startswith("speculation:")
    assert out("Kohli likely to miss first Test", lane="sport").startswith("speculation:")
    assert out("Tata in talks to buy chip firm", lane="companies").startswith("speculation:")
    assert out("Dream11 prediction for India vs England", lane="sport") is not None


def test_may_the_month_is_not_a_doubt():
    assert out("Sales rose in May for the third month", lane="companies") is None
    assert out("Event on May 12 in Mumbai", lane="companies") is None
    assert out("Apple May launch a cheaper iPad", lane="tech").startswith("speculation:")
    assert out("It may rain in Pune on match day", lane="sport").startswith("speculation:")


def test_sport_court_is_not_the_courts():
    assert out("Sindhu stays on court for 90 minutes, wins", lane="sport") is None
    assert out("Centre Court crowd sees Alcaraz win", lane="sport") is None
    assert out("Federation moves court against ban", lane="sport").startswith("harm:")


def test_service_pieces_listicles_and_opinion_urls():
    assert out("Gold rate today in Delhi", lane="companies") is not None
    assert out("IPL 2027 live score and updates", lane="sport").startswith("service:")
    assert out("10 best phones under Rs 20,000 in India", lane="tech") is not None
    assert out("Top 5 web series to watch this weekend", lane="entertainment") is not None
    assert out("Tata Motors opens new plant", url="https://x.com/opinion/tata-plant-123", lane="companies") == "url:opinion"
    assert out("Tata Motors opens new plant", url="https://x.com/photogallery/tata", lane="companies") == "url:photogallery"
    # cricket's "top order" and "career-best" are not listicles
    assert out("Top order collapses as India lose by 20 runs", lane="sport") is None
    assert out("Gill hits career-best 150 in Mohali", lane="sport") is None


def test_the_lead_counts_too():
    assert out("Startup announces new funding", "The founder was arrested last year over a fraud case.",
               lane="companies").startswith("harm:")


def test_reason_group():
    assert express.reason_group("harm:arrested") == "harm"
    assert express.reason_group(None) is None

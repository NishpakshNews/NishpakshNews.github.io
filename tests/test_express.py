"""Express lane, part 1 (express.py, config/express.yaml): the door. No database. The model is the scripted stand-in of
conftest (`_RISK_WORDS`): it says whether a headline fits each concern DEFINITION; the real model's reading of the same
sentences is what the audit (`express_replay`) checks on stored headlines."""
from nishpaksh import express, nli, risk


def out(title, lead="", url="", lane=None):
    return express.excluded(title, lead, url, lane)


def test_config_is_sane():
    c = express.cfg()
    assert c["enabled"] is True
    assert set(express.lanes()) == {"companies", "sport", "entertainment", "tech"}   # round one: no economy, markets, health
    for name, lane in express.lanes().items():
        assert lane.get("label") and lane.get("describe"), name
    # every concern has a rule and at least one definition; every definition is a sentence
    assert set(c["apply"]) == set(c["concerns"])
    for name, keys in c["concerns"].items():
        assert keys, name
        assert all(isinstance(s, str) and len(s.split()) >= 5 for s in keys.values()), name
    assert 0.0 < c["concern_min"] <= 1.0
    assert c["embed_daily_cap"] == 400
    assert "exclude" not in c and "patterns" not in c and "allow_phrases" not in c and "media_words" not in c    # no word lists


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


def test_the_reason_names_the_definition_that_fired():
    assert out("Founder arrested over funds diversion", lane="companies") == "harm:crime"
    assert out("Cricketer dies at 34", lane="sport") == "harm:death"


def test_a_concern_counts_only_in_its_lanes():
    assert out("RBI imposes penalty on private bank", lane="companies").startswith("government:")
    assert out("Reliance shares surge after quarterly results", lane="companies").startswith("market:")
    assert out("Sensex jumps 400 points as IT stocks rally", lane="tech").startswith("market:")
    assert out("Sinner wins a long rally to take the set", lane="sport") is None          # markets do not apply to sport
    assert out("Reliance shares surge after quarterly results", lane=None) is None        # no lane known: only the all-lane concerns
    assert out("Actor and singer dating, say fans", lane="entertainment").startswith("gossip:")
    assert out("Actor and singer dating, say fans", lane="sport") is None


def test_speculation_service_and_gossip():
    assert out("Apple reportedly working on foldable iPhone", lane="tech").startswith("speculation:")
    assert out("Kohli likely to miss first Test", lane="sport").startswith("speculation:")
    assert out("IPL 2027 live score and updates", lane="sport").startswith("service:")
    assert out("10 best phones under Rs 20,000 in India", lane="tech").startswith("service:")
    assert out("Film earns Rs 50 crore on opening day", lane="entertainment").startswith("gossip:")


def test_the_meaning_decides_not_the_word():
    # the same word, two meanings: the month and the verb; a court of law and a court of play
    assert out("Sales rose in May for the third month", lane="companies") is None
    assert out("It may rain in Pune on match day", lane="sport").startswith("speculation:")
    assert out("Sindhu stays on court for 90 minutes, wins", lane="sport") is None
    assert out("Federation moves court against ban", lane="sport").startswith("harm:")
    assert out("Ed Sheeran announces India tour dates", lane="entertainment") is None


def test_the_lead_counts_too():
    assert out("Startup announces new funding", "The founder was arrested last year over a fraud case.",
               lane="companies").startswith("harm:")


def test_url_pieces_are_structure_not_words():
    assert out("Tata Motors opens new plant", url="https://x.com/opinion/tata-plant-123", lane="companies") == "url:opinion"
    assert out("Tata Motors opens new plant", url="https://x.com/photogallery/tata", lane="companies") == "url:photogallery"


def test_no_model_means_unread_never_fine():
    nli.set_backend(lambda pairs: [None] * len(pairs))
    assert out("Tata Motors opens new plant in Pune", lane="companies") is risk.UNREAD
    assert not risk.UNREAD                                                      # falsy, but not None
    assert out("Tata Motors opens new plant", url="https://x.com/opinion/a", lane="companies") == "url:opinion"   # the URL needs no model


def test_one_definition_that_fires_is_enough_even_if_another_cannot_be_read():
    def partial(pairs):
        return [None if "court" in h else (0.9, 0.05, 0.05) if "accused" in h else (0.05, 0.9, 0.05) for _p, h in pairs]
    nli.set_backend(partial)
    assert out("Anything at all", lane="sport") == "harm:accusation"


def test_many_headlines_are_asked_in_one_batch():
    calls = []
    inner = nli._backend

    def spy(pairs):
        calls.append(len(pairs))
        return inner(pairs)
    nli.set_backend(spy)
    got = express.excluded_many([("Founder arrested", "", "", "companies"), ("Tata opens plant", "", "", "companies"),
                                 ("Tata opens plant", "", "", "companies")])
    assert got[0] == "harm:crime" and got[1] is None and got[2] is None
    assert len(calls) == 1                                                      # one batch (cache removes the repeated pair)


def test_reason_group():
    assert express.reason_group("harm:crime") == "harm"
    assert express.reason_group(None) is None


def test_empty_text_is_not_excluded():
    assert out("", "", "", "sport") is None

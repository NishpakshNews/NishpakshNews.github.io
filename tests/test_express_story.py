"""Express lane, part 3 (express.py: the express story, its named origin, the wait) as plain logic: no database, no
model. The database-backed parts (candidates, reading cap, assess) are in test_express_story_db.py."""
import datetime as dt
import sys
import types

from nishpaksh import express

try:                      # the real word lists when the whole package imports; a small stand-in otherwise
    import nishpaksh.origins  # noqa: F401
except ImportError:
    stub = types.ModuleType("nishpaksh.origins")
    stub.OWN_WORDS = {"", "article", "the article", "report", "reporter"}
    stub.ANON_WORDS = {"sources", "unnamed sources", "people familiar", "officials", "analysts", "witnesses"}
    stub.AGENCIES = {"pti": "pti", "ani": "ani"}
    stub._norm = lambda s: " ".join((s or "").lower().replace(".", " ").split())
    sys.modules["nishpaksh.origins"] = stub

NOW = dt.datetime(2026, 10, 13, 12, 0)


def ev(att, stance="asserts", kind="event"):
    return {"kind": kind, "stance": stance, "attributed_to": att}


def yes(lane="companies"):
    return {"title": "Tata Motors opens plant", "url": "https://x/a", "extraction": {"express": {"v": 1, "verdict": "yes", "lane": lane, "sig": "india"}}}


def test_how_an_attribution_reads():
    assert express.attribution_kind("") == "own"
    assert express.attribution_kind("Tata Motors") == "named"
    assert express.attribution_kind("Chief Executive Ratan Mehta") == "named"
    assert express.attribution_kind("unnamed sources") == "anon"
    assert express.attribution_kind("people familiar") == "anon"
    assert express.attribution_kind("PTI") == "agency"


def test_another_media_house_is_not_an_origin(monkeypatch):
    monkeypatch.setattr(express, "cfg", lambda: {"media_words": ["bloomberg", "report"]})
    assert express.attribution_kind("Bloomberg") == "media"
    assert express.attribution_kind("a Bloomberg report") == "media"
    assert express.attribution_kind("Tata Motors") == "named"


def test_a_named_event_qualifies_and_an_unnamed_one_does_not():
    assert express.origin_verdict([ev("Tata Motors")], "companies") == (True, "named")
    assert express.origin_verdict([ev("Tata Motors"), ev("")], "companies") == (True, "named")   # own-voice detail beside a named lead
    assert express.origin_verdict([ev("Tata Motors"), ev("unnamed sources")], "companies") == (False, "anonymous_source")
    assert express.origin_verdict([ev("PTI")], "companies") == (False, "agency_source")
    assert express.origin_verdict([], "companies") == (False, "no_event")


def test_only_events_count_not_background_or_denials():
    claims = [ev("Tata Motors"), ev("analysts", kind="claim"), ev("sources", stance="denies")]
    assert express.origin_verdict(claims, "companies") == (True, "named")


def test_own_voice_is_enough_for_sport_only(monkeypatch):
    monkeypatch.setattr(express, "cfg", lambda: {"own_voice_lanes": ["sport"]})
    assert express.origin_verdict([ev("")], "sport") == (True, "own_voice")
    assert express.origin_verdict([ev("")], "companies") == (False, "not_named")
    assert express.origin_verdict([ev(""), ev("sources")], "sport") == (False, "anonymous_source")


def test_the_lane_comes_from_the_members_verdicts():
    assert express.story_lane([yes()]) == ("companies", None)
    assert express.story_lane([{"title": "x", "url": "u"}]) == (None, "no_lane")
    assert express.story_lane([yes("sport"), yes("tech")]) == (None, "two_lanes")


def test_a_member_that_is_excluded_or_off_lane_keeps_the_story_out():
    out = {"title": "t", "url": "u", "extraction": {"express": {"v": 1, "verdict": "excluded", "why": "harm:arrested"}}}
    off = {"title": "t", "url": "u", "extraction": {"express": {"v": 1, "verdict": "no", "why": "not_lane"}}}
    assert express.story_lane([yes(), out]) == (None, "member_excluded")
    assert express.story_lane([yes(), off]) == (None, "member_not_lane")
    unreadable = {"title": "t", "url": "u", "extraction": {"express": {"v": 1, "verdict": "no", "why": "unreadable"}}}
    assert express.story_lane([yes(), unreadable]) == ("companies", None)      # an unreadable page says nothing about the topic


def test_an_exclusion_word_in_any_member_headline_keeps_the_story_out():
    arrested = {"title": "Founder arrested over fund diversion", "url": "https://x/b"}
    assert express.story_lane([yes(), arrested]) == (None, "member_excluded")


def test_the_wait_before_writing():
    last = NOW - dt.timedelta(minutes=10)
    met = NOW - dt.timedelta(minutes=30)
    assert express.settle_decision(NOW, last, met, 72, wait_hours=1) is None          # still waiting for a second outlet
    assert express.settle_decision(NOW, last, NOW - dt.timedelta(minutes=61), 72, wait_hours=1) == "express"
    assert express.settle_decision(NOW, last, None, 72, wait_hours=1) is None          # never met the rule
    assert express.settle_decision(NOW, None, met, 72, wait_hours=1) is None
    old = NOW - dt.timedelta(hours=80)
    assert express.settle_decision(NOW, old, NOW - dt.timedelta(hours=79), 72, wait_hours=1) is None   # stale: not written


def test_the_writer_is_told_a_companys_claim_is_its_own_claim_outside_sport():
    assert express.writer_note({"qualified_by": "express", "express_lane": "companies"}) == express.WRITER_NOTE
    assert express.writer_note({"qualified_by": "express", "express_lane": "tech"}) == express.WRITER_NOTE
    assert express.writer_note({"qualified_by": "express", "express_lane": "sport"}) == ""
    assert express.writer_note({"qualified_by": "interim", "express_lane": "companies"}) == ""
    assert express.writer_note({}) == ""


def test_the_strict_order_of_the_beat_seats():
    assert express.order() == ["companies", "tech", "domains", "sport", "entertainment"]
    t = express.tier
    assert t("companies", None) < t(None, "domains")
    assert t("tech", None) < t(None, "domains") < t(None, "sport") == t("sport", None) < t("entertainment", None)
    assert t(None, "domains") < t("sport", "domains")           # an express story ranks by its lane, not its desk
    assert t(None, None) == t(None, "other") == len(express.order())


def test_reading_goes_one_story_per_lane_in_turn_so_a_quiet_lane_is_not_crowded_out():
    def c(lane, minutes, sig="india"):
        return {"lane": lane, "sig": sig, "newest": NOW - dt.timedelta(minutes=minutes)}
    unread = {1: c("sport", 1), 2: c("sport", 2), 3: c("sport", 3), 4: c("entertainment", 4),
              5: c("tech", 50), 6: c("companies", 90)}
    assert express._reading_order(unread, 3) == [6, 5, 1]       # companies, tech, then the newest sport
    assert express._reading_order(unread, 6) == [6, 5, 1, 4, 2, 3]
    only = {1: c("entertainment", 1), 2: c("sport", 9, "world"), 3: c("sport", 8, "india")}
    assert express._reading_order(only, 3) == [3, 1, 2]         # sport first; inside it India before "world"


def test_a_member_judged_not_significant_keeps_the_story_out_and_the_sig_of_a_story_is_the_best_of_its_members():
    no = {"title": "t", "url": "u", "extraction": {"express": {"v": 1, "verdict": "no", "why": "not_significant", "lane": "sport"}}}
    assert express.story_lane([yes("sport"), no]) == (None, "member_not_significant")
    a = {"extraction": {"express": {"v": 1, "verdict": "yes", "lane": "sport", "sig": "world"}}}
    b = {"extraction": {"express": {"v": 1, "verdict": "yes", "lane": "sport", "sig": "india"}}}
    assert express.story_sig([a]) == "world" and express.story_sig([a, b]) == "india"
    old = {"title": "Tata Motors opens plant", "url": "https://x/a", "extraction": {"express": {"v": 1, "verdict": "yes", "lane": "companies"}}}
    assert express.story_lane([old]) == (None, "no_lane")        # a "yes" from before the question never met the bar

"""Express lane, part 2 (express.py: intake, headline question, verdicts, embedding slice) as plain logic.

No database and no model: the database touches (`lane_feeds`, `embed_allowance`, `_save`) are replaced by fakes, the
model by a fake router. The database-backed run through grouping is in test_express_db.py."""
import datetime as dt
import json
import re

from nishpaksh import express

NOW = dt.datetime(2026, 10, 12, 12, 0)
HT_BUSINESS = "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml"
HT_SPORTS = "https://www.hindustantimes.com/feeds/rss/sports/rssfeed.xml"
HT_INDIA = "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"


class Res:
    def __init__(self, data):
        self.data = data


class FakeRouter:
    """Answers the lane question by keyword: wickets -> sport, plant -> companies, launches -> tech, else none.
    Records every prompt; `flip` makes the answers of the SECOND question differ (a wavering model)."""

    def __init__(self, flip=(), skip=(), fail=False, sig_none=("injur",)):
        self.prompts, self.flip, self.skip, self.fail = [], set(flip), set(skip), fail
        self.sig_prompts, self.sig_none = [], tuple(sig_none)

    def call(self, tier, prompt, json_out=True, max_output_tokens=0, **kw):
        if self.fail:
            from nishpaksh.router import QuotaExhausted
            raise QuotaExhausted(tier)
        if "NEEDS to know" in prompt:               # the significance question: india unless the headline says injury
            self.sig_prompts.append(prompt)
            rows = re.findall(r"^(\d+)\. \[\w+\] (.*)$", prompt.split("If you are not sure")[1], re.M)
            return Res({"results": [{"n": int(n), "class": "none" if any(w in t.lower() for w in self.sig_none) else "india"}
                                    for n, t in rows]})
        self.prompts.append(prompt)
        asking = len(self.prompts)
        res = []
        lines = prompt.split("\n\n")[-2].split("\n")
        for line in lines:
            n, _, title = line.partition(". ")
            if not n.isdigit() or any(s in title for s in self.skip):
                continue
            t = title.lower()
            lane = "sport" if "wickets" in t else "companies" if "plant" in t else "tech" if "launches" in t else "none"
            if lane != "none" and asking > 1 and any(f in title for f in self.flip):
                lane = "entertainment"
            res.append({"n": int(n), "lane": lane})
        return Res({"results": res})


def art(i, title, feed=1, text="Full report text. " * 40, hours=1, source="full", extraction=None):
    return dict(id=i, title=title, feed_id=feed, text=text, text_source=source, extracted_at=None, embedding=None,
                published_at=NOW - dt.timedelta(hours=hours), url=f"https://x/{i}", extraction=extraction)


def setup(monkeypatch, allowance=100, left=400, lane_of=None):
    saved = {}
    express.reset()
    monkeypatch.setattr(express, "lane_feeds", lambda store: lane_of or {1: "companies", 2: "sport"})
    monkeypatch.setattr(express, "embed_allowance", lambda store, now=None: (allowance, left))
    monkeypatch.setattr(express, "_save", lambda store, verdicts: saved.update(verdicts))
    return saved


# --- intake -------------------------------------------------------------------------------------------------------

def test_lane_feeds_are_found_by_url_and_untagged_feeds_are_not():
    assert express.lane_of_url(HT_BUSINESS) == "companies"
    assert express.lane_of_url(HT_SPORTS) == "sport"
    assert express.lane_of_url(HT_INDIA) is None
    assert not express.skip_feed(HT_BUSINESS) and not express.skip_feed(HT_INDIA)


def test_a_lane_feed_is_skipped_while_the_lane_is_off(monkeypatch):
    monkeypatch.setattr(express, "enabled", lambda: False)
    assert express.skip_feed(HT_BUSINESS)            # never read, so never mixed into politics grouping
    assert not express.skip_feed(HT_INDIA)


def test_intake_keeps_main_feeds_whole_and_excludes_before_fetching():
    express.reset()
    f_main = {"id": 10, "url": HT_INDIA, "name": "HT"}
    f_biz = {"id": 11, "url": HT_BUSINESS, "name": "HT"}
    todo = [(f_main, {"title": "Minister arrested", "summary": "", "url": "u1"}),
            (f_biz, {"title": "Tata Motors opens new plant in Pune", "summary": "", "url": "u2"}),
            (f_biz, {"title": "Founder arrested over fund diversion", "summary": "", "url": "u3"}),
            (f_biz, {"title": "Adani says ministry approved the port", "summary": "", "url": "u4"})]
    rest, mine = express.take_intake(todo)
    assert [en["url"] for _, en in rest] == ["u1"]                    # politics intake untouched (no express rule)
    assert [en["url"] for _, en in mine] == ["u2"]
    assert express.STATS["taken"] == 1 and express.STATS["intake_excluded"] == 2
    assert express.STATS["excluded"] == {"harm": 1, "government": 1}
    assert express.STATS["excluded_terms"]["harm:crime"] == 1


def test_intake_caps_per_feed_and_per_run(monkeypatch):
    express.reset()
    monkeypatch.setattr(express, "setting", lambda k, d=None: {"intake_per_feed": 2, "intake_per_run": 3}.get(k, d))
    f1, f2 = {"id": 1, "url": HT_BUSINESS}, {"id": 2, "url": HT_SPORTS}
    todo = [(f1, {"title": f"Tata opens plant {i}", "summary": "", "url": f"a{i}"}) for i in range(4)] + \
           [(f2, {"title": f"India win by {i} wickets", "summary": "", "url": f"b{i}"}) for i in range(4)]
    _, mine = express.take_intake(todo)
    assert [en["url"] for _, en in mine] == ["a0", "a1", "b0"]       # 2 from the first feed, then the run's 3
    assert express.STATS["intake_over_cap"] == 5


def test_intake_does_nothing_when_the_lane_is_off(monkeypatch):
    monkeypatch.setattr(express, "enabled", lambda: False)
    todo = [({"id": 1, "url": HT_BUSINESS}, {"title": "x", "summary": "", "url": "u"})]
    assert express.take_intake(todo) == (todo, [])


# --- the headline question -------------------------------------------------------------------------------------

def test_prompt_lists_the_lanes_the_examples_and_the_headlines():
    p = express._prompt(["India beat Australia by six wickets", "Tata opens plant"])
    assert '"sport" -' in p and '"companies" -' in p and '"none" -' in p
    assert "1. India beat Australia" in p and "2. Tata opens plant" in p
    assert "If you are not sure" in p and "-> none (a crime case)" in p


def test_a_lane_needs_the_same_answer_twice_and_the_second_ask_is_reversed():
    r = FakeRouter(flip=["wickets-flip"])
    items = [art(1, "India win by six wickets"), art(2, "Weather office forecasts showers"),
             art(3, "Tata opens new plant in Pune"), art(4, "India win by two wickets-flip")]
    got = express.lanes_agreed(r, items, 20)
    assert got == {1: "sport", 2: "none", 3: "companies", 4: "none"}     # 4: the second answer named another lane
    assert len(r.prompts) == 2
    second = r.prompts[1]
    assert second.index("Tata opens new plant") < second.index("India win by six wickets")   # reversed order
    assert "Weather office" not in second                       # the second time only headlines that got a lane


def test_a_headline_the_model_did_not_answer_is_left_undecided():
    r = FakeRouter(skip=["Tata"])
    got = express.lanes_agreed(r, [art(1, "India win by six wickets"), art(2, "Tata opens new plant")], 20)
    assert got == {1: "sport"}


def test_no_quota_decides_nothing():
    assert express.lanes_agreed(FakeRouter(fail=True), [art(1, "India win by six wickets")], 20) == {}


# --- the gate --------------------------------------------------------------------------------------------------

def test_gate_passes_a_lane_headline_and_keeps_the_rest_out(monkeypatch):
    saved = setup(monkeypatch)
    arts = [art(1, "India win by six wickets", feed=2),                 # passes
            art(2, "Weather office forecasts light showers", feed=1),          # not a lane
            art(3, "Founder arrested over fraud", feed=1),              # code exclusion, never asked
            art(4, "Tata opens plant", feed=1, source="summary"),       # headline-only page: option B
            art(5, "Some political story", feed=99)]                    # not an express feed: untouched
    r = FakeRouter()
    held, first = express.gate(None, r, arts, NOW)
    assert first == {1} and held == {2, 3, 4}
    assert saved[1]["verdict"] == "yes" and saved[1]["lane"] == "sport"
    assert saved[2]["verdict"] == "no" and saved[2]["why"] == "not_lane"
    assert saved[3]["verdict"] == "excluded" and saved[3]["why"].startswith("harm:")
    assert saved[4]["why"] == "unreadable" and 5 not in saved
    s = express.STATS
    assert (s["asked"], s["passed"], s["not_lane"], s["unreadable"], s["passed_sport"]) == (2, 1, 1, 1, 1)
    assert s["excluded"] == {"harm": 1}
    assert "Founder arrested" not in "".join(r.prompts)                     # an excluded headline reaches no lane model


def test_the_lane_s_own_exclusions_run_after_the_model_names_the_lane(monkeypatch):
    saved = setup(monkeypatch)
    # in a companies feed, but the model calls it tech; a share-price move is a market concern in both lanes
    held, first = express.gate(None, FakeRouter(), [art(1, "Xiaomi launches phone at Rs 20,000 amid rally", feed=1)], NOW)
    assert saved[1]["verdict"] == "excluded" and saved[1]["why"].startswith("market:")     # market concern: companies, tech
    assert held == {1} and first == set()


def test_a_judged_headline_is_not_asked_again(monkeypatch):
    saved = setup(monkeypatch)
    old_no = {"express": {"v": 1, "verdict": "no", "why": "not_lane"}}
    old_yes = {"express": {"v": 1, "verdict": "yes", "lane": "sport", "sig": "india"}}
    r = FakeRouter()
    held, first = express.gate(None, r, [art(1, "x", extraction=old_no), art(2, "y", extraction=old_yes, feed=2)], NOW)
    assert held == {1} and first == {2} and r.prompts == [] and saved == {}


def test_a_stale_verdict_version_is_judged_again(monkeypatch):
    saved = setup(monkeypatch)
    r = FakeRouter()
    express.gate(None, r, [art(1, "India win by six wickets", feed=2, extraction={"express": {"v": 0, "verdict": "no"}})], NOW)
    assert saved[1]["verdict"] == "yes"


def test_the_slice_limits_how_many_passed_headlines_are_embedded(monkeypatch):
    saved = setup(monkeypatch, allowance=2)
    arts = [art(i, f"India win by {i} wickets", feed=2, hours=i) for i in range(1, 6)]     # newest = smallest hours
    held, first = express.gate(None, FakeRouter(), arts, NOW)
    assert first == {1, 2}                                   # the two newest
    assert held == {3, 4, 5}                                 # passed, waiting for room: verdict still "yes"
    assert all(saved[i]["verdict"] == "yes" for i in range(1, 6))
    assert express.STATS["now"]["passed_waiting"] == 3


def test_a_passed_headline_waiting_for_the_slice_is_found_again_next_run(monkeypatch):
    setup(monkeypatch, allowance=0)
    yes = {"express": {"v": 1, "verdict": "yes", "lane": "sport"}}
    held, first = express.gate(None, FakeRouter(), [art(1, "x", feed=2, extraction=yes)], NOW)
    assert held == {1} and first == set()
    setup(monkeypatch, allowance=5)
    held, first = express.gate(None, FakeRouter(), [art(1, "x", feed=2, extraction=yes)], NOW)
    assert first == {1} and held == set()


def test_nothing_is_asked_once_the_days_slice_is_spent(monkeypatch):
    saved = setup(monkeypatch, allowance=0, left=0)
    r = FakeRouter()
    held, first = express.gate(None, r, [art(1, "India win by six wickets", feed=2)], NOW)
    assert r.prompts == [] and held == {1} and first == set() and saved == {}     # waits, undecided


def test_no_quota_leaves_headlines_undecided_and_embeds_nothing(monkeypatch):
    saved = setup(monkeypatch)
    held, first = express.gate(None, FakeRouter(fail=True), [art(1, "India win by six wickets", feed=2)], NOW)
    assert held == {1} and first == set() and saved == {}
    assert express.STATS["now"]["undecided"] == 1


def test_the_number_of_headlines_asked_in_a_run_is_capped(monkeypatch):
    saved = setup(monkeypatch)
    monkeypatch.setattr(express, "setting", lambda k, d=None: {"filter_batch": 2, "filter_calls_per_run": 2}.get(k, d))
    arts = [art(i, f"Report number {i} on nothing", feed=1, hours=i) for i in range(1, 8)]
    express.gate(None, FakeRouter(), arts, NOW)
    assert len(saved) == 4 and set(saved) == {1, 2, 3, 4}           # 2 calls x 2 headlines, newest first
    assert express.STATS["now"]["undecided"] == 3


def test_an_article_already_read_or_embedded_is_left_alone(monkeypatch):
    saved = setup(monkeypatch)
    a1 = art(1, "India win by six wickets", feed=2)
    a1["embedding"] = [0.1]
    a2 = art(2, "India win by six wickets", feed=2)
    a2["extracted_at"] = NOW
    held, first = express.gate(None, FakeRouter(), [a1, a2], NOW)
    assert held == set() and first == set() and saved == {}


def test_gate_is_off_when_the_lane_is_off(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(express, "enabled", lambda: False)
    assert express.gate(None, FakeRouter(), [art(1, "India win by six wickets", feed=2)], NOW) == (set(), set())


def test_verdict_is_read_from_the_article_json():
    assert express.verdict_of({"extraction": {"model": "m"}}) is None
    assert express.verdict_of({"extraction": None}) is None
    assert express.verdict_of({"extraction": {"express": {"v": 1, "verdict": "yes"}}})["verdict"] == "yes"
    assert json.dumps(express._verdict("yes", "sport", None, NOW)) == \
        '{"v": 1, "verdict": "yes", "at": "2026-10-12T12:00", "lane": "sport"}'


def test_funnel_numbers_are_plain_json():
    saved = setup  # noqa: F841  (the stats are saved as run stats: they must be JSON)
    express.reset()
    express.bump("asked", 3)
    express._count_excluded("harm:arrested")
    express._now("cap_left", 400)
    assert json.loads(json.dumps(express.STATS)) == {"asked": 3, "excluded": {"harm": 1},
                                                     "excluded_terms": {"harm:arrested": 1}, "now": {"cap_left": 400}}


def test_the_significance_question_keeps_out_what_does_not_matter_beyond_its_corner(monkeypatch):
    saved = setup(monkeypatch)
    router = FakeRouter(sig_none=("knee",))
    arts = [art(1, "Tata Motors opens plant in Sanand"), art(2, "India win by six wickets in Pune"),
            art(3, "Foreign star has knee trouble as team win by six wickets elsewhere", feed=2)]
    held, first = express.gate(None, router, arts, NOW)
    assert first == {1, 2} and held == {3}
    assert saved[1]["verdict"] == "yes" and saved[1]["sig"] == "india"
    assert saved[3]["verdict"] == "no" and saved[3]["why"] == "not_significant" and saved[3]["lane"] == "sport"
    assert express.STATS["not_significant"] == 1 and express.STATS["passed"] == 2
    assert len(router.sig_prompts) == 2           # asked, then asked again (reversed) for the two that passed


def test_a_model_without_an_answer_leaves_the_headline_pending_and_it_is_asked_again(monkeypatch):
    saved = setup(monkeypatch)
    router = FakeRouter()
    real = express._ask_sig
    monkeypatch.setattr(express, "_ask_sig", lambda r, items: {})         # the significance call fails
    held, first = express.gate(None, router, [art(1, "Tata Motors opens plant in Sanand")], NOW)
    assert first == set() and held == {1} and saved[1]["verdict"] == "pending"
    monkeypatch.setattr(express, "_ask_sig", real)
    stored = art(1, "Tata Motors opens plant in Sanand", extraction={"express": saved[1]})
    saved.clear()
    router2 = FakeRouter()
    held, first = express.gate(None, router2, [stored], NOW)
    assert first == {1} and saved[1]["verdict"] == "yes"
    assert not router2.prompts                    # the lane question was not asked again, only the significance one


def test_the_significance_check_can_be_switched_off(monkeypatch):
    saved = setup(monkeypatch)
    monkeypatch.setattr(express, "setting", lambda name, default: False if name == "significance_enabled" else default)
    held, first = express.gate(None, FakeRouter(sig_none=("plant",)), [art(1, "Tata Motors opens plant in Sanand")], NOW)
    assert first == {1}


# --- a headline the model cannot read stays undecided (risk.py: never passed on a guess) -----------------------------

def _no_model():
    from nishpaksh import nli
    nli.set_backend(lambda pairs: [None] * len(pairs))


def test_gate_holds_an_unread_headline_and_saves_nothing(monkeypatch):
    saved = setup(monkeypatch)
    _no_model()
    r = FakeRouter()
    held, first = express.gate(None, r, [art(1, "India win by six wickets", feed=2)], NOW)
    assert held == {1} and first == set()
    assert saved == {}                                   # no verdict: judged again next run
    assert r.prompts == []                               # and the lane model was not spent on it
    assert express.STATS["risk_held"] == 1


def test_gate_asks_again_once_the_model_reads(monkeypatch):
    saved = setup(monkeypatch)
    from nishpaksh import nli
    working = nli._backend
    _no_model()
    a = art(1, "India win by six wickets", feed=2)
    express.gate(None, FakeRouter(), [a], NOW)
    nli.set_backend(working)
    held, first = express.gate(None, FakeRouter(), [a], NOW)
    assert first == {1} and saved[1]["verdict"] == "yes"


def test_intake_lets_an_unread_headline_through_to_the_gate(monkeypatch):
    express.reset()
    _no_model()
    f_biz = {"id": 11, "url": HT_BUSINESS, "name": "HT"}
    rest, mine = express.take_intake([(f_biz, {"title": "Founder arrested over fund diversion", "summary": "", "url": "u3"})])
    assert [en["url"] for _, en in mine] == ["u3"]       # not excluded here: the gate will not embed it without reading it
    assert express.STATS["intake_unread"] == 1 and "intake_excluded" not in express.STATS


def test_the_lane_named_by_the_model_is_checked_with_its_own_concerns(monkeypatch):
    saved = setup(monkeypatch)
    # the second look (lane named) cannot be read although the first look (feed lane) could
    from nishpaksh import nli
    working = nli._backend
    calls = []

    def flaky(pairs):
        calls.append(1)
        return working(pairs) if len(calls) == 1 else [None] * len(pairs)
    nli.set_backend(flaky)
    # a sport feed, the model says companies: the market concern is new for it and could not be read
    held, first = express.gate(None, FakeRouter(), [art(1, "Tata opens plant in Pune", feed=2)], NOW)
    assert len(calls) == 2
    assert held == {1} and 1 not in saved                 # undecided, asked next run
    assert express.STATS["risk_held"] == 1

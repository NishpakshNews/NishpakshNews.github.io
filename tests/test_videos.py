"""YouTube search phrase, language certainty, similarity ranking (owner, Oct 12 2026: the names-based design found no
videos; rebuilt on vague headline phrases + similarity). videoquery.py has no database; `choose`, `_due` and
`_gather` are tested with a fake store and a fake `get`."""
import datetime as dt

from nishpaksh import videoquery as vq

H1 = "Delhi Police releases detained CJP leader Abhijit after conditional bond"
H2 = "Rahul Gandhi announces Monday opposition march to Supreme Court over election disputes"
H3 = "Donald Trump waives sanctions on Russian diesel while demanding Zelensky be replaced"


def test_the_code_phrase_keeps_the_kind_of_event_and_drops_names_and_figures():
    assert vq.code_phrase(H1) == "releases detained leader"
    assert vq.code_phrase(H2) == "announces opposition march"
    assert not any(ch.isdigit() for ch in vq.code_phrase("Rs 661.50 crore deal signed for BrahMos launchers"))
    assert vq.code_phrase("") == ""
    hindi = vq.code_phrase("दिल्ली पुलिस ने हिरासत में लिए गए नेता को सशर्त जमानत पर रिहा किया")
    assert hindi and all("\u0900" <= w[0] <= "\u097f" for w in hindi.split())


def test_a_title_case_headline_keeps_its_words():
    assert vq.code_phrase("Opposition March Against Election Disputes") == "opposition march election"


def test_the_models_phrase_is_checked_by_code():
    assert vq.clean_phrase("Release of detained leader.", H1, deva=False) == "release of detained leader"
    assert vq.clean_phrase("opposition march", H2, deva=False) == "opposition march"
    assert vq.clean_phrase("waiving of sanctions", H3, deva=False) == "waiving of sanctions"   # 'waiv' starts both
    assert vq.clean_phrase("Delhi Police release", H1, deva=False) == ""        # a name of the headline
    assert vq.clean_phrase("release of 5 leaders", H1, deva=False) == ""        # a figure
    assert vq.clean_phrase("one two three four five six", H1, deva=False) == ""  # too long
    assert vq.clean_phrase("weather forecast", H1, deva=False) == ""            # nothing from the headline
    assert vq.clean_phrase("सशर्त रिहाई", "दिल्ली पुलिस ने नेता को रिहा किया", deva=True) == "सशर्त रिहाई"
    assert vq.clean_phrase("release", "दिल्ली पुलिस ने नेता को रिहा किया", deva=True) == ""   # wrong script


class _Router:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls = data, fail, 0

    def call(self, tier, prompt, json_out=True, max_output_tokens=0):
        self.calls += 1
        if self.fail:
            raise RuntimeError("quota")

        class R:
            pass
        r = R()
        r.data = self.data
        return r


def test_phrases_use_one_model_call_and_fall_back_to_code_per_language():
    r = _Router({"en": "release of detained leader", "hi": "weather"})            # the Hindi one is the wrong script
    got = vq.phrases(H1, "दिल्ली पुलिस ने नेता को रिहा किया", r)
    assert r.calls == 1 and got["en"] == "release of detained leader" and got["hi"]
    assert "\u0900" <= got["hi"][0] <= "\u097f"
    assert vq.phrases(H1, "", _Router(fail=True)) == {"en": "releases detained leader"}      # no model: code
    assert vq.phrases(H1, "", None) == {"en": "releases detained leader"}
    assert vq.phrases("", "", None) == {}


def test_language_is_given_only_when_sure():
    L = vq.video_language
    assert L("Delhi Braces For CJP Protest 2.0 Against CEC Gyanesh Kumar") == "en"
    assert L("Opposition march to Supreme Court") == "en"
    assert L("Opposition march Supreme Court") is None                           # no English word, no tag: not sure
    assert L("Opposition march Supreme Court", "en") == "en"                     # the tag makes it sure
    assert L("Opposition march Supreme Court", "en-IN") == "en"
    assert L("Opposition march Supreme Court", None, "en") == "en"               # a known English channel
    assert L("दिल्ली पुलिस ने नेता को छोड़ा") == "hi"
    assert L("दिल्ली पुलिस नेता छोड़ा", "hi") == "hi"
    assert L("दिल्ली पुलिस नेता छोड़ा") is None                                    # no Hindi word, no tag
    # the October 12 case: another language shown as English
    assert L("দিল্লি পুলিশ নেতাকে ছেড়ে দিয়েছে") is None
    assert L("The Opposition march in Delhi", "bn") is None                      # the tag is another language
    assert L("Marcha de la oposición en Delhi") is None                          # accented Latin letters
    assert L("Himashree Boro Case: Train Mein Kya Hua Tha?") is None             # romanised Hindi
    assert L("दिल्ली में विपक्ष का मार्च आहे") is None                              # Marathi
    assert L("दिल्ली पुलिस ले नेता छोडेको छ") is None                               # Nepali
    assert L("दिल्ली में विपक्ष का मार्च", "en") is None                           # tag disagrees with the script
    assert L("") is None and L("12345") is None


def test_similarity_ranks_the_story_first_and_counts_repeated_article_words():
    doc = vq.document("Opposition march to Supreme Court over election disputes",
                      ["The opposition marched to the Supreme Court. The march was led by Rahul Gandhi."])
    assert doc["oppos"] == 3.5 and doc["march"] >= 3.0 and doc["rahul"] == 0.5
    vids = [{"title": "Cricket highlights from Mumbai"}, {"title": "Opposition march reaches Supreme Court"},
            {"title": "Rahul Gandhi on the march"}]
    s = vq.scores(vids, doc)
    assert s[1] > s[2] > s[0] == 0


def _video(vid, title, channel="Some Channel", at="2026-10-12T05:00:00Z", desc=""):
    return {"id": vid, "title": title, "desc": desc, "channel": channel, "channelId": channel, "at": at,
            "credible": False}


def test_choose_shows_only_sure_languages_ranked_by_similarity_two_per_channel():
    from nishpaksh.videos import choose
    docs = {"en": vq.document(H2, ["Opposition leaders marched to the Supreme Court."]),
            "hi": vq.document("विपक्ष का सुप्रीम कोर्ट तक मार्च", [])}
    cands = [_video("e1", "Opposition march to the Supreme Court over election disputes", "A"),
             _video("e2", "Opposition leaders march to Supreme Court today", "A"),
             _video("e3", "Opposition march reaches the Supreme Court", "A"),            # a third from channel A
             _video("e4", "The march of the opposition in Delhi", "B"),
             _video("x1", "বিরোধী মিছিল সুপ্রিম কোর্টে", "C"),                              # Bengali: never
             _video("h1", "विपक्ष का सुप्रीम कोर्ट तक मार्च, राहुल गांधी ने किया ऐलान", "D"),
             _video("h2", "क्रिकेट मैच के बाद का हाल", "E")]
    got = choose(cands, docs)
    ids = [v["id"] for v in got]
    assert "x1" not in ids and "e3" not in ids and "h2" not in ids
    assert ids.index("e1") < ids.index("e4") and "h1" in ids
    assert {v["id"]: v["lang"] for v in got}["h1"] == "hi" and all("desc" not in v and "score" not in v for v in got)


def test_choose_never_leaves_the_card_empty_when_a_sure_video_exists():
    from nishpaksh.videos import choose
    docs = {"en": vq.document("Opposition march", []), "hi": {}}
    cands = [_video("a", "Weather report for the week in Delhi", "A"), _video("b", "Cricket match of the day", "B"),
             _video("c", "A song of the year", "C"), _video("d", "Chinese drama 12 of the season", "D")]
    got = choose(cands, docs)
    assert len(got) == 3                                                   # topped up to MIN_SHOW with the best sure ones
    assert choose([_video("z", "অসমে বন্যা")], docs) == []                   # nothing sure, nothing shown


def test_choose_uses_the_language_tags():
    from nishpaksh.videos import choose
    docs = {"en": vq.document("Opposition march", []), "hi": {}}
    c = [_video("a", "Opposition march Supreme Court"), _video("b", "Opposition march Parliament", "B")]
    assert [v["id"] for v in choose(c, docs, {})] == []                        # no English word, no tag
    assert [v["id"] for v in choose(c, docs, {"a": "en", "b": "ta"})] == ["a"]  # b is tagged Tamil


def test_due_retries_an_empty_row_once_and_never_a_filled_one():
    from nishpaksh.videos import _due
    now = dt.datetime(2026, 10, 12, 12, 0)
    pub = now - dt.timedelta(hours=4)
    assert _due(pub, None, now)                                                          # never tried
    assert not _due(pub, {"items": [{"id": "x"}], "fetched_at": pub}, now)               # has videos
    assert not _due(pub, {"items": [], "fetched_at": now - dt.timedelta(hours=1)}, now)  # too soon
    assert _due(pub, {"items": [], "fetched_at": pub + dt.timedelta(hours=1)}, now)      # the one second try
    old_story = now - dt.timedelta(hours=8)
    assert not _due(old_story, {"items": [], "fetched_at": now - dt.timedelta(hours=3)}, now)  # that WAS the second try



def test_due_handles_mixed_naive_and_timezone_aware_timestamps():
    from nishpaksh.videos import _due

    # Production combines naive UTC newsroom timestamps with aware Supabase timestamptz values.
    now_naive = dt.datetime(2026, 10, 12, 12, 0)
    published_naive = now_naive - dt.timedelta(hours=4)
    fetched_aware = dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.timezone.utc)
    assert _due(published_naive, {"items": [], "fetched_at": fetched_aware}, now_naive)

    # Also handle aware `now` / publication values, including a non-UTC offset.
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    now_aware = dt.datetime(2026, 10, 12, 17, 30, tzinfo=ist)
    published_aware = dt.datetime(2026, 10, 12, 13, 30, tzinfo=ist)
    fetched_naive = dt.datetime(2026, 10, 12, 9, 0)
    assert _due(published_aware, {"items": [], "fetched_at": fetched_naive}, now_aware)

    # A missing timestamp is not retryable, and filled results are never retried.
    assert not _due(None, {"items": [], "fetched_at": fetched_aware}, now_naive)
    assert not _due(published_naive, {"items": [{"id": "existing"}], "fetched_at": fetched_aware}, now_naive)


class _Store:
    def __init__(self):
        self.units = 0

    def quota_add(self, model, day, requests, tokens):
        self.units += requests


def _response(items):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"items": items}
    return R()


def test_gather_searches_each_phrase_in_its_language_with_and_without_a_date_limit():
    from nishpaksh.videos import _gather
    seen = []

    def get(url, params, timeout):
        seen.append(params)
        return _response([{"id": {"videoId": "a"}, "snippet": {"title": "T", "channelTitle": "C", "channelId": "c",
                                                               "description": "d", "publishedAt": "2026-10-12T05:00:00Z"}}])
    store = _Store()
    qs = [("opposition march", "en"), ("विपक्ष मार्च", "hi")]
    got = _gather(store, "KEY", qs, dt.datetime(2026, 9, 1), get)
    assert [v["id"] for v in got] == ["a", "a"] and store.units == 200
    assert [p["relevanceLanguage"] for p in seen] == ["en", "hi"] and "publishedAfter" in seen[0]
    _gather(store, "KEY", qs[:1], None, get)
    assert "publishedAfter" not in seen[-1]


def test_gather_returns_none_when_a_search_fails():
    from nishpaksh.videos import _gather

    def get(url, params, timeout):
        raise RuntimeError("quota")
    assert _gather(_Store(), "KEY", [("x y", "en")], None, get) is None


# ---------------------------------------------------------------- the ongoing story (owner, Oct 13 2026)
def test_earlier_headlines_of_the_thread_raise_the_ranking_words_to_a_floor():
    """A follow-up's headline says only what is new; the video is titled with the story's old words."""
    plain = vq.document("Court seeks report on bail plea", [])
    assert "abhij" not in plain
    doc = vq.document("Court seeks report on bail plea", [], thread=["Delhi Police detains CJP leader Abhijit"])
    assert doc["abhij"] == vq.THREAD_WEIGHT and doc["court"] == 3.0          # floors only raise: own words keep theirs
    vids = [{"title": "Abhijit detained: CJP leader taken into custody"}, {"title": "Cricket highlights"}]
    assert vq.scores(vids, doc)[0] > vq.scores(vids, plain)[0] == 0


def test_a_thread_word_never_lowers_a_heavier_headline_word():
    doc = vq.document("Opposition march to Supreme Court", [], thread=["Opposition march planned"])
    assert doc["oppos"] == 3.0 and doc["march"] == 3.0


def test_topic_neighbours_count_only_for_words_two_other_headlines_share():
    pool = ["Heavy rain floods Patna streets as river rises", "River rises in Patna, schools shut",
            "Cricket: India win toss", "Sensex ends flat"]
    head = "Patna flood relief camps open as river rises"
    near = vq.neighbours(head, pool)
    assert set(near) == set(pool[:2])
    one = vq.document(head, [], neighbours=near[:1])
    assert "schoo" not in one and "heavy" not in one                         # one other headline alone adds nothing
    two = vq.document(head, [], neighbours=near)
    assert two["patna"] == 3.0                                               # the headline's own weight is kept
    assert "cricket" not in two


def test_neighbours_need_shared_words_and_skip_the_headline_itself():
    assert vq.neighbours("Rain in Patna", ["Rain in Patna", "Cricket final", "Patna rain damage"]) == \
        ["Patna rain damage"]                                   # itself skipped; no shared words, no neighbour
    assert vq.neighbours("Patna floods worsen", ["Patna floods: rescue begins", "Delhi smog"]) == \
        ["Patna floods: rescue begins"]


def test_phrases_give_the_model_the_threads_headlines_in_the_same_single_call():
    calls = []

    class Res:
        data = {"en": "arrest of leader", "hi": "नेता की गिरफ्तारी"}

    class Router:
        def call(self, role, prompt, **kw):
            calls.append(prompt)
            return Res()
    out = vq.phrases("Court seeks report on bail plea", "अदालत ने जमानत पर रिपोर्ट मांगी", Router(),
                     thread_en=["Delhi Police arrests leader Abhijit"], thread_hi=["दिल्ली पुलिस ने नेता को गिरफ्तार किया"])
    assert len(calls) == 1 and "Delhi Police arrests leader Abhijit" in calls[0] and "ONGOING" in calls[0]
    assert out["en"] == "arrest of leader"          # shares 'arre' with the EARLIER headline, accepted because of it
    calls.clear()
    vq.phrases("Court seeks report on bail plea", "", Router())
    assert "EARLIER HEADLINES" not in calls[0]       # no thread: the prompt is as before


def test_a_phrase_with_a_name_from_an_earlier_headline_is_still_refused():
    assert vq.clean_phrase("abhijit arrest", "Court seeks report on bail plea", False,
                           thread=["Delhi Police arrests leader Abhijit"]) == ""
    assert vq.clean_phrase("leader arrest", "Court seeks report on bail plea", False,
                           thread=["Delhi Police arrests leader Abhijit"]) == "leader arrest"


# ---------------------------------------------------------------- Shorts (owner, Oct 13 2026)
def test_durations_are_read_and_a_live_broadcast_has_no_length_yet():
    assert vq.parse_duration("PT45S") == 45 and vq.parse_duration("PT1M5S") == 65
    assert vq.parse_duration("PT1H2M3S") == 3723
    assert vq.parse_duration("P0D") is None and vq.parse_duration("") is None and vq.parse_duration(None) is None


def test_a_short_is_a_video_under_the_minimum_or_tagged_as_one():
    assert vq.is_short("Rally", "", 45) and vq.is_short("Rally", "", vq.MIN_SECONDS - 1)
    assert not vq.is_short("Rally", "", vq.MIN_SECONDS)
    assert vq.is_short("Rally #Shorts", "", 600) and vq.is_short("Rally", "watch on YouTube Shorts", None)
    assert not vq.is_short("Rally", "", None)                      # length unknown (live, or the call failed): kept


def test_choose_drops_shorts_before_ranking_and_before_the_fill_up():
    from nishpaksh.videos import choose
    docs = {"en": vq.document("Opposition march to the Supreme Court", []), "hi": {}}
    cands = [_video("s1", "Opposition march to the Supreme Court today", "A"),        # best match, but 40 s
             _video("s2", "Opposition march Supreme Court #shorts", "B"),             # tagged, length unknown
             _video("ok", "Opposition march reaches the Supreme Court", "C"),
             _video("f1", "Weather in Delhi this week", "D")]
    tags = {v["id"]: "en" for v in cands}
    got = [v["id"] for v in choose(cands, docs, tags, seconds={"s1": 40, "ok": 300, "f1": 200})]
    assert "s1" not in got and "s2" not in got and got[0] == "ok"
    # fill-up: with every video short, the card stays empty rather than showing Shorts
    shorts = [_video(str(i), f"Opposition march clip {i}", str(i)) for i in range(4)]
    assert choose(shorts, docs, {v["id"]: "en" for v in shorts}, seconds={v["id"]: 30 for v in shorts}) == []


def test_details_return_language_tag_and_length_in_one_call():
    from nishpaksh.videos import _details
    seen = []

    def get(url, params, timeout):
        seen.append(params)
        return _response([{"id": "a", "snippet": {"defaultAudioLanguage": "en"}, "contentDetails": {"duration": "PT45S"}},
                          {"id": "b", "snippet": {"defaultLanguage": "hi"}, "contentDetails": {"duration": "P0D"}},
                          {"id": "c", "snippet": {}}])
    got = _details("KEY", ["a", "b", "c"], get)
    assert len(seen) == 1 and seen[0]["part"] == "snippet,contentDetails"
    assert got == {"a": {"tag": "en", "seconds": 45}, "b": {"tag": "hi", "seconds": None}, "c": {"tag": None, "seconds": None}}

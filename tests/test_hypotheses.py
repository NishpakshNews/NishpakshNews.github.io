"""The group A hypothesis tests (nishpaksh/tools/hypotheses.py) on a small database seeded with KNOWN defects: each test
must see the defect planted for it. Plain sqlite3, no model, no network."""
import datetime as dt
import json
import sqlite3

from nishpaksh.tools import hypotheses as H


def build():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
    create table published(story_id int, version int, updated_at text, headline_en text, payload_en text);
    create table stories(id int, analysis text);
    create table claims(id int, story_id int, article_id int, kind text, text text, stance text, attributed_to text, "time" text, canonical_id int);
    create table canonical(id int, story_id int, kind text, text text, rel text, conflicts text, verdict text, detail text, origins text, checkable int);
    create table story_links(parent_id int, child_id int, reason text);
    create table diagnostics(id integer primary key, created_at text, kind text, report text);
    create table runs(id integer primary key, started_at text, trigger text, stats text);
    """)
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    def item(i, text, speaker=None, verdict="corroborated"):
        return {"id": i, "kind": "event", "text": text, "verdict": verdict, "speaker": speaker}
    s1_items = [
      item(1, "Sandeep Naik said the notice was served on Friday to the senior officer in Delhi", "Sandeep Naik"),
      item(2, "The notice was served on Friday to the senior officer in Delhi according to Sandeep Naik", "Sandeep Naik"),
      item(3, "He confirmed 100% of the seats were filled in the Mandi district"),
      item(4, "Rahul Gandhi accused the government of hiding the figures", "Rahul Gandhi"),
      item(5, "Priyanka Gandhi accused the government of hiding the figures", "Priyanka Gandhi"),
    ]
    sent = lambda t, ids: {"text": t, "ids": ids}
    nar1 = {"paragraphs": [
        [sent("Sandeep Naik said the notice was served on Friday to the senior officer in Delhi.", [1]),
         sent("Sandeep Naik added that 100% of the seats were filled.", [3])],
        [sent("The notice was served on Friday to the senior officer in Delhi, Sandeep Naik said.", [2]),
         sent("About 100% of seats were taken, officials said, and feesadi remained pending. I?ve seen it.", [3])],
        [sent("The agency said 100% of the work is done. It's what Naik's team says, but the minister’s office differs.", [3]),
         sent("Rahul Gandhi accused the government of hiding the figures.", [4]),
         sent("Priyanka Gandhi accused the government of hiding the figures.", [5])],
        [sent("Sandeep Naik denied the charge.", [1])]],
      "section_keys": ["happened", "background", "numbers", "say"]}
    p1 = {"headline": "Notice row", "timeline": [s1_items[:3]], "established": s1_items[3:], "places": ["himachal-pradesh"],
          "narrative": nar1, "counts": {"independent_sources": 2, "outlets": 3}, "parents": [], "thread": 2, "qualified_by": "perspectives"}
    topics = {"tkey": [[s1_items[0]["text"]], [s1_items[1]["text"]], [s1_items[2]["text"]], [s1_items[3]["text"], s1_items[4]["text"]]]}
    an1 = {"topic_groups": None, "same_checks": {"3:5": False, "f3:5": True, "c1:2": False, "fc1:2": True},
           "dupe_checks": {"x": 1}, "qualified_by": "perspectives",
           "attribution_map": {"the Centre": {"kind": "government", "government": "India"},
                               "Modi government": {"kind": "government", "government": "Modi government"}}}
    an1["topic_groups"] = topics
    con.execute("insert into published values (2,1,?,?,?)", (now, "Notice row", json.dumps(p1)))
    con.execute("insert into stories values (2, ?)", (json.dumps(an1),))
    for k, (a, t) in enumerate([("Sandeep Naik", "Sandeep Naik said the notice was served"), ("Rahul Gandhi", "Rahul Gandhi said x"),
                                ("Priyanka Gandhi", "Priyanka Gandhi said y"), ("Washington Post", "It reported z")]):
        con.execute("insert into claims values (?,?,?,?,?,?,?,?,?)", (k, 2, k, "event", t + " Ã© â€™ ", "attributes", a, "{}", k))
    con.execute("insert into canonical values (50,2,'event','He said it was fine',?,?,?,?,?,1)", ("{}", "[]", "false",
                json.dumps({"checked": True, "outcome": "false", "opinions": [{"reason": "model says so", "evidence_urls": []}], "web_sources": []}), "{}"))
    con.execute("insert into canonical values (51,2,'event','It was fine',?,?,?,?,?,1)", ("{}", "[]", "confirmed",
                json.dumps({"checked": True, "outcome": "confirmed", "opinions": [{"reason": "ok", "evidence_urls": ["http://a"]}], "web_sources": ["w"]}), "{}"))
    # thread: story 2 child of parents 3 and 4, payload has no parents; canonical of parents
    for pid in (3, 4):
        con.execute("insert into canonical values (?,?,'event','parent line',?,?,?,?,?,1)", (60 + pid, pid, "{}", "[]", "corroborated", "{}", "{}"))
        con.execute("insert into story_links values (?,2,'dev')", (pid,))
    con.execute("insert into canonical values (70,2,'event','child line',?,?,?,?,?,1)", (json.dumps({"twins": [63]}), "[]", "corroborated", "{}", "{}"))
    con.execute("insert into diagnostics (created_at,kind,report) values (?,?,?)", (now, "positions", json.dumps({"signal": True, "r": .4, "null_r": .1})))
    con.execute("insert into diagnostics (created_at,kind,report) values (?,?,?)", (now, "positions", json.dumps({"signal": False, "why": "too few outlets"})))
    con.execute("insert into runs (started_at,trigger,stats) values (?,?,?)", (now, "cron", json.dumps({"global_clusters": 3})))
    con.execute("insert into runs (started_at,trigger,stats) values (?,?,?)", (now, "cron", json.dumps({"global_clusters": 0})))

    p2 = {"headline": "Mandi prices", "timeline": [], "places": ["himachal-pradesh", "assam"], "counts": {"independent_sources": 4},
          "narrative": {"paragraphs": [[{"text": "Prices at the mandi rose sharply in the market on Tuesday.", "ids": []},
                                        {"text": "Officials in Guwahati said the rise was short-lived.", "ids": []}]],
                        "section_keys": ["happened"]}}
    con.execute("insert into published values (9,1,?,?,?)", (now, "Mandi prices", json.dumps(p2)))
    con.execute("insert into stories values (9, ?)", (json.dumps({}),))

    def q(sql, **p):
        return [dict(r) for r in con.execute(sql, p).fetchall()]
    return q


def report(only=None):
    q = build()
    return H.run(H.load(q, 14, q), only)


def test_no_test_fails():
    rep = report()
    assert {k for k, v in rep["tests"].items() if v.get("error")} == set()
    assert len(rep["tests"]) >= 15


def test_planted_defects_are_seen():
    t = report()["tests"]
    assert t["H22"]["data"]["layers"]["claims"]["with_mojibake"] == 4
    assert t["H22"]["data"]["layers"]["published"]["with_mojibake"] == 1
    assert t["H22"]["data"]["mixed_apostrophe_articles"] == 1
    assert t["H18"]["data"]["figure_3plus"] == 1
    assert t["H3/H10"]["data"]["pair_kinds"].get("cross_section") == 1
    m = t["H1/H27/H28/H37"]["data"]
    assert m["pairs_split_topics"] == 1 and m["pairs_same_topic"] == 1
    assert m["first_same_final_no"] == {"same": 1, "covers": 1}
    assert t["H42"]["data"]["reasons"] == {"word_in_title_or_notperson_list": 1}
    assert t["H43/H46"]["data"]["collision_stories"] == 1
    assert t["H43/H46"]["data"]["rejected_by_word"] == {"Naik": 1}
    assert t["H66"]["data"]["shapes"] == {"pronoun": 2}
    assert t["H41"]["data"]["tag_not_found_in_text"] == 1 and t["H41"]["data"]["only_alias_match"] == 2
    assert t["H70"]["data"]["no_evidence"] == 1 and t["H70"]["data"]["rows"] == 2
    assert t["H74"]["data"]["stories_multi"] == 1
    assert t["H79"]["data"]["histogram"]["perspectives"] == {"2": 1}
    assert t["H95/H96"]["data"]["parents_lost"] == 1 and t["H95/H96"]["data"]["one_sided"] == 1
    assert t["H80/H87"]["data"]["flips"] == 1
    assert t["H80/H87"]["data"]["cluster_stats"]["global_clusters"]["changes"] == 1
    assert "feesadi" in {x["token"] for x in t["H4"]["data"]["review_list"]}


def test_only_runs_the_named_tests():
    assert set(report({"H22"})["tests"]) == {"OVERVIEW", "H22"}


def test_empty_database_does_not_crash():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
    create table published(story_id int, version int, updated_at text, headline_en text, payload_en text);
    create table stories(id int, analysis text);
    create table claims(id int, story_id int, article_id int, kind text, text text, stance text, attributed_to text, "time" text, canonical_id int);
    create table canonical(id int, story_id int, kind text, text text, rel text, conflicts text, verdict text, detail text, origins text, checkable int);
    create table story_links(parent_id int, child_id int, reason text);
    """)
    q = lambda sql, **p: [dict(r) for r in con.execute(sql, p).fetchall()]  # noqa: E731
    rep = H.run(H.load(q, 14, None))
    assert not [k for k, v in rep["tests"].items() if v.get("error")]

"""The express desk (step 2 of the express plan, Oct 16 2026): coverage of the one report, a layout per kind of story,
and the copy check."""
import types

from nishpaksh import coverage as C
from nishpaksh import expressdesk as D
from nishpaksh import narrative as N

REPORT = """NEW DELHI: Prithvi Shaw scored 537 runs in seven matches in the 2025-26 Ranji Trophy season.
He made 222 off 156 balls against Chandigarh in the league stage of the season.
Delhi Capitals brought him back for the 2026 IPL season, although he did not play a match.
Also read: Top cricket stories of the day
Former India coach Greg Chappell wrote him a letter about not letting the past decide his future.
Is this the end of the road for him?
Get the latest Sports News and Live updates. Download the TOI app."""


def test_coverage_counts_fact_sentences_only_and_finds_what_was_read():
    facts = C.fact_sentences(REPORT)
    assert len(facts) == 4 and not any("Download" in f or "Also read" in f or f.endswith("?") for f in facts)
    items = [{"text": "Prithvi Shaw scored 537 runs in seven matches.", "quote": "NEW DELHI: Prithvi Shaw scored 537 runs"},
             {"text": "Shaw made 222 runs off 156 balls against Chandigarh."}]          # found by its numbers
    n, total, left = C.report(items, REPORT)
    assert (n, total) == (2, 4) and any("Chappell" in s for s in left)


def item(i, text, kind="claim", speaker=None, words=None, time=None):
    return {"id": i, "kind": kind, "text": text, "speaker": speaker, "words": words, "time": time,
            "frame": {}, "role": "core", "verdict": "single", "sources": []}


def test_kinds_by_lane_and_statements():
    match = [item(1, "India beat Pakistan by 19 runs in the final"), item(2, "Abhishek Sharma scored 61 runs off 28 balls"),
             item(3, "Pakistan scored 192 runs for 6 wickets")]
    assert D.kind_of("sport", match) == "match"
    results = [item(1, "Nestle India's net profit rose 36% to Rs 1,026 crore in the September quarter"),
               item(2, "Revenue rose 20% to Rs 6,782 crore"), item(3, "Total expenses rose 17% to Rs 5,405 crore")]
    assert D.kind_of("companies", results) == "results"
    profile = [item(k, t) for k, t in enumerate(["Prithvi Shaw is 26", "Prithvi Shaw went unsold in 2025",
                                                  "Prithvi Shaw scored 537 runs", "Shaw wants an India comeback"])]
    assert D.kind_of("sport", profile) == "profile"
    assert D.kind_of("entertainment", [item(1, "The film released on Friday")]) == "general"


def test_each_layout_places_every_statement_in_its_own_sections():
    profile = [item(1, "Prithvi Shaw returned to form", kind="event"),
               item(2, "Prithvi Shaw is 26 years old"),
               item(3, "Prithvi Shaw scored 537 runs in seven matches"),
               item(4, "Prithvi Shaw said returning to the India team is his goal", speaker="Prithvi Shaw",
                    words="It is me versus me"),
               item(5, "Prithvi Shaw captained India to the Under-19 title in 2018", kind="event",
                    time={"start": "2018-02-03T00:00"})]
    sec = {1: "news", 2: "happened", 3: "numbers", 4: "say", 5: "background"}
    got = D.sections("profile", profile, sec)
    assert got == {1: "news", 2: "who", 3: "journey", 4: "words", 5: "journey"}
    assert set(got.values()) <= set(D.LAYOUTS["profile"])
    text = D.structure("profile")
    assert "journey" in text and "In their own words" not in text and "one or two outlets" in text


def test_the_copy_check_rephrases_only_what_repeats_the_report():
    rep = "Delhi Capitals brought him back for the 2026 IPL season, although he did not play a match."
    by = {1: item(1, "Delhi Capitals brought Prithvi Shaw back for the 2026 IPL season but he did not play a match.")}
    paras = [[{"text": "Delhi Capitals brought him back for the 2026 IPL season, although he did not play a match.",
               "ids": [1]}]]
    assert N.copied(paras[0][0]["text"], N._grams(rep))
    assert not N.copied('He said "brought him back for the 2026 IPL season, although he did not play" then.', N._grams(rep))

    class R:
        def call(self, tier, prompt, **kw):
            return types.SimpleNamespace(data={"sentences": [
                "Prithvi Shaw returned to Delhi Capitals for the 2026 IPL season but did not play a match."]})
    out, stats = N._rephrase_copies(R(), paras, by, set(), [], rep)
    assert stats == {"copied": 1, "rephrased": 1} and out[0][0]["text"].startswith("Prithvi Shaw returned")

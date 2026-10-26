"""Names are found first, on the text as written, and rewritten once (Oct 26 2026: story 45108 printed "Chief Minister
Chandrababu Andhra Pradesh Chief Minister N Chandrababu Naidu": the pass patched each written form of a person in turn
and the next form matched the output of the one before)."""
from nishpaksh.style import mentions, shorten_names

FORMS = {"N Chandrababu Naidu": "Naidu"}


def test_a_partial_name_is_one_mention_with_its_given_names():
    t = "Chief Minister Chandrababu Naidu reviewed the state's preparedness."
    spans = mentions(t, FORMS)
    assert [(t[a:b], s) for a, b, s in spans] == [("Chandrababu Naidu", "Naidu")]


def test_the_longest_written_form_wins_and_mentions_never_overlap():
    t = "N Chandrababu Naidu spoke, and Naidu left."
    spans = mentions(t, FORMS)
    assert [t[a:b] for a, b, _ in spans] == ["N Chandrababu Naidu", "Naidu"]


def test_a_person_is_introduced_once_whichever_form_comes_first():
    P = [[{"text": "Chief Minister Chandrababu Naidu reviewed the preparations on Sunday."},
          {"text": "N Chandrababu Naidu directed officials to open control rooms."},
          {"text": "Naidu said evacuations would begin."}]]
    shorten_names(P, ["N Chandrababu Naidu"], ["Andhra Pradesh Chief Minister N Chandrababu Naidu reviewed preparedness"])
    out = [s["text"] for s in P[0]]
    assert out[0].startswith("Andhra Pradesh Chief Minister N Chandrababu Naidu reviewed")
    assert out[1].startswith("Naidu directed") and out[2].startswith("Naidu said")
    assert " ".join(out).count("Chandrababu") == 1


def test_a_lone_statement_joins_the_paragraph_it_is_closest_to_but_a_labelled_topic_stays_apart():
    from nishpaksh import plan
    mk = lambda i, t: {"id": i, "text": t}   # noqa: E731
    groups = [[mk(1, "Brent fell 1.3 percent to 115 dollars")], [mk(2, "WTI fell 1.7 percent to 101 dollars")],
              [mk(3, "Houthi drones were intercepted over Riyadh"), mk(4, "Saudi Arabia intercepted missiles")]]
    assert [[i["id"] for i in g] for g in plan.merge_small(groups)] == [[1, 2], [3, 4]]
    assert [[i["id"] for i in g] for g in plan.merge_small(groups, [True, True, False])] == [[1], [2], [3, 4]]
    assert [[i["id"] for i in g] for g in plan.merge_small([[mk(1, "only one")]])] == [[1]]


def test_a_linked_event_must_name_something_the_story_names():
    from nishpaksh import belong
    core = ["Cyclone Arnab will make landfall near Visakhapatnam on Wednesday.",
            "Andhra Pradesh Chief Minister Chandrababu Naidu reviewed preparedness.",
            "The India Meteorological Department issued an orange alert for Andhra Pradesh.",
            "Odisha closed schools in five districts."]
    assert belong.grounded("Chandrababu Naidu also met the Union Home Minister.", core)
    assert not belong.grounded("Himachal Pradesh is experiencing bright, sunny and crisp autumn conditions.", core)


def test_the_inspector_counts_what_it_missed_in_the_two_live_articles():
    from nishpaksh import inspector
    P = [[{"text": "Chief Minister Chandrababu Andhra Pradesh Chief Minister N Chandrababu Naidu reviewed the state's preparedness."}],
         [{"text": "On Sunday, US Central Command chief Adm."}]]
    out = inspector.inspect(P)
    assert out["repeated_run"] == 1 and out["cut_sentence"] == 1 and out["one_sentence_paragraphs"] == 2

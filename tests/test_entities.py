"""The entity table, tested on the real names of Group A (14 days of published articles, Oct 18 2026; H42, H43).
Every name below is a speaker the pipeline stored. Each test says what the current code did with it."""
from nishpaksh import entities as E


def table(*speakers, text=""):
    t = E.EntityTable()
    for s in speakers:
        t.add(s, "speaker", text)
    return t.build()


def groups(t):
    return sorted(sorted(m.raw for m in e.mentions) for e in t.entities)


def test_two_different_singhs_are_two_people_and_a_spelling_variant_is_one():
    # story 26428: speaker_key gave all three "singh"; Harjit and Harjeet are one DIG, Bhim Singh is someone else
    t = table("Bathinda DIG Harjit Singh", "Bhim Singh", "DIG Harjeet Singh")
    assert groups(t) == [["Bathinda DIG Harjit Singh", "DIG Harjeet Singh"], ["Bhim Singh"]]
    assert t.speaker_key("DIG Harjeet Singh") == t.speaker_key("Bathinda DIG Harjit Singh") == "harjit singh"
    assert t.speaker_key("Bhim Singh") == "bhim singh"


def test_a_lone_surname_that_fits_two_people_is_ambiguous_not_guessed():
    t = table("Bhim Singh", "DIG Harjit Singh", "Singh")
    lone = t.entity("Singh")
    assert lone.ambiguous and lone.key.startswith("?")
    assert {e.key for e in t.entities if not e.ambiguous} == {"bhim singh", "harjit singh"}


def test_a_lone_surname_joins_the_one_person_who_has_it():
    t = table("Defence Minister Rajnath Singh", "Singh")
    assert len(t.entities) == 1 and not t.entities[0].ambiguous


def test_abhishek_and_mamata_banerjee_are_not_one_speaker():          # story 23630: both were key "banerjee"
    t = table("Abhishek Banerjee", "Mamata Banerjee")
    assert len(t.entities) == 2
    assert t.speaker_key("Abhishek Banerjee") != t.speaker_key("Mamata Banerjee")


def test_one_minister_under_three_titles_is_one_entity():            # stories 27229, 28714
    t = table("Defence Minister Rajnath Singh", "Defense Minister Rajnath Singh", "Indian Defence Minister Rajnath Singh",
              "Union Defence Minister Rajnath Singh")
    assert len(t.entities) == 1 and t.entities[0].name == "Rajnath Singh"


def test_the_three_yadavs_of_the_gwalior_story():                    # story 31784
    t = table("Chief Minister Mohan Yadav", "Acting Inspector General of Police Asit Yadav",
              "Gwalior superintendent of police Dharamveer Yadav", "Yadav")
    keys = sorted(e.key for e in t.entities)
    assert keys == ["?yadav", "asit yadav", "dharamvir yadav", "mohan yadav"]


def test_two_spellings_of_one_first_name_and_a_title_difference():   # story 29042 (Dipke), 24672 (Tejashwi), 28333 (Carney)
    assert len(table("Abhijeet Dipke", "Abhijit Dipke").entities) == 1
    assert len(table("Opposition leader Tejashwi Yadav",
                     "Raghopur MLA and Rashtriya Janata Dal leader Tejashwi Yadav").entities) == 1
    t = table("Canadian Prime Minister Mark Carney", "Rt. Hon. PM Mark Carney")
    assert len(t.entities) == 1 and t.entities[0].name == "Mark Carney"
    assert len(table("Former Canadian PM Justin Trudeau", "former Canadian Prime Minister Justin Trudeau").entities) == 1


def test_titled_speakers_the_old_detector_rejected_are_people():     # 34 of 153 speaker names were rejected for the title
    for raw, core in [("Canadian Prime Minister Mark Carney", "Mark Carney"),
                      ("Chhattisgarh Chief Minister Vishnu Deo Sai", "Vishnu Deo Sai"),
                      ("Defense Minister Rajnath Singh", "Rajnath Singh"),
                      ("Commander National Strategic Command General Aamer Raza", "Aamer Raza"),
                      ("Gwalior Police Senior Superintendent Dharmveer Singh", "Dharmveer Singh")]:
        e = table(raw).entities[0]
        assert e.person and e.name == core, raw


def test_initials_fit_the_written_out_name_and_a_different_first_name_does_not():
    t = table("MK Stalin", "M K Stalin", "Muthuvel Karunanidhi Stalin")
    assert len(t.entities) == 1 and t.entities[0].name == "Muthuvel Karunanidhi Stalin"
    t = table("MK Stalin", "Udhayanidhi Stalin")
    assert len(t.entities) == 2


def test_bodies_and_relations_make_no_person():
    for raw in ["Ministry of Defence", "Department of Energy", "Indian Computer Emergency Response Team",
                "Cockroach Janata Party and student groups", "Vithya Ramraj's father", "Mr. (Vithya Ramraj's father)"]:
        t = table(raw)
        assert not t.persons(), raw
    assert E.parse("Vithya Ramraj's father").kind == "relation"


def test_a_name_in_plain_narrative_is_a_person_only_with_evidence():
    # story 26660: "Alexandros Paporakis" 19 times, "no person evidence"
    text = "Alexandros Paporakis was arrested in Palatine. Alexandros Paporakis denied nothing. Saudi Arabia was angry."
    t = E.EntityTable()
    t.add_text(text)
    assert [e.name for e in t.persons()] == ["Alexandros Paporakis"]
    for non_person in ["Super League", "Asian Games", "Saudi Arabia", "New Zealand",
                       "Comprehensive Economic Partnership Agreement", "Street Fighter"]:
        t = E.EntityTable()
        t.add_text(f"{non_person} was in the news. {non_person} scored a lot and won.")
        assert not t.persons(), non_person


def test_shortenable_follows_the_entity_not_the_string():
    # story 26428: "Parvinder Singh" (18 times) and "Parvinder Singh Jhota" (15) were two strings sharing "Singh" with
    # DIG Harjit Singh, so neither was ever shortened; the victim is one person and "Jhota" is only his
    text = ("Chief Minister Mohan Yadav said it. Parvinder Singh Jhota was shot, police said. Parvinder Singh was a "
            "trader. Parvinder Singh Jhota, 41, died. DIG Harjit Singh said so.")
    t = E.EntityTable()
    t.add_text(text)
    short = t.shortenable()
    assert short.get("Parvinder Singh Jhota") == "Jhota" and short.get("Parvinder Singh") == "Jhota"
    assert "Harjit Singh" not in short and "Mohan Yadav" in short


def test_two_people_with_one_surname_are_never_shortened():
    t = E.EntityTable()
    t.add_text("Minister Abhishek Banerjee said it. Mamata Banerjee said that.")
    assert t.shortenable() == {}


def test_a_surname_that_is_also_someones_first_name_is_not_a_short_form():
    t = E.EntityTable()
    t.add_text("Chief Minister Mohan Yadav said it. Minister Rajesh Mohan said that.")
    assert "Rajesh Mohan" not in t.shortenable()


def test_first_shadow_run_fixes():
    """The first live run (66 articles, Oct 25 2026) found these."""
    for raw, name in [("Capt Gurudeep Bala", "Gurudeep Bala"),
                      ("Shree Narendra Modi", "Narendra Modi"),
                      ]:
        assert E.parse(raw).text == name, raw
    # bodies, events and organisations are the analyser's call (nlp.py labels them ORG), not parse()'s
    assert E.parse("Lokesh Adhikari Lokesh Adhikari").text == "Lokesh Adhikari"
    # a place leaking in after "of" is one person with the plain title; the shorter name is the entity's name
    t = table("Chief Electoral Officer Navdeep Rinwa", "Chief Electoral Officer of Uttar Pradesh Navdeep Rinwa",
              "Uttar Pradesh Chief Electoral Officer Navdeep Rinwa")
    assert len(t.entities) == 1 and t.entities[0].name == "Navdeep Rinwa"
    # fits the longest name, not every member: Singh is a middle name, two shorter forms are one person with it
    t = table("ITBP Director General Shatrujeet Singh Kapoor", "ITBP Director General Singh Kapoor", "Shatrujeet Kapoor")
    assert len(t.entities) == 1

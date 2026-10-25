from nishpaksh import aliases, nlp
from nishpaksh.entities import EntityTable


def test_alias_cue_between_two_people_unifies_them():
    t = EntityTable()
    text = "Sunil Yadav alias Bunty Chor was arrested. Later Bunty Chor was produced in court."
    for a, b in aliases.find(text):
        t.link(a, b)
    t.add("Sunil Yadav", "text", text)
    t.add("Bunty Chor", "text", text)
    assert t.entity("Sunil Yadav") is t.entity("Bunty Chor")


def test_no_cue_no_link():
    assert aliases.find("Sunil Yadav met Bunty Chor in Patna.") == []

from nishpaksh import nameconflict as nc


def test_spellings_of_one_person_are_an_alias_and_two_people_in_one_sentence_are_distinct():
    assert nc.classify(["Narendra Modi", "Modi"], []) == "alias"
    assert nc.classify(["A. K. Sharma", "Ajay Kumar Sharma"], []) == "alias"
    assert nc.classify(["Ritesh Kumar Singh", "Abhishek Kumar Singh"],
                       ["Ritesh Kumar Singh is accused of assisting Abhishek Kumar Singh."]) == "distinct"
    assert nc.classify(["Company A", "Company B"], ["Company A was fined."]) == "disagreement"
    assert nc.classify(["Bhim Singh", "Harjit Singh"], []) == "disagreement"            # two written-out first names: never linked

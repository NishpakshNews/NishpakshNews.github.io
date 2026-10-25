from nishpaksh import crosslingual, entities, names as N


def _reg():
    reg = N.Registry()
    reg.add_manual("Kushok", "कुशोक")
    reg.add_manual("Rimpochee", "रिम्पोछे")
    return reg


def test_hindi_name_becomes_the_english_spelling():
    assert crosslingual.to_english("कुशोक रिम्पोछे ने कहा", _reg()) == "Kushok Rimpochee ने कहा"


def test_unknown_word_and_english_text_are_untouched():
    assert crosslingual.to_english("अज्ञात ने कहा", _reg()) == "अज्ञात ने कहा"
    assert crosslingual.to_english("Kushok said", _reg()) == "Kushok said"


def test_a_hindi_speaker_is_the_same_entity_as_the_english_one():
    crosslingual.use(_reg())
    try:
        t = entities.for_items([{"speaker": "Kushok Rimpochee", "text": "Kushok Rimpochee said the road is shut."},
                                {"speaker": "कुशोक रिम्पोछे", "text": "सड़क बंद है।"}])
        assert t.entity("कुशोक रिम्पोछे") is t.entity("Kushok Rimpochee") and t.entity("Kushok Rimpochee") is not None
    finally:
        crosslingual.use(None)

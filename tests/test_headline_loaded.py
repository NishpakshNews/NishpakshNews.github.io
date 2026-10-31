from nishpaksh import news


def test_word_the_statements_use_is_freed():
    banned, freed = news.freed_words({"shoddy", "riot"}, ["Police said the riot spread."])
    assert banned == {"shoddy"} and freed == ["riot"]
    assert news.headline_problem("Riot in town leaves two hurt", "riot in town leaves two hurt", banned) is None


def test_unused_loaded_word_still_blocks():
    p = news.headline_problem("Shoddy flyover collapses in Kesarganj", "a flyover collapsed in kesarganj", {"shoddy"})
    assert p and "loaded word" in p and "shoddy" in p


def test_quoted_word_is_exempt():
    assert news.loaded_hit('Mayor calls bridge "shoddy" after collapse', {"shoddy"}) is None
    assert news.loaded_hit("Mayor calls bridge shoddy after collapse", {"shoddy"}) == "shoddy"


def test_fault_keeps_full_set():
    banned, freed = news.freed_words({"x"}, [None, 5])
    assert banned == {"x"} and freed == []

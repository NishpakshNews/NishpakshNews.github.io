from nishpaksh import inspector


def S(t):
    return {"text": t}


def test_counts_what_the_sentence_checks_would_refuse_in_the_final_text():
    paras = [[S("It was arrested on Monday."), S("Police arrested the engineer on Monday in Patna.")],
             [S("Police arrested the engineer on Monday in Patna.")]]
    r = inspector.inspect(paras)
    assert r["sentences"] == 3 and r["opens_with_pronoun"] == 1 and r["repeats"] >= 1 and r["problems"] >= 2


def test_a_clean_article_has_no_problems():
    r = inspector.inspect([[S("Police arrested the site engineer."), S("The court heard the case on Tuesday.")]])
    assert r["problems"] == 0

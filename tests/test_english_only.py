"""narrative.english_only: the English essay holds English sentences (Oct 30 2026, a Hindi statement published with an English
attribution)."""
from nishpaksh import narrative

HI = "लेकिन अब तक का अनुभव बताता है कि अलग-अलग मुद्दों पर छोटे-छोटे कदम उठाने से समस्या का समाधान नहीं होगा, Parvathaneni Harish said."
EN = "India agrees with the sentiment behind UNGA Resolution 76/262, Parvathaneni Harish said."
NAME = "Rimpochee said the (रिम्पोछे) monastery would reopen on Monday for all visitors."


def S(t, i):
    return {"text": t, "ids": [i]}


def test_a_sentence_mostly_in_another_script_leaves_the_essay_and_its_paragraph_key_goes_if_it_empties():
    paras, keys, stray = narrative.english_only([[S(EN, 1), S(HI, 2)], [S(HI, 3)]], ["news", "background"])
    assert [[x["ids"] for x in p] for p in paras] == [[[1]]] and keys == ["news"] and stray == [HI, HI]


def test_a_devanagari_name_inside_an_english_sentence_stays_and_an_article_is_never_emptied():
    paras, keys, stray = narrative.english_only([[S(NAME, 1)]], ["news"])
    assert stray == [] and paras == [[S(NAME, 1)]]
    paras, keys, stray = narrative.english_only([[S(HI, 1)]], ["news"])         # the only sentence: nothing moves
    assert stray == [] and len(paras[0]) == 1

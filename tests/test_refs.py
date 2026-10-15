"""refs.py: every sentence knows what came before it (owner, Oct 15 2026). No database needed."""
from nishpaksh import refs

SRC_SCHEME = ("This comes after the Cabinet approved a new rural employment guarantee scheme, Viksit Bharat–Guarantee "
              "for Rozgar and Ajeevika Mission (Gramin), in December last year, replacing the Mahatma Gandhi National "
              "Rural Employment Guarantee Act (MGNREGA). The divyangjan pension scheme will give 375 rupees.")
NAME = "Viksit Bharat–Guarantee for Rozgar and Ajeevika Mission (Gramin)"
SRC_ECI = ("The Election Commission of India said it was trying to trace the missing video recording of the counting "
           "of votes in 2023 in Sringeri.")


def test_a_generic_thing_gets_the_name_the_source_gives_it():
    r = refs.resolve_item({"text": "The new scheme is replacing the Mahatma Gandhi National Rural Employment "
                                   "Guarantee Scheme.", "attributed_to": "article"}, SRC_SCHEME)
    assert r["refs"] == [{"phrase": "The new scheme", "gloss": NAME, "how": "code"}]      # not ", in December"


def test_two_different_things_are_never_guessed():
    src = "A new pension scheme, Alpha Yojana, began. A new housing scheme, Beta Yojana, also began."
    r = refs.resolve_item({"text": "The new scheme is popular.", "attributed_to": "article"}, src)
    assert not r["refs"] and r["open"]


def test_a_pronoun_that_is_the_speaker_is_replaced_only_when_the_source_says_so():
    it = {"text": "It was trying to trace the missing video recording", "attributed_to": "Election Commission of India"}
    assert refs.resolve_item(it, SRC_ECI)["text"].startswith("Election Commission of India was trying")
    other = refs.resolve_item(it, "Officials said the Election Commission of India was busy. It was trying to trace "
                                  "the missing video recording.")
    assert "text" not in other and other["open"][0]["kind"] == "pronoun"      # no proof: left open, counted


def test_a_model_answer_must_stand_in_the_source():
    assert refs.usable_gloss(NAME, "the new scheme", SRC_SCHEME) == NAME
    assert refs.usable_gloss("Viksit Bharat Rozgar Mission", "the new scheme", SRC_SCHEME) is None     # invented
    assert refs.usable_gloss("the scheme", "the new scheme", SRC_SCHEME) is None                       # no name


def test_ask_model_keeps_only_verified_answers():
    class R:
        def call(self, tier, prompt, **kw):
            class Res:
                data = {"1": NAME, "2": "Made Up Mission"}
            return Res()
    res = {"refs": [], "open": []}
    o1 = {"phrase": "the new scheme", "kind": "definite"}
    o2 = {"phrase": "the bill", "kind": "definite"}
    res["open"] = [o1, o2]
    assert refs.ask_model(R(), [(res, o1), (res, o2)], SRC_SCHEME) == 1
    assert res["refs"][0]["gloss"] == NAME and res["open"] == [o2]


def test_the_name_goes_in_brackets_once_and_only_when_the_reader_was_not_told():
    para = [{"text": "The new scheme is replacing the old one.", "ids": [1]},
            {"text": "The new scheme starts in April.", "ids": [1]}]
    out = refs.gloss_article([para], "Cabinet news", lambda s: [{"phrase": "The new scheme", "gloss": NAME}])
    assert para[0]["text"] == f"The new scheme [{NAME}] is replacing the old one."       # square: the name has brackets
    assert "[" not in para[1]["text"] and out["glossed"] == 1
    told = [{"text": "The new scheme is replacing the old one.", "ids": [1]}]
    refs.gloss_article([told], NAME, lambda s: [{"phrase": "The new scheme", "gloss": NAME}])
    assert "[" not in told[0]["text"]                                                     # the headline said it


def test_a_paragraph_does_not_open_with_it():
    assert refs.opening_problem("It was trying to trace the video, Election Commission of India said.")
    assert refs.opening_problem("This comes after the Cabinet approved a scheme.")
    assert refs.opening_problem("It is not clear whether the video exists.") is None
    assert refs.opening_problem("The Election Commission said it was trying.") is None


def test_the_attribution_goes_first_so_the_pronoun_has_someone_before_it():
    t = "It was trying to trace the missing video recording, Election Commission of India said."
    assert refs.repair_opening(t, {"Election Commission of India"}) == \
        "Election Commission of India said it was trying to trace the missing video recording."
    assert refs.repair_opening(t, {"Someone Else"}) is None


def test_the_check_repairs_or_refuses_a_dangling_opening():
    from nishpaksh.narrative import _check_paragraphs
    from tests.test_pipeline import _item
    by = {1: _item(1, "Election Commission of India was trying to trace the missing video recording",
                   speaker="Election Commission of India")}
    para = [{"text": "It was trying to trace the missing video recording, Election Commission of India said.", "ids": [1]}]
    paras, failed, _ = _check_paragraphs([para], by, set(), [])
    assert paras and paras[0][0]["text"].startswith("Election Commission of India said it was trying")
    # a bare "It ..." with a named speaker is pinned and reordered by the repairs; with no speaker it is refused
    by2 = {2: _item(2, "The panel will meet on Friday")}
    bare = [{"text": "It will meet on Friday.", "ids": [2]}]
    paras, failed, _ = _check_paragraphs([bare], by2, set(), [])
    assert not paras and failed[0]["reason"] == "opens with a pronoun"


# ---- a pronoun in the middle of a paragraph; Hindi; a body of several people is "they" (owner, Oct 15 2026) ----

def test_a_pronoun_with_nothing_before_it_is_refused_anywhere_in_a_paragraph():
    assert refs.antecedent_problem("It was handed over later.", "") == "pronoun without antecedent"
    assert refs.antecedent_problem("It was handed over later.", "Police arrested the engineer on Monday.") is None
    assert refs.antecedent_problem("The panel said it would meet.", "") is None
    assert refs.antecedent_problem("It was handed over later.", None) is None            # position unknown: not asked


def test_a_bare_it_said_after_a_body_gets_the_body_back():
    from nishpaksh.narrative import _check_paragraphs
    from tests.test_pipeline import _item
    by = {1: _item(1, "The Supreme Court heard the plea", speaker="Supreme Court"),
          2: _item(2, "The plea seeks a fresh count", speaker="Supreme Court")}
    para = [{"text": "The Supreme Court heard the plea.", "ids": [1]}, {"text": "It added that the plea seeks a fresh count.", "ids": [2]}]
    paras, failed, _ = _check_paragraphs([para], by, set(), [])
    assert [s["text"][:7] for s in paras[0]] == ["The Sup", "It adde"]                   # the sentence before is its antecedent
    lone = [{"text": "It added that the plea seeks a fresh count.", "ids": [2]}]
    paras, failed, _ = _check_paragraphs([lone], by, set(), [])
    assert paras and paras[0][0]["text"].startswith("Supreme Court added")              # repaired: the body named


def test_a_court_is_they_with_a_plural_verb():
    from nishpaksh import agreement as a
    f = lambda t, c="": a.fix_text(t, c)[0]                                              # noqa: E731
    assert f("The Supreme Court said it was examining the plea.") == "The Supreme Court said they were examining the plea."
    assert f("The Election Commission of India said it is checking its records.") == \
        "The Election Commission of India said they are checking their records."
    assert f("Police said it believes the man fled.") == "Police said they believe the man fled."
    assert f("The petitioners asked it to rule on its own powers.", "The Supreme Court heard the case.") == \
        "The petitioners asked them to rule on their own powers."


def test_it_stays_it_when_the_body_is_not_a_group_or_not_the_nearest_thing():
    from nishpaksh import agreement as a
    f = lambda t, c="": a.fix_text(t, c)[0]                                              # noqa: E731
    assert f("The government said it was ready.") == "The government said it was ready."          # not in the list
    assert f("The Supreme Court asked the Centre whether it had complied.") == \
        "The Supreme Court asked the Centre whether it had complied."                              # the Centre is nearer
    assert f("The High Court said \"it is a matter\" and it was adjourned.") == \
        "The High Court said \"it is a matter\" and it was adjourned."                             # another clause
    assert f("The Supreme Court said it is not clear whether the plea will stand.") == \
        "The Supreme Court said it is not clear whether the plea will stand."                      # expletive it
    assert f("The Reliance spokesperson said it was ready.") == "The Reliance spokesperson said it was ready."


def test_the_article_pass_follows_the_sentence_before_and_the_parts():
    from nishpaksh import agreement as a
    paras = [[{"text": "The Election Commission of India said on Monday that the video is missing.", "ids": [1]},
              {"text": "It was trying to trace its copy.", "ids": [2]},
              {"parts": [{"text": "The Supreme Court said it was hearing the plea,", "ids": [3]},
                         {"text": "and it has reserved its order.", "ids": [4]}], "text": "x", "ids": [3, 4]}]]
    for s in paras[0][2:]:
        s["text"] = " ".join(p["text"] for p in s["parts"])
    n = a.fix_article(paras)
    assert paras[0][1]["text"] == "They were trying to trace their copy."
    assert paras[0][2]["text"] == "The Supreme Court said they were hearing the plea, and they have reserved their order." and n == 5


def test_a_body_run_is_they_not_it():
    from nishpaksh.voice import body_refs
    assert body_refs("Supreme Court") == ["the court", "they"]
    assert body_refs("US Department of State") == ["the department", "it"]


def test_a_hindi_source_is_matched_across_scripts_never_made_up():
    src = ("केंद्रीय मंत्रिमंडल ने दिसंबर में एक नई ग्रामीण रोजगार गारंटी योजना, विकसित भारत–रोजगार और आजीविका गारंटी "
           "मिशन (ग्रामीण) को मंजूरी दी।")
    assert refs.is_hindi(src) and not refs.is_hindi(SRC_SCHEME)
    assert refs.usable_gloss("Viksit Bharat Rozgar Ajeevika Guarantee Mission Gramin", "the new scheme", src)
    assert refs.usable_gloss("Made Up Mission", "the new scheme", src) is None
    assert refs.usable_gloss("विकसित भारत", "the new scheme", src) is None               # an English article needs English letters
    r = refs.resolve_item({"text": "It was trying to trace the missing video.", "attributed_to": "Election Commission"}, src)
    assert "text" not in r and r["open"]                                                 # a Hindi source's pronoun: left open, counted


def test_the_hindi_page_keeps_the_bracketed_name_and_adds_no_pronoun():
    from nishpaksh.compose import translation_problem as tp
    en = "The new scheme [Viksit Bharat–Guarantee for Rozgar and Ajeevika Mission (Gramin)] is replacing the old one."
    assert tp(en, "नई योजना [Viksit Bharat–Guarantee for Rozgar and Ajeevika Mission (Gramin)] पुरानी योजना की जगह ले रही है।") is None
    assert tp(en, "नई योजना [विकसित भारत] पुरानी योजना की जगह ले रही है।") == "bracketed name changed"
    assert tp("The Election Commission of India said the video is missing.",
              "वह वीडियो लापता होने की बात चुनाव आयोग ने कही।") == "pronoun added"

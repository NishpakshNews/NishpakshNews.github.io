"""The read-only audits (nishpaksh/audit.py): pure functions, no database."""
from nishpaksh import audit


def test_near_pairs_find_the_same_fact_left_apart_and_note_the_clock_time():
    texts = {1: "Modi will inaugurate five major development projects worth 3,350 crore in Ladakh on October 15",
             2: "Modi will inaugurate five major development projects worth 3,350 crore rupees on October 15 at 12:30 PM",
             3: "Geothermal energy is used in the new passenger terminal building"}
    rep = audit.merge_report(texts, {"k1": False, "k2": True, "fk1": True, "ck3": False}, relate_fn=lambda a, b: "different")
    assert rep["near_pairs"] == 1 and rep["near_with_clock"] == 1
    assert rep["asked"] == 2 and rep["asked_no"] == 1          # first answers ("f") and covers questions ("c") left out
    assert rep["code_verdicts"] == {"different": 1}


def test_latin_left_in_hindi_is_counted_units_and_links_are_not():
    page = {"headline": "भारतीय टेनिस खिलाड़ी Amrit Vats ने Djibouti में खिताब जीता",
            "narrative": {"section_keys": ["news", "happened"],
                          "paragraphs": [[{"text": "Amrit Vats और Muhammad Yahya ने ITF खिताब जीता।"}],
                                         [{"text": "सड़क 12 km लंबी है, देखें https://x.in/a"},
                                          {"text": "This sentence was never translated."}]]}}
    rep = audit.hindi_report(page)
    assert rep["strings"] == 4 and rep["untranslated"] == 1 and rep["with_latin"] == 2
    assert rep["words"]["Amrit"] == 2 and "km" not in rep["words"] and "https" not in rep["words"]
    assert rep["by_field"] == {"headline": 1, "section": 1, "section:untranslated": 1}


def test_repeated_openings_and_runs():
    paras = [[{"text": "Modi will inaugurate a park."}, {"text": "Modi will inaugurate 40 water bodies."},
              {"text": "Modi will inaugurate a hydro project."}, {"text": "It will add 9 MW."}],
             [{"text": "The terminal uses geothermal energy."}, {"text": "It cuts the carbon footprint."}]]
    rep = audit.openings_report(paras)
    assert rep["sentences"] == 6 and rep["alike"] == 2 and rep["runs_of_3"] == 1


def test_mixed_forms_inside_one_article():
    t = ("Projects worth ₹3,350 crore open on October 15. Projects worth 3,350 crore rupees open on 15 October "
         "at 12:30 PM. Turnout rose 5 per cent; costs fell 3%.")
    f = audit.forms_report(t)
    assert f == {"date_both": True, "money_both": True, "percent_both": True, "clock_times": 1}
    assert audit.forms_report("On 15 October, ₹40 crore.")["date_both"] is False


def test_language_mix_and_summary_by_mix():
    assert audit.language_mix({"en"}) == "en" and audit.language_mix({"hi", "en"}) == "mixed"
    assert audit.language_mix(set()) == "en"
    s = {"id": 1, "mix": "mixed",
         "merge": audit.merge_report({1: "a b c d e f g h", 2: "a b c d e f g x"}, {}),
         "hindi": audit.hindi_report({"headline": "Amrit Vats जीते"}),
         "openings": audit.openings_report([[{"text": "A b c."}, {"text": "A b d."}]]),
         "forms": audit.forms_report("")}
    out = audit.summarise([s])
    assert out["by_mix"]["mixed"]["hindi"]["with_latin"] == 1 and out["by_mix"]["mixed"]["openings"]["alike"] == 1
    assert ("Amrit", 1) in out["latin_top_words"]

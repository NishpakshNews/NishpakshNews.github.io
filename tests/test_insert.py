"""nishpaksh/insert.py: lines of "Also in these reports" that belong in the article (shadow)."""
from nishpaksh import insert


def L(text, ids, cls="established", sources=(1,)):
    return {"text": text, "ids": list(ids), "class": cls, "sources": list(sources)}


def A(text, id_, role="background", verdict="unverified", speaker=None, sources=()):
    return {"id": id_, "text": text, "role": role, "verdict": verdict, "n_sources": 1, "speaker": speaker, "sources": list(sources)}


PARAS = [
    [L("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday.", [1]),
     L("The scheme aims to build domestic container production for Indian shipping lines.", [2])],
    [L("Container shortages raised freight rates for Indian exporters this year.", [3]),
     L("The Shipping Ministry will run the scheme with an outlay of ₹10,000 crore.", [4])],
    [L("Rain fell over Kerala on Tuesday.", [7]), L("The court heard a plea on Monday.", [8])],       # filler for the weights
]


def run(also):
    return insert.insert([list(p) for p in PARAS], also, "Cabinet approves scheme to boost container production")


def test_a_line_about_the_same_scheme_goes_in_after_its_nearest_line():
    new, rep = run([A("Container manufacturing under the scheme will start with three Indian shipyards.", 10)])
    assert rep["inserted"] == 1
    flat = [x["text"] for p in new for x in p]
    assert any("three Indian shipyards" in t for t in flat)


def test_what_the_article_already_says_another_subject_a_pronoun_and_an_outlets_own_voice_stay_out():
    out = {
        "said": A("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Wednesday.", 11),
        "pron": A("She said the ministry would also review the scheme within a year.", 12),
        "other": A("The Cabinet approved the Khelo India Sports Goods Manufacturing Scheme with an outlay of ₹1,856 crore.", 13, "related"),
        "self": A("Satya Hindi is an effort by some journalists to build a newsroom.", 14, speaker="Satya Hindi",
                  sources=[{"outlet": "Satya Hindi"}]),
        "short": A("It was approved.", 15),
    }
    new, rep = run(list(out.values()))
    assert rep["inserted"] == 0, rep["why_not"]
    assert sum(rep["why_not"].values()) == 5


def test_a_clashing_line_is_not_inserted_quietly():
    new, rep = run([A("The Union Cabinet approved the Container Manufacturing Promotion Scheme on Thursday.", 16, "core")])
    assert rep["inserted"] == 0 and any("clash" in k or "already" in k for k in rep["why_not"])


def test_the_inserted_line_keeps_its_own_colour_and_input_is_untouched():
    from nishpaksh.narrative import shade
    before = [[dict(x) for x in p] for p in PARAS]
    new, rep = insert.insert([list(p) for p in PARAS],
                             [A("Container manufacturing under the scheme will start with three Indian shipyards.", 10)], "", shade=shade)
    line = next(x for p in new for x in p if "shipyards" in x["text"])
    assert line["class"] == "single" and "_inserted" not in line
    assert PARAS == before

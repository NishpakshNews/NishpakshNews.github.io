"""express_replay: which stored exclusions would pass without a word (plain logic)."""
from nishpaksh import express, express_replay


def test_a_dropped_word_lets_its_headline_through_unless_another_list_holds_it():
    express.reload()
    rows = [{"title": "Fans detained outside the stadium before the final", "url": "https://x/a", "lane": "sport", "why": "harm:detained"},
            {"title": "Founder detained, company shares fall", "url": "https://x/b", "lane": "companies", "why": "harm:detained"}]
    rep = express_replay.replay(rows, {"detained"})
    got = {r["title"]: r["now"] for r in rep["harm:detained"]}
    assert got["Fans detained outside the stadium before the final"] is None
    assert got["Founder detained, company shares fall"] is not None        # "shares" ... or another list keeps it out
    assert express.excluded(rows[0]["title"], "", "", "sport") == "harm:detained"   # the real config is restored afterwards

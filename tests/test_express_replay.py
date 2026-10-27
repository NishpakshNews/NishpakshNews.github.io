"""express_replay: the audit of the concerns on stored headlines (plain logic, scripted model)."""
from nishpaksh import express_replay, nli

DEFS = {"harm": {"crime": "The news is about a crime or an arrest."}, "market": {"prices": "Share prices moved."}}
APPLY = {"harm": "all", "market": ["companies"]}


def model(pairs):
    out = []
    for premise, hypothesis in pairs:
        word = "arrest" if "crime" in hypothesis else "shares"        # each definition is "said" by its own words
        hit = word in premise.lower()
        out.append((0.9, 0.05, 0.05) if hit else (0.05, 0.9, 0.05))
    return out


def test_audit_compares_old_verdicts_with_the_definitions():
    nli.set_backend(model)
    rows = [{"title": "Founder arrested in fraud case", "lane": "companies", "verdict": "excluded", "why": "harm:arrested"},
            {"title": "Fans detained outside the stadium", "lane": "sport", "verdict": "excluded", "why": "harm:detained"},
            {"title": "Tata opens a plant", "lane": "companies", "verdict": "yes"},
            {"title": "Reliance shares surge", "lane": "companies", "verdict": "yes"}]
    rep = express_replay.audit(rows, DEFS, APPLY, 0.5)
    assert rep["old_excluded"]["harm"] == {"n": 2, "also": 1, "missed": ["Fans detained outside the stadium"]}
    assert rep["passed"]["n"] == 2 and rep["passed"]["would_exclude"] == [("Reliance shares surge", "market:prices")]
    assert rep["by_definition"] == {"harm:crime": 1, "market:prices": 1}
    assert rep["unread"] == 0


def test_a_headline_the_model_could_not_read_is_counted_not_judged():
    nli.set_backend(lambda pairs: [None] * len(pairs))
    rep = express_replay.audit([{"title": "Anything", "lane": "sport", "verdict": "yes"}], DEFS, APPLY, 0.5)
    assert rep["unread"] == 1 and rep["passed"]["would_exclude"] == []

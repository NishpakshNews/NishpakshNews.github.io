"""headlinekit: pure code, no model, no database."""
import time
from nishpaksh import headlinekit as kit

T = [{"outlet": "A", "title": "Seemapuri building collapse: 40 dead, rescue continues in Delhi"},
     {"outlet": "B", "title": "Delhi: 40 killed as Seemapuri building collapses"},
     {"outlet": "C", "title": "Seemapuri collapse toll rises to 40, rescue on"},
     {"outlet": "D", "title": "Opposition walks out of Parliament over price rise"}]


def test_consensus_finds_what_most_outlets_share():
    c = kit.consensus(T)
    assert any(v["word"].lower().startswith("seemapuri") for v in c.values())
    assert kit.coverage("Seemapuri collapse kills 40 in Delhi", c) > kit.coverage("Building falls in city", c)
    assert kit.has_figure("Seemapuri collapse kills 40", c)


def test_too_few_outlets_gives_neutral_values():
    assert kit.consensus(T[:1]) == {} and kit.consensus([]) == {} and kit.consensus(None) == {}
    assert kit.coverage("anything", {}) == 0 and kit.blocks([], [])["outlets"] == ""


def test_quotes_must_be_letter_for_letter():
    facts = 'Minister Rao said, "we will not bend to pressure from anyone". It was a long day.'
    q = kit.quotes([{"text": facts, "speaker": "Minister Rao", "words": "we will not bend to pressure from anyone"}])
    assert kit.quote_problem('Rao: "we will not bend"', facts, q) is None
    assert kit.quote_problem('Rao: "we will never bend"', facts, q)
    assert kit.quote_problem('Rao: "we will not bend"', facts)         # no listed quote: a long span is refused


def test_copying_an_outlet_headline_is_refused():
    assert kit.copy_problem("Delhi: 40 killed as Seemapuri building collapses", T)
    assert not kit.copy_problem("Seemapuri collapse leaves 40 dead, families wait for news", T)


def test_repetition_penalises_same_shape():
    recent = ["Police arrest three over theft", "Police arrest two over fraud"]
    assert kit.repetition("Police arrest five over smuggling", recent) >= kit.repetition("Court stays eviction order in Noida", recent)


def test_fast_and_never_raises():
    t = time.time()
    for _ in range(200):
        kit.blocks(T, [{"text": "x said, \"hello there my friend\""}])
    assert time.time() - t < 1.0
    assert kit.blocks([{"bad": 1}, None, 5], [None])["cons"] == {}

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


def _fake_embed(texts):
    """Bag of a few topic words per text, so Hindi and English about one event are close (stand-in for the multilingual model)."""
    import numpy as np
    keys = [("collapse", "ढह", "गिर"), ("delhi", "दिल्ली"), ("40", "४०"), ("parliament", "संसद"), ("price", "महंगाई")]
    return np.array([[1.0 if any(k in t.lower() for k in ks) else 0.0 for ks in keys] + [0.05] for t in texts])


def test_market_reads_hindi_and_english_on_one_scale():
    from nishpaksh import embed
    embed.set_backend(_fake_embed)
    try:
        titles = T + [{"outlet": "H", "title": "दिल्ली में इमारत ढही, ४० की मौत"}]
        m = kit.evaluate(titles, reference="A building collapsed in Delhi and 40 people died.",
                         candidates=["Delhi collapse kills 40, rescue goes on", "Parliament row over price rise"])
        assert m["seeds"] and "Parliament" not in m["seeds"][0]["title"]
        assert m["cands"][0] > m["cands"][1]               # the on-topic candidate beats the off-topic one
        assert kit._figset("४० की मौत") == kit._figset("40 dead")     # the figure bridge across scripts
    finally:
        embed.set_backend(None)


def test_market_is_neutral_without_voices_or_embedding():
    assert kit.evaluate(T[:1])["seeds"] == [] and kit.evaluate(None)["best"] is None


def test_seeds_are_adaptive_two_to_four():
    from nishpaksh import embed
    embed.set_backend(_fake_embed)
    try:
        m = kit.evaluate(T, reference="A building collapsed in Delhi and 40 died.")
        assert kit.SEED_MIN <= len(m["seeds"]) <= kit.SEED_MAX and len(m["all"]) == 4
    finally:
        embed.set_backend(None)


def test_write_headline_retries_only_when_ours_is_outside_the_top_three_and_records_it():
    from nishpaksh import embed, news
    embed.set_backend(_fake_embed)
    item = {"id": 1, "text": "A building collapsed in Delhi and 40 people died.", "n_sources": 3, "role": "core", "time": {}}
    titles = T + [{"outlet": "H", "title": "दिल्ली में इमारत ढही, ४० की मौत"},
                  {"outlet": "I", "title": "Delhi building collapse: 40 killed"}]

    class R:
        calls = 0

        def __init__(self, seq):
            self.seq = seq

        def call(self, tier, prompt, **k):
            h = self.seq[min(self.calls, len(self.seq) - 1)]
            self.calls += 1
            return type("X", (), {"data": {"headlines": [h]}})()
    try:
        r = R(["Delhi building collapse leaves 40 dead, families wait for news"])        # on topic: in the top three, one call
        news.write_headline(r, item, {1: item}, item["text"], set(), titles=titles)
        assert r.calls == 1 and news.HEADLINE_STATS["rank"] <= 3 and news.HEADLINE_STATS["outlets"]
        r = R(["Parliament row over price rise grows", "Parliament row over price rise worsens"])   # off topic: second call
        news.write_headline(r, item, {1: item}, item["text"], set(), titles=titles)
        assert r.calls == 2 and news.HEADLINE_STATS["retried"] is True
    finally:
        embed.set_backend(None)

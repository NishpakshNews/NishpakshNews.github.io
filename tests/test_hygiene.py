from nishpaksh import hygiene


def test_mojibake_is_undone_and_clean_text_untouched():
    good = "नमस्ते दुनिया, it’s fine"
    bad = good.encode("utf-8").decode("cp1252", errors="ignore") if False else None
    broken = "Itâ€™s a Hindi quote"      # â€™ for ’
    assert hygiene.repair(broken) == "It’s a Hindi quote"
    assert hygiene.repair(good) == good and hygiene.repair("") == ""


def test_profile_language_and_leaks():
    t = "Police arrested five men. They were taken away. पुलिस ने पांच लोगों को गिरफ्तार किया।"
    p = hygiene.profile(t)
    assert p["en"] == 2 and p["hi"] == 1
    assert hygiene.language(t) == "en"
    assert hygiene.leaks(t) == ["पुलिस ने पांच लोगों को गिरफ्तार किया।"]
    assert hygiene.kind("PM Modi ने कहा कि यह सही है") == "mixed"


def test_translation_quality_estimate_uses_the_bi_encoder_only():
    import numpy as np
    from nishpaksh import embed, fidelity
    embed.set_backend(lambda texts: np.array([[1.0, 0.0] if "police" in t.lower() or "पुलिस" in t else [0.0, 1.0] for t in texts]))
    try:
        assert fidelity.quality_low("The police arrested five men near the bridge", "पुलिस ने पुल के पास पांच लोगों को पकड़ा") is None
        assert fidelity.quality_low("The police arrested five men near the bridge", "आज मौसम बहुत अच्छा रहेगा यहां") is not None
        assert fidelity.quality_low("Short", "छोटा") is None
    finally:
        embed.set_backend(None)

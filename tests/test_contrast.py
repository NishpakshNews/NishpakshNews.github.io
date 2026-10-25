from nishpaksh import contrast


def test_seed_cue_and_learned_cue():
    contrast.set_learned([])
    assert contrast.has("Police made another arrest") and not contrast.has("Police made an arrest")
    contrast.set_learned(["raid"])
    try:
        assert contrast.has("A raid was held")
    finally:
        contrast.set_learned([])


def test_learn_from_answers():
    rows = []
    for i in range(10):
        rows.append({"a": f"Police arrested ten men in district {i} on Sunday",
                     "b": f"Police arrested ten men in district {i} on Sunday during a crackdown", "label": False})
    for i in range(10):
        rows.append({"a": f"Police arrested ten men in district {i} on Monday",
                     "b": f"Police arrested ten men in district {i} on Monday afternoon", "label": True})
    got = contrast.learn(rows)
    assert "crackdown" in got and "afternoon" not in got

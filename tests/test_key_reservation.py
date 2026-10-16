"""The Translator project's key serves the quality lane only (owner, Oct 16 2026; models.yaml `keys:`)."""
import pytest

from nishpaksh.config import load_yaml
from nishpaksh.router import QuotaExhausted, Router

from .fixtures import FakeBackend


def _named(name):
    b = FakeBackend()
    b.key_name = name
    return b


def _keys_by_tier(router):
    return {t: sorted({s.key_name for s in slots}) for t, slots in router.tiers.items()}


def test_the_translator_key_serves_only_the_quality_tier_and_quality_only_it():
    cfg = load_yaml("models.yaml")
    keys = ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"]
    r = Router(cfg["tiers"], [_named(k) for k in keys], paced=False)
    by = _keys_by_tier(r)
    assert by["quality"] == ["GEMINI_API_KEY_4"]
    for tier in ("bulk", "light", "page", "writer", "embed"):
        assert "GEMINI_API_KEY_4" not in by[tier] and len(by[tier]) == 3, tier


def test_without_the_translator_key_quality_work_stops_quietly_and_nothing_else_changes():
    cfg = load_yaml("models.yaml")
    r = Router(cfg["tiers"], [_named(k) for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")], paced=False)
    assert r.tiers["quality"] == []
    with pytest.raises(QuotaExhausted):
        r.call("quality", "anything")
    assert len({s.key_name for s in r.tiers["page"]}) == 3


def test_usage_is_counted_under_the_secrets_name_not_its_position():
    cfg = load_yaml("models.yaml")
    # the second secret missing: the Translator key is the second backend, but its counter is still "@k4"
    r = Router(cfg["tiers"], [_named("GEMINI_API_KEY"), _named("GEMINI_API_KEY_4")], paced=False)
    q = r.tiers["quality"][0]
    assert q.usage_key == f"{q.id}@k4"
    assert r.tiers["page"][0].usage_key == r.tiers["page"][0].id          # the first key keeps the plain model id


def test_keys_without_a_name_keep_the_old_behaviour():
    """Tests and tools that pass plain fakes: no names, no rules apply to them, counters by position as before."""
    cfg = load_yaml("models.yaml")
    r = Router({"page": cfg["tiers"]["page"]}, [FakeBackend(), FakeBackend()], paced=False)
    assert {s.usage_key for s in r.tiers["page"]} >= {"gemini-3.5-flash-lite", "gemini-3.5-flash-lite@k2"}

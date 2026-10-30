import datetime as dt

from nishpaksh.audio import expired


def test_expired_handles_every_mix_of_aware_and_naive():
    now = dt.datetime(2026, 10, 30, 12, 0)
    old, new = dt.datetime(2026, 10, 28, 12, 0), dt.datetime(2026, 10, 30, 11, 0)
    utc = dt.timezone.utc
    for a, b in ((old, new), (old.replace(tzinfo=utc), new.replace(tzinfo=utc))):
        assert expired(a, now) and not expired(b, now)
        assert expired(a, now.replace(tzinfo=utc)) and not expired(b, now.replace(tzinfo=utc))
    assert not expired(None, now)

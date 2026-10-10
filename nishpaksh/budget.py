"""Shared clock for internal quotas that accrue across hourly runs.

Gemini's daily quota day runs from midnight Pacific to midnight Pacific. Database timestamps
are naive UTC, so these helpers deliberately return/accept naive UTC at the persistence boundary.
Provider hard RPM/TPM/RPD limits remain enforced by the router and are not changed here.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
UTC = dt.timezone.utc


def _aware_utc(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def quota_day_start(now: dt.datetime | None = None) -> dt.datetime:
    """Return this Gemini quota day's midnight as a naive UTC datetime."""
    local = _aware_utc(now).astimezone(PACIFIC)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC).replace(tzinfo=None)


def quota_day_key(now: dt.datetime | None = None) -> str:
    """The Gemini quota-day key (Pacific calendar date) for an internal usage counter."""
    return _aware_utc(now).astimezone(PACIFIC).date().isoformat()


def quota_hours_open(now: dt.datetime | None = None) -> int:
    """Number of hourly quota tranches opened since Pacific midnight, including this hour."""
    utc_now = _aware_utc(now)
    start = quota_day_start(now).replace(tzinfo=UTC)
    elapsed = max(0.0, (utc_now - start).total_seconds())
    # Elapsed real hours also handles the 23/25-hour DST transition days correctly.
    return max(1, int(elapsed // 3600) + 1)


def accrued_limit(per_hour: int, now: dt.datetime | None = None) -> int:
    """Total internal allowance available so far today, before subtracting recorded usage."""
    return max(0, int(per_hour)) * quota_hours_open(now)

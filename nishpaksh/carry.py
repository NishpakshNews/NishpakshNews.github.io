"""Unused hourly allowances roll forward (owner, Oct 11 2026).

Some limits are ours, not Google's: how many articles the writer publishes an hour (`desk_per_hour`), how many
stories are searched for more outlets in a run (`search_stories_per_run`), how many blocked pages and searches go
to Tavily (`tavily_extract_pages_per_run`, `tavily_searches_per_run`). When an hour has little to do they went
unused and were lost, although the next hour might have plenty. Now every hour of the quota day adds its share to
a bank and a run may spend the whole bank (up to `carry_burst_hours` hours' worth at a time). The bank empties at
the end of the quota day, midnight Pacific: the moment Google resets the Gemini quotas (router.quota_day), so
nothing is carried into the next day.

Gemini's own request quotas needed none of this: router.pace_cap is already cumulative (the share of the day
opened so far, minus what was used).

What a run has spent is kept in `quota_usage` under "carry:<name>" for the quota day, like every other count.
The hard limits (Google's per minute / per day, Tavily's monthly credits) are enforced where they always were:
carrying never raises them, it only moves our own pacing.
"""
from __future__ import annotations

import datetime as dt
import logging

from . import config
from .router import PACIFIC, quota_day

log = logging.getLogger(__name__)
PREFIX = "carry:"


def enabled() -> bool:
    return bool(config.SETTINGS.carry_over)


def _pacific(now: dt.datetime | None) -> dt.datetime:
    """`now` (naive UTC, as the database keeps it) in Pacific time."""
    if now is None:
        return dt.datetime.now(PACIFIC)
    return now.replace(tzinfo=dt.timezone.utc).astimezone(PACIFIC) if now.tzinfo is None else now.astimezone(PACIFIC)


def day_of(now: dt.datetime | None = None) -> str:
    """The quota day `now` falls in (Pacific date), the key spending is booked under."""
    return quota_day() if now is None else _pacific(now).date().isoformat()


def day_start(now: dt.datetime | None = None) -> dt.datetime:
    """When the quota day of `now` began, as naive UTC (to compare with the database's times)."""
    p = _pacific(now)
    midnight = dt.datetime.combine(p.date(), dt.time(), tzinfo=PACIFIC)
    return midnight.astimezone(dt.timezone.utc).replace(tzinfo=None)


def hours_open(now: dt.datetime | None = None) -> int:
    """Hours of the quota day whose allowance is open: the ones gone by plus the current one (1 at 00:xx
    Pacific). Counted from the clock, so hours when no run happened still add their share."""
    p = _pacific(now)
    midnight = dt.datetime.combine(p.date(), dt.time(), tzinfo=PACIFIC)
    return int((p.astimezone(dt.timezone.utc) - midnight.astimezone(dt.timezone.utc)).total_seconds() // 3600) + 1


def cap(per_hour: int, now: dt.datetime | None = None) -> int:
    """Most that may have been spent by now in the quota day."""
    return per_hour * hours_open(now)


def burst(per_hour: int, hours: int | None = None) -> int:
    """Most one run may spend, however much is banked."""
    return per_hour * max(1, config.SETTINGS.carry_burst_hours if hours is None else hours)


def left(per_hour: int, spent_today: int, now: dt.datetime | None = None, hours: int | None = None) -> int:
    """What a run may spend now: the bank (this hour's share and every unused one since the day began), at most
    one burst. With carry-over off, just the hour's share, as before."""
    if not enabled():
        return per_hour
    return max(0, min(cap(per_hour, now) - spent_today, burst(per_hour, hours)))


class Bank:
    """Spending of the self-imposed limits that are not visible in the data itself (the desk's seats are: they are
    the articles published today). One row per name and quota day in quota_usage."""

    def __init__(self, store, now: dt.datetime | None = None):
        self.store = store
        self.now = now

    @property
    def day(self) -> str:
        return day_of(self.now)

    def spent(self, name: str) -> int:
        if self.store is None:
            return 0
        try:
            return int(self.store.quota_load(self.day).get(PREFIX + name, (0, 0))[0] or 0)
        except Exception as e:  # noqa: BLE001 - never stops a run: it just gets the plain hourly share
            log.warning("carry: could not read %s: %s", name, e)
            return 0

    def left(self, name: str, per_hour: int, hours: int | None = None) -> int:
        return left(per_hour, self.spent(name) if enabled() else 0, self.now, hours)

    def spend(self, name: str, n: int) -> None:
        if n <= 0 or self.store is None or not enabled():
            return
        try:
            self.store.quota_add(PREFIX + name, self.day, int(n), 0)
        except Exception as e:  # noqa: BLE001
            log.warning("carry: could not book %s: %s", name, e)

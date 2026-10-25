"""The reliable-call layer (B24): one place that knows how an outside call fails and what to do about it.

Failure kinds (a taxonomy, not a guess per call site):
  TRANSIENT  timeout, connection reset, HTTP 5xx / 408 / 429  -> retry with exponential backoff and full jitter
  PERMANENT  HTTP 4xx other than the above, an answer with no content -> never retried, may be remembered
  OPEN       the circuit for this service is open (too many transient failures in a row) -> not even tried

A call returns Outcome(ok, value, kind, error): "could not ask" (TRANSIENT/OPEN) is never the same as "asked, nothing
there" (PERMANENT), so callers can leave the first unmarked and retry it on the next run, and cache only the second.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("nishpaksh.reliable")

TRANSIENT, PERMANENT, OPEN = "transient", "permanent", "open"
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class Outcome:
    ok: bool
    value: Any = None
    kind: str | None = None
    error: str = ""

    @property
    def could_not_ask(self) -> bool:
        return self.kind in (TRANSIENT, OPEN)


class HttpFailure(Exception):
    def __init__(self, status: int, text: str = ""):
        super().__init__(f"HTTP {status}: {text[:200]}")
        self.status = status


def classify(exc: BaseException) -> str:
    status = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return TRANSIENT if status in RETRY_STATUS else PERMANENT
    return TRANSIENT           # timeouts, resets, DNS: the network, not the answer


@dataclass
class Breaker:
    """Opens after `threshold` transient failures in a row; lets one try through after `cooldown` seconds."""
    threshold: int = 5
    cooldown: float = 120.0
    fails: int = 0
    opened_at: float = 0.0

    def allow(self, now: float | None = None) -> bool:
        if self.fails < self.threshold:
            return True
        return (now if now is not None else time.monotonic()) - self.opened_at >= self.cooldown

    def record(self, ok: bool, now: float | None = None) -> None:
        if ok:
            self.fails = 0
            return
        self.fails += 1
        if self.fails >= self.threshold:
            self.opened_at = now if now is not None else time.monotonic()


_breakers: dict[str, Breaker] = {}


def breaker(name: str) -> Breaker:
    return _breakers.setdefault(name, Breaker())


def call(name: str, fn: Callable[[], Any], attempts: int = 3, base: float = 0.5, cap: float = 8.0,
         sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None) -> Outcome:
    """Run fn() with retry on transient failures (full-jitter backoff) behind the service's circuit breaker."""
    b = breaker(name)
    r = rng or random
    last = ""
    for n in range(attempts):
        if not b.allow():
            return Outcome(False, None, OPEN, f"{name}: circuit open")
        try:
            v = fn()
            b.record(True)
            return Outcome(True, v)
        except Exception as e:  # noqa: BLE001
            kind = classify(e)
            last = str(e)[:200]
            if kind == PERMANENT:
                b.record(True)                    # the service answered: it is up
                return Outcome(False, None, PERMANENT, last)
            b.record(False)
            if n + 1 < attempts:
                sleep(r.uniform(0, min(cap, base * (2 ** n))))
    log.info("%s: gave up after %d tries: %s", name, attempts, last)
    return Outcome(False, None, TRANSIENT, last)

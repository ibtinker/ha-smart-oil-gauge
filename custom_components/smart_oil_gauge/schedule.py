"""Work out when each gauge will next upload, and when to poll the portal.

The gauge uploads its hourly readings on an interval set on the portal
(1-24 hours). It only fetches a changed interval *when it uploads*, so a
change made on the portal takes effect after the next upload. We therefore
track two values per gauge:

* ``configured_h``: what the portal says now.
* ``effective_h``: what the gauge is actually using, i.e. the interval that
  was configured as of its most recent upload.

The spacing between observed uploads is a cross-check: if two consecutive
spacings agree with each other but not with ``effective_h``, the measured
spacing wins.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

# Gauges upload a little after the exact interval (about a minute was seen).
GRACE_S = 5 * 60
# If an upload is late, poll again at these offsets after it was due, then
# hourly.
RETRY_OFFSETS_S = (15 * 60, 45 * 60, 105 * 60)
RETRY_EVERY_S = 60 * 60
# Bounds on the time between polls.
MIN_DELAY_S = 60
MAX_DELAY_S = 6 * 3600
# Upload spacings within this many seconds of each other count as agreeing.
SPACING_TOLERANCE_S = 20 * 60
KEEP_UPLOADS = 6


@dataclass(slots=True)
class TankSchedule:
    """Upload schedule state for one gauge."""

    configured_h: int | None = None
    effective_h: int | None = None
    num_tanks: int | None = None
    upload_times: list[float] = field(default_factory=list)
    config_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "configured_h": self.configured_h,
            "effective_h": self.effective_h,
            "num_tanks": self.num_tanks,
            "upload_times": list(self.upload_times),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> TankSchedule:
        """Load from storage, ignoring anything malformed."""
        if not isinstance(raw, dict):
            return cls()
        times = raw.get("upload_times")
        return cls(
            configured_h=_hours(raw.get("configured_h")),
            effective_h=_hours(raw.get("effective_h")),
            num_tanks=_hours(raw.get("num_tanks"), maximum=10),
            upload_times=sorted(
                float(t) for t in times if isinstance(t, int | float) and t > 0
            )[-KEEP_UPLOADS:]
            if isinstance(times, list)
            else [],
        )

    @property
    def pending(self) -> bool:
        """True when the portal has an interval the gauge has not picked up yet."""
        return (
            self.configured_h is not None
            and self.effective_h is not None
            and self.configured_h != self.effective_h
        )

    def update_configured(self, hours: int | None, num_tanks: int | None) -> None:
        """Record the interval the portal shows now."""
        if hours is not None:
            self.configured_h = hours
            if self.effective_h is None:
                # First time we see this gauge: assume it is already in effect.
                self.effective_h = hours
        if num_tanks is not None:
            self.num_tanks = num_tanks

    def record_upload(self, last_read: float) -> None:
        """Record a new upload. The gauge picked up the portal setting with it."""
        if self.upload_times and last_read <= self.upload_times[-1] + 1:
            return
        self.upload_times.append(last_read)
        self.upload_times = self.upload_times[-KEEP_UPLOADS:]
        if self.configured_h is not None:
            self.effective_h = self.configured_h

    def measured_h(self) -> float | None:
        """Interval implied by the last uploads, if they agree with each other."""
        times = self.upload_times
        if len(times) < 3:
            return None
        spacings = [b - a for a, b in zip(times[-3:], times[-2:], strict=False)]
        if abs(spacings[0] - spacings[1]) > SPACING_TOLERANCE_S:
            return None
        return statistics.mean(spacings) / 3600

    def interval(self) -> tuple[float | None, str]:
        """Return the interval in hours to expect, and where it came from."""
        measured = self.measured_h()
        if self.effective_h is not None:
            if (
                measured is not None
                and abs(measured - self.effective_h) * 3600 > SPACING_TOLERANCE_S
            ):
                return measured, "measured"
            return float(self.effective_h), "portal"
        if measured is not None:
            return measured, "measured"
        return None, "unknown"

    def next_expected(self, last_read: float | None) -> float | None:
        """When the next upload should arrive, as a unix timestamp."""
        hours, _ = self.interval()
        if last_read is None or hours is None:
            return None
        return last_read + hours * 3600


def next_poll_delay(
    now: float, expected: list[float], fallback_s: float
) -> tuple[float, float]:
    """Return ``(delay_s, poll_at)`` for the next poll.

    Polls shortly after the earliest expected upload. If an upload is
    overdue, polls at the next retry offset. Without any expectation, uses
    ``fallback_s``. The delay is kept between ``MIN_DELAY_S`` and
    ``MAX_DELAY_S``.
    """
    candidates = [_next_attempt(now, exp + GRACE_S) for exp in expected]
    delay = min(candidates) - now if candidates else fallback_s
    delay = max(MIN_DELAY_S, min(MAX_DELAY_S, delay))
    return delay, now + delay


def _next_attempt(now: float, due: float) -> float:
    """The first scheduled attempt (due, then retries) after ``now``."""
    if due > now:
        return due
    for offset in RETRY_OFFSETS_S:
        if due + offset > now + MIN_DELAY_S:
            return due + offset
    last = due + RETRY_OFFSETS_S[-1]
    steps = int((now + MIN_DELAY_S - last) // RETRY_EVERY_S) + 1
    return last + steps * RETRY_EVERY_S


def _hours(value: Any, maximum: int = 24) -> int | None:
    try:
        hours = int(value)
    except TypeError, ValueError:
        return None
    return hours if 1 <= hours <= maximum else None

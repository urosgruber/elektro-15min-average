"""Fixed 15-minute interval averaging.

The meter's 15-minute power is the energy in the interval divided by 15
minutes. The averager computes the same value from power samples: each value
holds until the next sample (time-weighted). Time with no data, such as a Home
Assistant restart, is left out instead of being filled with a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

INTERVAL = timedelta(minutes=15)
INTERVAL_SECONDS = INTERVAL.total_seconds()


@dataclass(frozen=True)
class FinishedInterval:
    """The result of one finished 15-minute interval."""

    start: datetime
    end: datetime
    average: float | None
    arithmetic: float | None
    sample_count: int
    min_value: float | None
    max_value: float | None
    coverage: float
    restart_detected: bool
    block: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the stored form."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "average": self.average,
            "arithmetic": self.arithmetic,
            "sample_count": self.sample_count,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "coverage": self.coverage,
            "restart_detected": self.restart_detected,
            "block": self.block,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FinishedInterval | None:
        """Read the stored form. Return None if it is not valid."""
        start = _parse(data.get("start"))
        end = _parse(data.get("end"))
        if start is None or end is None:
            return None
        return cls(
            start=start,
            end=end,
            average=data.get("average"),
            arithmetic=data.get("arithmetic"),
            sample_count=int(data.get("sample_count", 0)),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            coverage=float(data.get("coverage", 0.0)),
            restart_detected=bool(data.get("restart_detected", False)),
            block=data.get("block"),
        )


def interval_bounds(ts: datetime) -> tuple[datetime, datetime]:
    """Return the local quarter-hour interval (as UTC) that contains ts."""
    local = dt_util.as_local(ts)
    start_local = local.replace(
        minute=(local.minute // 15) * 15, second=0, microsecond=0
    )
    start = dt_util.as_utc(start_local)
    return start, start + INTERVAL


class IntervalAverager:
    """Accumulate power samples into fixed 15-minute intervals."""

    def __init__(self) -> None:
        self.interval_start: datetime | None = None
        self.interval_end: datetime | None = None
        self.sum_values = 0.0
        self.sample_count = 0
        self.min_value: float | None = None
        self.max_value: float | None = None
        self.last_value: float | None = None
        # Energy (W·s) and measured time (s) of the current interval.
        self.weighted_sum = 0.0
        self.weighted_duration = 0.0
        # The time up to which last_value is already counted. None means that
        # last_value must not be held (no measurement since a restart).
        self.last_sample_ts: datetime | None = None
        self.restart_detected = False

    # --- samples and boundaries -------------------------------------------

    def add_sample(self, value: float, ts: datetime) -> FinishedInterval | None:
        """Add a sample. Return the interval that the sample finished, if any."""
        finished = self.finalize_until(ts)
        self._hold_until(ts)
        self.sum_values += value
        self.sample_count += 1
        self.min_value = value if self.min_value is None else min(self.min_value, value)
        self.max_value = value if self.max_value is None else max(self.max_value, value)
        self.last_value = value
        self.last_sample_ts = ts
        return finished

    def finalize_until(self, ts: datetime) -> FinishedInterval | None:
        """Close every interval that ended at or before ts.

        Return the last closed interval. After a long gap, the empty intervals
        in between are skipped.
        """
        if self.interval_end is None:
            self._start_interval(*interval_bounds(ts), carry=False)
            return None
        if ts < self.interval_end:
            return None

        self._hold_until(self.interval_end)
        finished = self._finished()
        next_start, next_end = interval_bounds(ts)
        # The last value holds into the next interval only when it directly
        # follows the finished one.
        carry = next_start == self.interval_end
        self._start_interval(next_start, next_end, carry=carry)
        return finished

    # --- values -------------------------------------------------------------

    def average(self, now: datetime) -> float | None:
        """Return the time-weighted average of the current interval so far."""
        energy, duration = self._totals(now)
        if duration <= 0:
            # Exactly at the start of an interval: the carried power is the
            # best value, so the sensor does not turn unknown.
            if self.last_sample_ts is not None:
                return self.last_value
            return None
        return energy / duration

    def projected(self, now: datetime) -> float | None:
        """Return the value the current interval ends at if the power stays.

        The energy measured so far, plus the latest power for the rest of the
        interval, divided by the measured time plus the rest.
        """
        if self.interval_end is None or self.last_value is None:
            return None
        if self.last_sample_ts is None:
            return self.average(now)
        energy, duration = self._totals(now)
        until = min(now, self.interval_end)
        remaining = max((self.interval_end - until).total_seconds(), 0.0)
        total = duration + remaining
        if total <= 0:
            return None
        return (energy + self.last_value * remaining) / total

    def arithmetic(self) -> float | None:
        """Return the mean of the samples (for comparison only)."""
        if self.sample_count == 0:
            return None
        return self.sum_values / self.sample_count

    def coverage(self, now: datetime) -> float:
        """Return the measured share of the interval so far, 0 to 1."""
        _, duration = self._totals(now)
        return min(duration / INTERVAL_SECONDS, 1.0)

    # --- storage ------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the stored form of the current interval."""
        return {
            "interval_start": _fmt(self.interval_start),
            "interval_end": _fmt(self.interval_end),
            "sum_values": self.sum_values,
            "sample_count": self.sample_count,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "last_value": self.last_value,
            "weighted_sum": self.weighted_sum,
            "weighted_duration": self.weighted_duration,
            "last_sample_ts": _fmt(self.last_sample_ts),
        }

    def restore(self, data: dict[str, Any], now: datetime) -> bool:
        """Restore the current interval after a restart.

        Return False, and keep nothing, when the stored interval already
        ended. The time while Home Assistant was down is not counted.
        """
        end = _parse(data.get("interval_end"))
        start = _parse(data.get("interval_start"))
        if start is None or end is None or end <= now:
            return False
        self.interval_start = start
        self.interval_end = end
        self.sum_values = float(data.get("sum_values", 0.0))
        self.sample_count = int(data.get("sample_count", 0))
        self.min_value = data.get("min_value")
        self.max_value = data.get("max_value")
        self.last_value = data.get("last_value")
        self.weighted_sum = float(data.get("weighted_sum", 0.0))
        self.weighted_duration = float(data.get("weighted_duration", 0.0))
        self.last_sample_ts = None
        self.restart_detected = True
        return True

    # --- internals ----------------------------------------------------------

    def _totals(self, now: datetime) -> tuple[float, float]:
        energy = self.weighted_sum
        duration = self.weighted_duration
        if self.last_value is not None and self.last_sample_ts is not None:
            until = now if self.interval_end is None else min(now, self.interval_end)
            delta = (until - self.last_sample_ts).total_seconds()
            if delta > 0:
                energy += self.last_value * delta
                duration += delta
        return energy, duration

    def _hold_until(self, ts: datetime) -> None:
        if self.last_value is None or self.last_sample_ts is None:
            return
        delta = (ts - self.last_sample_ts).total_seconds()
        if delta <= 0:
            return
        self.weighted_sum += self.last_value * delta
        self.weighted_duration += delta
        self.last_sample_ts = ts

    def _finished(self) -> FinishedInterval:
        assert self.interval_start is not None and self.interval_end is not None
        average = (
            self.weighted_sum / self.weighted_duration
            if self.weighted_duration > 0
            else None
        )
        return FinishedInterval(
            start=self.interval_start,
            end=self.interval_end,
            average=average,
            arithmetic=self.arithmetic(),
            sample_count=self.sample_count,
            min_value=self.min_value,
            max_value=self.max_value,
            coverage=min(self.weighted_duration / INTERVAL_SECONDS, 1.0),
            restart_detected=self.restart_detected,
        )

    def _start_interval(self, start: datetime, end: datetime, carry: bool) -> None:
        self.interval_start = start
        self.interval_end = end
        self.sum_values = 0.0
        self.sample_count = 0
        self.min_value = None
        self.max_value = None
        self.weighted_sum = 0.0
        self.weighted_duration = 0.0
        self.restart_detected = False
        if carry and self.last_value is not None and self.last_sample_ts is not None:
            self.last_sample_ts = start
        else:
            self.last_sample_ts = None


def _fmt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return dt_util.as_utc(parsed)
    return parsed

"""Sensor for Elektro 15-minute power average."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_METHOD,
    CONF_NAME,
    CONF_PRECISION,
    CONF_SOURCE_ENTITY,
    DEFAULT_METHOD,
    DEFAULT_PRECISION,
    DOMAIN,
    METHOD_ARITHMETIC,
    METHOD_TIME_WEIGHTED,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class IntervalAverages:
    """Averages for a completed or in-progress interval."""

    arithmetic: float | None
    time_weighted: float | None


@dataclass
class FinalInterval:
    """Result for a completed interval."""

    averages: IntervalAverages
    interval_start: datetime
    interval_end: datetime


class IntervalAverager:
    """Accumulate sensor values into fixed 15-minute intervals."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")

        self.interval_start: datetime | None = None
        self.interval_end: datetime | None = None

        self.sum_values = 0.0
        self.sample_count = 0
        self.min_value: float | None = None
        self.max_value: float | None = None
        self.last_value: float | None = None

        self.weighted_sum = 0.0
        self.weighted_duration = 0.0
        self.last_sample_ts: datetime | None = None

        self.restart_detected = False
        self.restart_at: datetime | None = None

    async def async_restore(self) -> bool:
        """Restore state from storage."""
        data = await self._store.async_load()
        if not data:
            return False

        self.interval_start = _parse_datetime(data.get("interval_start"))
        self.interval_end = _parse_datetime(data.get("interval_end"))
        self.sum_values = float(data.get("sum_values", 0.0))
        self.sample_count = int(data.get("sample_count", 0))
        self.min_value = data.get("min_value")
        self.max_value = data.get("max_value")
        self.last_value = data.get("last_value")
        self.weighted_sum = float(data.get("weighted_sum", 0.0))
        self.weighted_duration = float(data.get("weighted_duration", 0.0))
        self.last_sample_ts = _parse_datetime(data.get("last_sample_ts"))

        # Mark the interval as potentially partial after restart.
        self.restart_detected = True
        self.restart_at = dt_util.utcnow()
        return True

    def snapshot(self) -> dict[str, Any]:
        """Serialize the current accumulator state."""
        return {
            "interval_start": _format_datetime(self.interval_start),
            "interval_end": _format_datetime(self.interval_end),
            "sum_values": self.sum_values,
            "sample_count": self.sample_count,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "last_value": self.last_value,
            "weighted_sum": self.weighted_sum,
            "weighted_duration": self.weighted_duration,
            "last_sample_ts": _format_datetime(self.last_sample_ts),
        }

    async def async_save(self) -> None:
        """Persist state to storage."""
        await self._store.async_save(self.snapshot())

    def ensure_interval(self, ts: datetime) -> None:
        """Ensure interval bounds are set for the given timestamp."""
        if self.interval_start is not None and self.interval_end is not None:
            return

        start, end = _calc_interval_bounds(ts)
        self._reset_interval(start, end, carry_last_value=False)

    def finalize_until(self, ts: datetime) -> FinalInterval | None:
        """Finalize intervals until the timestamp and return the last final averages."""
        if self.interval_end is None:
            self.ensure_interval(ts)

        final_result: FinalInterval | None = None
        while self.interval_end is not None and ts >= self.interval_end:
            finished_start = self.interval_start
            finished_end = self.interval_end
            self._update_weighted_until(self.interval_end)
            final_averages = self.current_averages()
            if finished_start is not None and finished_end is not None:
                final_result = FinalInterval(
                    averages=final_averages,
                    interval_start=finished_start,
                    interval_end=finished_end,
                )
            next_start = self.interval_end
            next_end = next_start + timedelta(minutes=15)
            self._reset_interval(next_start, next_end, carry_last_value=True)

        return final_result

    def add_sample(self, value: float, ts: datetime) -> None:
        """Add a new sample to the accumulator."""
        self.ensure_interval(ts)
        self.finalize_until(ts)
        self._update_weighted_until(ts)

        self.sum_values += value
        self.sample_count += 1
        self.min_value = value if self.min_value is None else min(self.min_value, value)
        self.max_value = value if self.max_value is None else max(self.max_value, value)
        self.last_value = value
        self.last_sample_ts = ts

    def current_averages(self) -> IntervalAverages:
        """Return arithmetic and time-weighted averages for the current interval."""
        arithmetic = None
        time_weighted = None
        if self.sample_count > 0:
            arithmetic = self.sum_values / self.sample_count
        if self.weighted_duration > 0:
            time_weighted = self.weighted_sum / self.weighted_duration
        return IntervalAverages(arithmetic=arithmetic, time_weighted=time_weighted)

    def _update_weighted_until(self, ts: datetime) -> None:
        if self.last_value is None or self.last_sample_ts is None:
            return
        delta = (ts - self.last_sample_ts).total_seconds()
        if delta <= 0:
            return
        self.weighted_sum += self.last_value * delta
        self.weighted_duration += delta
        self.last_sample_ts = ts

    def _reset_interval(
        self, start: datetime, end: datetime, carry_last_value: bool
    ) -> None:
        self.interval_start = start
        self.interval_end = end
        self.sum_values = 0.0
        self.sample_count = 0
        self.min_value = None
        self.max_value = None
        self.weighted_sum = 0.0
        self.weighted_duration = 0.0

        if carry_last_value and self.last_value is not None:
            self.last_sample_ts = start
        else:
            self.last_sample_ts = None

        self.restart_detected = False
        self.restart_at = None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the sensor for a config entry."""
    async_add_entities([PowerIntervalSensor(hass, entry)])


class PowerIntervalSensor(SensorEntity):
    """Sensor that exposes 15-minute average power."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._averager = IntervalAverager(hass, entry.entry_id)

        self._source_entity = entry.data[CONF_SOURCE_ENTITY]
        self._method = entry.options.get(
            CONF_METHOD, entry.data.get(CONF_METHOD, DEFAULT_METHOD)
        )
        precision = entry.options.get(
            CONF_PRECISION, entry.data.get(CONF_PRECISION, DEFAULT_PRECISION)
        )
        self._precision = int(precision) if precision is not None else None
        self._custom_name = entry.data.get(CONF_NAME)

        self._attr_unique_id = entry.entry_id
        self._attr_name = self._custom_name or self._default_name()

        self._attr_native_value: float | None = None
        self._attrs: dict[str, Any] = {}

        self._unsub_state = None
        self._unsub_boundary = None

    async def async_added_to_hass(self) -> None:
        restored = await self._averager.async_restore()
        if restored:
            self._update_from_averages(self._averager.current_averages())
            self.async_write_ha_state()

        state = self._hass.states.get(self._source_entity)
        if state is not None:
            self._handle_state(state)

        self._unsub_state = async_track_state_change_event(
            self._hass, [self._source_entity], self._handle_state_change
        )
        self._unsub_boundary = async_track_time_change(
            self._hass,
            self._handle_boundary,
            minute=[0, 15, 30, 45],
            second=0,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None

    @callback
    def _handle_boundary(self, now: datetime) -> None:
        final_result = self._averager.finalize_until(dt_util.as_utc(now))
        if final_result is None:
            return

        self._update_from_averages(
            final_result.averages,
            interval_start=final_result.interval_start,
            interval_end=final_result.interval_end,
        )
        self.async_write_ha_state()
        self._hass.async_create_task(self._averager.async_save())

    @callback
    def _handle_state_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self._handle_state(new_state)

    @callback
    def _handle_state(self, state) -> None:
        if state.state in ("unknown", "unavailable"):
            return

        try:
            value = float(state.state)
        except (TypeError, ValueError):
            _LOGGER.debug("Skipping non-numeric state: %s", state.state)
            return

        ts = dt_util.as_utc(state.last_updated)
        self._averager.add_sample(value, ts)

        self._update_from_averages(self._averager.current_averages())
        self.async_write_ha_state()
        self._hass.async_create_task(self._averager.async_save())

    def _default_name(self) -> str:
        source_state = self._hass.states.get(self._source_entity)
        if source_state is not None:
            friendly = source_state.attributes.get("friendly_name")
            if friendly:
                return f"{friendly} 15-minute average"
        return f"{self._source_entity} 15-minute average"

    def _update_from_averages(
        self,
        averages: IntervalAverages,
        interval_start: datetime | None = None,
        interval_end: datetime | None = None,
    ) -> None:
        arithmetic = averages.arithmetic
        time_weighted = averages.time_weighted

        rounded_arithmetic = self._round(arithmetic)
        rounded_time_weighted = self._round(time_weighted)

        if self._method == METHOD_TIME_WEIGHTED:
            self._attr_native_value = rounded_time_weighted
        else:
            self._attr_native_value = rounded_arithmetic

        interval_start = interval_start or self._averager.interval_start
        interval_end = interval_end or self._averager.interval_end

        self._attrs = {
            "average_method": self._method,
            "arithmetic_average": rounded_arithmetic,
            "time_weighted_average": rounded_time_weighted,
            "interval_start": _format_datetime(interval_start, local=True),
            "interval_end": _format_datetime(interval_end, local=True),
            "sample_count": self._averager.sample_count,
            "min_value": self._round(self._averager.min_value),
            "max_value": self._round(self._averager.max_value),
            "last_value": self._round(self._averager.last_value),
            "source_entity": self._source_entity,
            "restart_detected": self._averager.restart_detected,
            "restart_at": _format_datetime(self._averager.restart_at, local=True),
        }

    def _round(self, value: float | None) -> float | None:
        if value is None:
            return None
        if self._precision is None:
            return value
        return round(value, self._precision)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs


def _calc_interval_bounds(ts: datetime) -> tuple[datetime, datetime]:
    local = dt_util.as_local(ts)
    start_minute = (local.minute // 15) * 15
    start_local = local.replace(minute=start_minute, second=0, microsecond=0)
    end_local = start_local + timedelta(minutes=15)
    return dt_util.as_utc(start_local), dt_util.as_utc(end_local)


def _format_datetime(dt_value: datetime | None, local: bool = False) -> str | None:
    if dt_value is None:
        return None
    if local:
        dt_value = dt_util.as_local(dt_value)
    return dt_value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return dt_util.as_utc(parsed)
    return parsed

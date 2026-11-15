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
    CONF_FINAL_SENSOR,
    CONF_ENTITY_PICTURE,
    CONF_IMPORT_ONLY,
    CONF_METHOD,
    CONF_NAME,
    CONF_SOURCE_ENTITY,
    DEFAULT_FINAL_SENSOR,
    DEFAULT_ENTITY_PICTURE,
    DEFAULT_IMPORT_ONLY,
    DEFAULT_METHOD,
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
class IntervalStats:
    """Snapshot of interval stats used for attributes."""

    sample_count: int
    min_value: float | None
    max_value: float | None
    last_value: float | None
    restart_detected: bool
    restart_at: datetime | None


@dataclass
class FinalInterval:
    """Result for a completed interval."""

    averages: IntervalAverages
    stats: IntervalStats
    interval_start: datetime
    interval_end: datetime


class IntervalAverager:
    """Accumulate sensor values into fixed 15-minute intervals."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, storage_suffix: str = ""
    ) -> None:
        # Use separate storage keys per sensor to avoid collisions.
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}{storage_suffix}")

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

        interval_end = _parse_datetime(data.get("interval_end"))
        if interval_end is None or interval_end <= dt_util.utcnow():
            # The stored interval ended while Home Assistant was down. Its
            # data is incomplete, so start fresh instead of finalizing it.
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
        # The power while Home Assistant was down is unknown. Do not hold the
        # last value over the downtime; weight again from the next sample.
        self.last_sample_ts = None

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

        # Initialize to the quarter-hour window that contains ts.
        start, end = _calc_interval_bounds(ts)
        self._reset_interval(start, end, carry_last_value=False)

    def finalize_until(self, ts: datetime) -> FinalInterval | None:
        """Finalize intervals until the timestamp and return the last final averages."""
        if self.interval_end is None:
            self.ensure_interval(ts)

        final_result: FinalInterval | None = None
        while self.interval_end is not None and ts >= self.interval_end:
            # Close out the current interval, then roll forward in 15-minute steps.
            finished_start = self.interval_start
            finished_end = self.interval_end
            self._update_weighted_until(self.interval_end)
            final_averages = self.current_averages()
            final_stats = self._stats_snapshot()
            if finished_start is not None and finished_end is not None:
                final_result = FinalInterval(
                    averages=final_averages,
                    stats=final_stats,
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
        # Time-weighted average treats the last value as holding until this sample.
        self._update_weighted_until(ts)

        self.sum_values += value
        self.sample_count += 1
        self.min_value = value if self.min_value is None else min(self.min_value, value)
        self.max_value = value if self.max_value is None else max(self.max_value, value)
        self.last_value = value
        self.last_sample_ts = ts

    def current_averages(self, until: datetime | None = None) -> IntervalAverages:
        """Return arithmetic and time-weighted averages for the current interval.

        With ``until``, the time-weighted average also holds the last value
        from the last sample up to that time (capped at the interval end).
        """
        arithmetic = None
        time_weighted = None
        if self.sample_count > 0:
            arithmetic = self.sum_values / self.sample_count

        weighted_sum = self.weighted_sum
        weighted_duration = self.weighted_duration
        if (
            until is not None
            and self.last_value is not None
            and self.last_sample_ts is not None
        ):
            if self.interval_end is not None:
                until = min(until, self.interval_end)
            delta = (until - self.last_sample_ts).total_seconds()
            if delta > 0:
                weighted_sum += self.last_value * delta
                weighted_duration += delta

        if weighted_duration > 0:
            time_weighted = weighted_sum / weighted_duration
        return IntervalAverages(arithmetic=arithmetic, time_weighted=time_weighted)

    def _stats_snapshot(self) -> IntervalStats:
        """Capture interval stats before the accumulator resets."""
        return IntervalStats(
            sample_count=self.sample_count,
            min_value=self.min_value,
            max_value=self.max_value,
            last_value=self.last_value,
            restart_detected=self.restart_detected,
            restart_at=self.restart_at,
        )

    def _update_weighted_until(self, ts: datetime) -> None:
        if self.last_value is None or self.last_sample_ts is None:
            return
        delta = (ts - self.last_sample_ts).total_seconds()
        if delta <= 0:
            return
        # Accumulate value * duration to compute time-weighted average.
        self.weighted_sum += self.last_value * delta
        self.weighted_duration += delta
        self.last_sample_ts = ts

    def _reset_interval(
        self, start: datetime, end: datetime, carry_last_value: bool
    ) -> None:
        # Reset counters for a new interval while preserving last_value for weighting.
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
    create_final = entry.options.get(
        CONF_FINAL_SENSOR, entry.data.get(CONF_FINAL_SENSOR, DEFAULT_FINAL_SENSOR)
    )
    sensors: list[SensorEntity] = [PowerIntervalSensor(hass, entry)]
    if create_final:
        sensors.append(FinalizedIntervalSensor(hass, entry))
    async_add_entities(sensors)


class PowerIntervalSensor(SensorEntity):
    """Sensor that exposes 15-minute average power."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        name_suffix: str = "",
        unique_id_suffix: str = "",
        storage_suffix: str = "",
        publish_live: bool = True,
        use_final_stats: bool = False,
        publish_on_restore: bool = True,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._averager = IntervalAverager(
            hass, entry.entry_id, storage_suffix=storage_suffix
        )
        # Control when the entity publishes state updates.
        self._publish_live = publish_live
        self._use_final_stats = use_final_stats
        self._publish_on_restore = publish_on_restore

        self._source_entity = entry.data[CONF_SOURCE_ENTITY]
        self._method = entry.options.get(
            CONF_METHOD, entry.data.get(CONF_METHOD, DEFAULT_METHOD)
        )
        entity_picture = entry.options.get(
            CONF_ENTITY_PICTURE,
            entry.data.get(CONF_ENTITY_PICTURE, DEFAULT_ENTITY_PICTURE),
        )
        self._import_only = entry.options.get(
            CONF_IMPORT_ONLY, entry.data.get(CONF_IMPORT_ONLY, DEFAULT_IMPORT_ONLY)
        )
        self._custom_name = entry.data.get(CONF_NAME)

        base_name = self._custom_name or self._default_name()
        self._attr_unique_id = f"{entry.entry_id}{unique_id_suffix}"
        self._attr_name = f"{base_name}{name_suffix}" if name_suffix else base_name

        self._attr_native_value: float | None = None
        self._attrs: dict[str, Any] = {}
        if entity_picture:
            self._attr_entity_picture = entity_picture

        self._unsub_state = None
        self._unsub_boundary = None

    async def async_added_to_hass(self) -> None:
        restored = await self._averager.async_restore()
        if restored and self._publish_on_restore:
            self._update_from_averages(
                self._averager.current_averages(until=dt_util.utcnow())
            )
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
        # Finalize the interval at the wall-clock quarter-hour boundary.
        final_result = self._averager.finalize_until(dt_util.as_utc(now))
        if final_result is None:
            return

        self._update_from_averages(
            final_result.averages,
            interval_start=final_result.interval_start,
            interval_end=final_result.interval_end,
            stats=final_result.stats if self._use_final_stats else None,
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

        if self._import_only and value < 0:
            # Export: the meter's import register does not count it.
            value = 0.0

        # Ignore a state older than the last sample (for example the source's
        # unchanged state at startup); it must not move the interval back.
        ts = max(dt_util.as_utc(state.last_updated), self._sample_floor())
        self._averager.add_sample(value, ts)

        if self._publish_live:
            self._update_from_averages(self._averager.current_averages(until=ts))
            self.async_write_ha_state()
        self._hass.async_create_task(self._averager.async_save())

    def _sample_floor(self) -> datetime:
        last = self._averager.last_sample_ts
        start = self._averager.interval_start
        floors = [t for t in (last, start) if t is not None]
        return max(floors) if floors else dt_util.as_utc(dt_util.utcnow())

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
        stats: IntervalStats | None = None,
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

        stats_source = stats or IntervalStats(
            sample_count=self._averager.sample_count,
            min_value=self._averager.min_value,
            max_value=self._averager.max_value,
            last_value=self._averager.last_value,
            restart_detected=self._averager.restart_detected,
            restart_at=self._averager.restart_at,
        )

        self._attrs = {
            "average_method": self._method,
            "arithmetic_average": rounded_arithmetic,
            "time_weighted_average": rounded_time_weighted,
            "interval_start": _format_datetime(interval_start, local=True),
            "interval_end": _format_datetime(interval_end, local=True),
            "sample_count": stats_source.sample_count,
            "min_value": self._round(stats_source.min_value),
            "max_value": self._round(stats_source.max_value),
            "last_value": self._round(stats_source.last_value),
            "source_entity": self._source_entity,
            "import_only": self._import_only,
            "restart_detected": stats_source.restart_detected,
            "restart_at": _format_datetime(stats_source.restart_at, local=True),
        }

    def _round(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs


class FinalizedIntervalSensor(PowerIntervalSensor):
    """Sensor that only publishes at 15-minute boundaries."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        # Avoid writing a partial interval at startup; update only when finalized.
        super().__init__(
            hass,
            entry,
            name_suffix=" (final)",
            unique_id_suffix="_final",
            storage_suffix="_final",
            publish_live=False,
            use_final_stats=True,
            publish_on_restore=False,
        )


def _calc_interval_bounds(ts: datetime) -> tuple[datetime, datetime]:
    local = dt_util.as_local(ts)
    start_minute = (local.minute // 15) * 15
    # Align to the local quarter-hour wall-clock boundaries.
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

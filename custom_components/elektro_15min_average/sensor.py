"""Sensors of the Elektro 15-minute average integration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ElektroAverageConfigEntry
from .entity import AverageEntity
from .tariff import (
    BLOCKS,
    is_high_season,
    is_working_day,
    next_change,
    next_cheap_start,
)
from .tracker import AverageTracker


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElektroAverageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of one entry."""
    tracker = entry.runtime_data
    entities: list[SensorEntity] = [
        CurrentAverageSensor(entry, tracker),
        ProjectedSensor(entry, tracker),
        LastIntervalSensor(entry, tracker),
        TariffBlockSensor(entry, tracker),
    ]
    entities += [MonthlyPeakSensor(entry, tracker, block) for block in BLOCKS]
    async_add_entities(entities)


def _round(value: float | None) -> int | None:
    return None if value is None else round(value)


def _local(value: datetime | None) -> str | None:
    return None if value is None else dt_util.as_local(value).isoformat()


class PowerSensor(AverageEntity, SensorEntity):
    """A power sensor in W."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0


class CurrentAverageSensor(PowerSensor):
    """The average of the current interval so far."""

    _attr_translation_key = "average"
    # These change with every sample. Keep them out of the database.
    _unrecorded_attributes = frozenset(
        {"sample_count", "min_value", "max_value", "last_value", "coverage"}
    )

    @callback
    def _refresh(self) -> None:
        avg = self._tracker.averager
        now = dt_util.utcnow()
        self._attr_native_value = _round(avg.average(now))
        self._attr_extra_state_attributes = {
            "interval_start": _local(avg.interval_start),
            "interval_end": _local(avg.interval_end),
            "block": self._tracker.current_block(now),
            "coverage": round(avg.coverage(now), 3),
            "sample_count": avg.sample_count,
            "min_value": _round(avg.min_value),
            "max_value": _round(avg.max_value),
            "last_value": _round(avg.last_value),
            "restart_detected": avg.restart_detected,
            "source_entity": self._tracker.source_entity,
            "import_only": self._tracker.import_only,
        }


class ProjectedSensor(PowerSensor):
    """The value the current interval ends at if the power stays as it is."""

    _attr_translation_key = "projected"
    _unique_id_suffix = "_projected"
    _unrecorded_attributes = frozenset({"headroom"})

    @callback
    def _refresh(self) -> None:
        now = dt_util.utcnow()
        projected = self._tracker.averager.projected(now)
        agreed = self._tracker.agreed_power_now(now)
        self._attr_native_value = _round(projected)
        self._attr_extra_state_attributes = {
            "interval_end": _local(self._tracker.averager.interval_end),
            "block": self._tracker.current_block(now),
            "agreed_power": _round(agreed),
            "headroom": (
                _round(agreed - projected)
                if agreed is not None and projected is not None
                else None
            ),
        }


class LastIntervalSensor(PowerSensor):
    """The result of the last finished interval. It survives a restart."""

    _attr_translation_key = "last_interval"
    _unique_id_suffix = "_final"

    @callback
    def _refresh(self) -> None:
        last = self._tracker.last_interval
        if last is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return
        self._attr_native_value = _round(last.average)
        agreed = self._tracker.agreed_power.get(last.block) if last.block else None
        attrs: dict[str, Any] = {
            "interval_start": _local(last.start),
            "interval_end": _local(last.end),
            "block": last.block,
            "agreed_power": _round(agreed),
            "exceeded": (
                agreed is not None
                and last.average is not None
                and last.average > agreed
            ),
            "coverage": round(last.coverage, 3),
            "sample_count": last.sample_count,
            "min_value": _round(last.min_value),
            "max_value": _round(last.max_value),
            "arithmetic_average": _round(last.arithmetic),
            "restart_detected": last.restart_detected,
        }
        self._attr_extra_state_attributes = attrs


class TariffBlockSensor(AverageEntity, SensorEntity):
    """The network tariff block now (1 is the most expensive)."""

    _attr_translation_key = "tariff_block"
    _unique_id_suffix = "_tariff_block"

    @callback
    def _refresh(self) -> None:
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        self._attr_native_value = self._tracker.current_block(now)
        today_is_working = self._tracker.working_day(local)

        def working_day(day: date) -> bool:
            # The holiday source gives only the state of today. Other days
            # use the built-in holiday list.
            return today_is_working if day == local.date() else is_working_day(day)

        # A block entity gives the current block, and the tables cannot
        # forecast it. Then there is no forecast.
        source = self._tracker.block_source()
        change = next_change(local, working_day) if source == "calculated" else None
        cheap = next_cheap_start(local, working_day) if source == "calculated" else None
        self._attr_extra_state_attributes = {
            "next_change": change[0].isoformat() if change else None,
            "next_block": change[1] if change else None,
            "next_cheap_start": cheap.isoformat() if cheap else None,
            "source": source,
            "high_season": is_high_season(local.date()),
            "working_day": today_is_working,
            "agreed_power": _round(self._tracker.agreed_power_now(now)),
        }


class MonthlyPeakSensor(PowerSensor):
    """The highest finished interval of one block in the current month."""

    _attr_translation_key = "monthly_peak"

    def __init__(self, entry: ConfigEntry, tracker: AverageTracker, block: int) -> None:
        self._block = block
        self._unique_id_suffix = f"_monthly_peak_{block}"
        super().__init__(entry, tracker)
        self._attr_translation_placeholders = {"block": str(block)}

    @callback
    def _refresh(self) -> None:
        peak = self._tracker.peaks.get(self._block)
        agreed = self._tracker.agreed_power.get(self._block)
        self._attr_native_value = None if peak is None else round(peak.value)
        self._attr_extra_state_attributes = {
            "month": self._tracker.peak_month,
            "peak_start": _local(peak.start) if peak else None,
            "agreed_power": _round(agreed),
        }

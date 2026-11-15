"""Sensors of the Elektro 15-minute average integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ElektroAverageConfigEntry
from .const import CONF_NAME, DOMAIN
from .tracker import AverageTracker


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElektroAverageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the three sensors of one entry."""
    tracker = entry.runtime_data
    async_add_entities(
        [
            CurrentAverageSensor(entry, tracker),
            ProjectedSensor(entry, tracker),
            LastIntervalSensor(entry, tracker),
        ]
    )


def _round(value: float | None) -> int | None:
    return None if value is None else round(value)


def _local(value: datetime | None) -> str | None:
    return None if value is None else dt_util.as_local(value).isoformat()


class AverageSensor(SensorEntity):
    """Base sensor: one device per entry, power in W."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0
    _unique_id_suffix = ""

    def __init__(
        self, entry: ElektroAverageConfigEntry, tracker: AverageTracker
    ) -> None:
        self._tracker = tracker
        # Keep the unique IDs of version 0.x, so the entity IDs stay.
        self._attr_unique_id = f"{entry.entry_id}{self._unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME) or entry.title,
            model="15-minute average power",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self._refresh()
        self.async_on_remove(self._tracker.async_add_listener(self._update))

    @callback
    def _update(self) -> None:
        self._refresh()
        self.async_write_ha_state()

    @callback
    def _refresh(self) -> None:
        raise NotImplementedError


class CurrentAverageSensor(AverageSensor):
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
            "coverage": round(avg.coverage(now), 3),
            "sample_count": avg.sample_count,
            "min_value": _round(avg.min_value),
            "max_value": _round(avg.max_value),
            "last_value": _round(avg.last_value),
            "restart_detected": avg.restart_detected,
            "source_entity": self._tracker.source_entity,
            "import_only": self._tracker.import_only,
        }


class ProjectedSensor(AverageSensor):
    """The value the current interval ends at if the power stays as it is."""

    _attr_translation_key = "projected"
    _unique_id_suffix = "_projected"

    @callback
    def _refresh(self) -> None:
        avg = self._tracker.averager
        self._attr_native_value = _round(avg.projected(dt_util.utcnow()))
        self._attr_extra_state_attributes = {
            "interval_end": _local(avg.interval_end),
        }


class LastIntervalSensor(AverageSensor):
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
        attrs: dict[str, Any] = {
            "interval_start": _local(last.start),
            "interval_end": _local(last.end),
            "coverage": round(last.coverage, 3),
            "sample_count": last.sample_count,
            "min_value": _round(last.min_value),
            "max_value": _round(last.max_value),
            "arithmetic_average": _round(last.arithmetic),
            "restart_detected": last.restart_detected,
        }
        self._attr_extra_state_attributes = attrs

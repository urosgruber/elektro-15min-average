"""Binary sensor of the Elektro 15-minute average integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ElektroAverageConfigEntry
from .entity import AverageEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElektroAverageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the agreed-power warning of one entry."""
    async_add_entities([AgreedPowerExceededSensor(entry, entry.runtime_data)])


class AgreedPowerExceededSensor(AverageEntity, BinarySensorEntity):
    """On when the projected value is above the agreed power of the block.

    It is off when the current block has no agreed power.
    """

    _attr_translation_key = "agreed_power_exceeded"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _unique_id_suffix = "_agreed_power_exceeded"
    _unrecorded_attributes = frozenset({"projected", "headroom"})

    @callback
    def _refresh(self) -> None:
        now = dt_util.utcnow()
        projected = self._tracker.averager.projected(now)
        agreed = self._tracker.agreed_power_now(now)
        known = agreed is not None and projected is not None
        self._attr_is_on = known and projected > agreed
        self._attr_extra_state_attributes = {
            "block": self._tracker.current_block(now),
            "agreed_power": None if agreed is None else round(agreed),
            "projected": None if projected is None else round(projected),
            "headroom": round(agreed - projected) if known else None,
        }

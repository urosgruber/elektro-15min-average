"""Base entity of the Elektro 15-minute average integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_NAME, DOMAIN
from .tracker import AverageTracker


class AverageEntity(Entity):
    """An entity of the device of one entry. It reads from the tracker."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _unique_id_suffix = ""

    def __init__(self, entry: ConfigEntry, tracker: AverageTracker) -> None:
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

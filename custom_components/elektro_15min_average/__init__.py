"""The Elektro 15-minute average integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_IMPORT_ONLY,
    CONF_NAME,
    CONF_SOURCE_ENTITY,
    DEFAULT_IMPORT_ONLY,
    DOMAIN,
    STORAGE_VERSION,
)
from .tracker import AverageTracker, store_key

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ElektroAverageConfigEntry = ConfigEntry[AverageTracker]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def source_name(hass: HomeAssistant, entity_id: str) -> str:
    """Return a readable name of the source sensor."""
    if (reg := er.async_get(hass).async_get(entity_id)) is not None:
        if name := reg.name or reg.original_name:
            return name
    if (state := hass.states.get(entity_id)) is not None:
        if name := state.attributes.get("friendly_name"):
            return name
    return entity_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ElektroAverageConfigEntry
) -> bool:
    """Start to follow the source sensor of one entry."""
    tracker = AverageTracker(hass, entry)
    await tracker.async_start()
    entry.runtime_data = tracker
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await tracker.async_stop()
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ElektroAverageConfigEntry
) -> bool:
    """Stop and save the interval state."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stop()
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: ElektroAverageConfigEntry
) -> None:
    """Delete the stored interval state."""
    await Store(hass, STORAGE_VERSION, store_key(entry.entry_id)).async_remove()


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an entry of version 0.x (config entry version 1).

    Version 1 had the options average_method, create_final_sensor and
    entity_picture. Version 2 always uses the time-weighted average, always
    creates all sensors, and uses the brand icon. The second store of the
    old finalized-only sensor is deleted.
    """
    if entry.version > 2:
        return False
    if entry.version == 1:
        source = entry.data[CONF_SOURCE_ENTITY]
        data = {
            CONF_SOURCE_ENTITY: source,
            CONF_NAME: entry.data.get(CONF_NAME) or source_name(hass, source),
        }
        options = {
            CONF_IMPORT_ONLY: entry.options.get(
                CONF_IMPORT_ONLY, entry.data.get(CONF_IMPORT_ONLY, DEFAULT_IMPORT_ONLY)
            )
        }
        await Store(
            hass, STORAGE_VERSION, f"{store_key(entry.entry_id)}_final"
        ).async_remove()
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, title=data[CONF_NAME], version=2
        )
        _LOGGER.debug("Migrated %s to version 2", entry.entry_id)
    return True

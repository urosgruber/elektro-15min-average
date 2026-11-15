"""Diagnostics of the Elektro 15-minute average integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import ElektroAverageConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ElektroAverageConfigEntry
) -> dict[str, Any]:
    """Return the settings and the interval state of one entry.

    The data holds power values and times only. Nothing is redacted.
    """
    tracker = entry.runtime_data
    avg = tracker.averager
    now = dt_util.utcnow()
    source = hass.states.get(tracker.source_entity)
    return {
        "entry": {
            "version": entry.version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "source": {
            "entity_id": tracker.source_entity,
            "state": source.state if source else None,
            "unit": source.attributes.get("unit_of_measurement") if source else None,
            "last_updated": source.last_updated.isoformat() if source else None,
        },
        "current_interval": {
            **avg.to_dict(),
            "average": avg.average(now),
            "projected": avg.projected(now),
            "coverage": avg.coverage(now),
            "restart_detected": avg.restart_detected,
        },
        "last_interval": (
            tracker.last_interval.to_dict() if tracker.last_interval else None
        ),
    }

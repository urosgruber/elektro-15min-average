"""Follow the source sensor and keep the interval state of one entry."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfPower
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .averager import FinishedInterval, IntervalAverager
from .const import (
    CONF_IMPORT_ONLY,
    CONF_SOURCE_ENTITY,
    DEFAULT_IMPORT_ONLY,
    DOMAIN,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# How often the live and projected values move on between source updates.
TICK = timedelta(seconds=10)
# Save the state at most this often (seconds); a restart loses less than this.
SAVE_DELAY = 30

_UNIT_FACTOR = {
    UnitOfPower.WATT: 1.0,
    UnitOfPower.KILO_WATT: 1000.0,
}


def store_key(entry_id: str) -> str:
    """Return the storage key of one entry."""
    return f"{DOMAIN}.{entry_id}"


class AverageTracker:
    """Keep the 15-minute interval state of one source sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.source_entity: str = entry.data[CONF_SOURCE_ENTITY]
        self.import_only: bool = entry.options.get(
            CONF_IMPORT_ONLY, DEFAULT_IMPORT_ONLY
        )
        self.averager = IntervalAverager()
        self.last_interval: FinishedInterval | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, store_key(entry.entry_id)
        )
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    # --- life cycle -----------------------------------------------------

    async def async_start(self) -> None:
        """Load the stored state and start to follow the source."""
        now = dt_util.utcnow()
        data = await self._store.async_load() or {}
        self.averager.restore(data, now)
        if last := data.get("last_interval"):
            self.last_interval = FinishedInterval.from_dict(last)
        self.averager.finalize_until(now)

        if (state := self.hass.states.get(self.source_entity)) is not None:
            self._add_state(state)

        self._unsubs = [
            async_track_state_change_event(
                self.hass, [self.source_entity], self._on_state_change
            ),
            async_track_time_change(
                self.hass, self._on_boundary, minute=[0, 15, 30, 45], second=0
            ),
            async_track_time_interval(self.hass, self._on_tick, TICK),
        ]

    async def async_stop(self) -> None:
        """Stop to follow the source and save the state now."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        await self._store.async_save(self._data())

    # --- listeners ------------------------------------------------------

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Call update on every change. Return a function that removes it."""
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    # --- events ---------------------------------------------------------

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        if (state := event.data["new_state"]) is not None:
            self._add_state(state)
            self._notify()

    @callback
    def _on_boundary(self, now: datetime) -> None:
        self._finish(self.averager.finalize_until(dt_util.as_utc(now)))
        self._notify()

    @callback
    def _on_tick(self, now: datetime) -> None:
        self._notify()

    # --- samples --------------------------------------------------------

    @callback
    def _add_state(self, state: State) -> None:
        value = self.state_watts(state)
        if value is None:
            return
        if self.import_only and value < 0:
            # Export. The meter's import register does not count it.
            value = 0.0
        # A state can be older than the last sample, for example the source's
        # unchanged state at startup. It must not move the interval back.
        ts = max(dt_util.as_utc(state.last_updated), self._floor())
        self._finish(self.averager.add_sample(value, ts))

    @callback
    def _finish(self, finished: FinishedInterval | None) -> None:
        if finished is not None:
            self.last_interval = finished
        self._store.async_delay_save(self._data, SAVE_DELAY)

    def _floor(self) -> datetime:
        times = [
            t
            for t in (self.averager.last_sample_ts, self.averager.interval_start)
            if t is not None
        ]
        return max(times) if times else dt_util.utcnow()

    @staticmethod
    def state_watts(state: State) -> float | None:
        """Return the state in W, or None when it is not a usable number."""
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = state.attributes.get("unit_of_measurement", UnitOfPower.WATT)
        factor = _UNIT_FACTOR.get(unit)
        if factor is None:
            _LOGGER.debug("Unsupported unit %s of %s", unit, state.entity_id)
            return None
        return value * factor

    def _data(self) -> dict[str, Any]:
        data = self.averager.to_dict()
        if self.last_interval is not None:
            data["last_interval"] = self.last_interval.to_dict()
        return data

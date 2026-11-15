"""Follow the source sensor and keep the interval state of one entry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfPower,
)
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
    CONF_AGREED_POWER,
    CONF_BLOCK_ENTITY,
    CONF_DAY_ENTITY,
    CONF_IMPORT_ONLY,
    CONF_SOURCE_ENTITY,
    DEFAULT_IMPORT_ONLY,
    DOMAIN,
    STORAGE_VERSION,
)
from .tariff import BLOCKS, block_at, is_working_day, parse_block

_LOGGER = logging.getLogger(__name__)

# How often the live and projected values move on between source updates.
TICK = timedelta(seconds=10)
# Save the state at most this often (seconds); a restart loses less than this.
SAVE_DELAY = 30
# With a block entity, the block of an interval is the block seen up to this
# long before its end. Blocks change on the full hour, and the entity can
# switch a moment before the interval closes.
BLOCK_SETTLE = timedelta(seconds=60)

_UNIT_FACTOR = {
    UnitOfPower.WATT: 1.0,
    UnitOfPower.KILO_WATT: 1000.0,
}


def store_key(entry_id: str) -> str:
    """Return the storage key of one entry."""
    return f"{DOMAIN}.{entry_id}"


def agreed_power_watts(options: dict[str, Any]) -> dict[int, float]:
    """Return the agreed power per block in W, for the blocks that have one."""
    agreed: dict[int, float] = {}
    for block in BLOCKS:
        value = options.get(CONF_AGREED_POWER.format(block))
        if value:
            agreed[block] = float(value) * 1000
    return agreed


@dataclass(frozen=True)
class Peak:
    """The highest finished interval of a block in the current month."""

    value: float
    start: datetime


class AverageTracker:
    """Keep the 15-minute interval state of one source sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.source_entity: str = entry.data[CONF_SOURCE_ENTITY]
        self.import_only: bool = entry.options.get(
            CONF_IMPORT_ONLY, DEFAULT_IMPORT_ONLY
        )
        self.block_entity: str | None = entry.options.get(CONF_BLOCK_ENTITY)
        self.day_entity: str | None = entry.options.get(CONF_DAY_ENTITY)
        self.agreed_power: dict[int, float] = agreed_power_watts(entry.options)
        self.averager = IntervalAverager()
        self.last_interval: FinishedInterval | None = None
        self.peaks: dict[int, Peak] = {}
        self.peak_month: str | None = None
        self._interval_block: int | None = None
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
        self._load_peaks(data.get("peaks") or {})
        self.averager.finalize_until(now)
        self._roll_month(now)
        self._watch_block(now)

        if (state := self.hass.states.get(self.source_entity)) is not None:
            self._add_state(state)

        watched = [self.source_entity]
        watched += [e for e in (self.block_entity, self.day_entity) if e]
        self._unsubs = [
            async_track_state_change_event(self.hass, watched, self._on_state_change),
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
        state = event.data["new_state"]
        if state is not None and state.entity_id == self.source_entity:
            self._add_state(state)
        self._watch_block(dt_util.utcnow())
        self._notify()

    @callback
    def _on_boundary(self, now: datetime) -> None:
        self._finish(self.averager.finalize_until(dt_util.as_utc(now)))
        self._notify()

    @callback
    def _on_tick(self, now: datetime) -> None:
        now = dt_util.as_utc(now)
        self._roll_month(now)
        self._watch_block(now)
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
            finished = replace(finished, block=self._block_of(finished))
            self.last_interval = finished
            self._record_peak(finished)
            self._interval_block = None
            self._watch_block(dt_util.utcnow())
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

    # --- tariff blocks --------------------------------------------------

    def entity_block(self) -> int | None:
        """Return the block that the block entity shows, if it is usable."""
        if not self.block_entity:
            return None
        state = self.hass.states.get(self.block_entity)
        return parse_block(state.state) if state is not None else None

    def current_block(self, now: datetime | None = None) -> int:
        """Return the tariff block now.

        The block entity wins when it has a usable state. Otherwise the
        integration calculates the block.
        """
        now = now or dt_util.utcnow()
        block = self.entity_block()
        if block is not None:
            return block
        local = dt_util.as_local(now)
        return block_at(local, self.working_day(local))

    def working_day(self, local: datetime) -> bool:
        """Return whether the local day is a working day.

        A holiday calendar (on = holiday today) or a workday binary sensor
        (on = working day) wins when it has a usable state. Otherwise the
        built-in holiday list decides.
        """
        state = self.hass.states.get(self.day_entity) if self.day_entity else None
        if state is None or state.state not in (STATE_ON, STATE_OFF):
            return is_working_day(local.date())
        if state.domain == "calendar":
            return local.weekday() < 5 and state.state == STATE_OFF
        return state.state == STATE_ON

    def block_source(self) -> str:
        """Return where the current block comes from."""
        if self.entity_block() is not None:
            return "entity"
        return "calculated"

    def agreed_power_now(self, now: datetime | None = None) -> float | None:
        """Return the agreed power of the current block in W, if set."""
        return self.agreed_power.get(self.current_block(now))

    @callback
    def _watch_block(self, now: datetime) -> None:
        """Remember the block while the interval runs.

        The entities that give the block or the day can switch a moment
        before the interval closes, so the value near the end is not used.
        """
        end = self.averager.interval_end
        if end is None or now >= end - BLOCK_SETTLE:
            return
        self._interval_block = self.current_block(now)

    def _block_of(self, finished: FinishedInterval) -> int:
        if self._interval_block is not None:
            return self._interval_block
        local = dt_util.as_local(finished.start)
        return block_at(local, self.working_day(local))

    # --- monthly peaks --------------------------------------------------

    @staticmethod
    def _month(ts: datetime) -> str:
        return dt_util.as_local(ts).strftime("%Y-%m")

    @callback
    def _roll_month(self, now: datetime) -> None:
        """Clear the peaks when a new month starts."""
        month = self._month(now)
        if self.peak_month != month:
            if self.peak_month is not None:
                self.peaks = {}
            self.peak_month = month

    @callback
    def _record_peak(self, finished: FinishedInterval) -> None:
        if finished.average is None or finished.block is None:
            return
        month = self._month(finished.start)
        if self.peak_month is not None and month < self.peak_month:
            # The last quarter hour of the old month closes after the month
            # rolled over. It belongs to the old month.
            return
        if month != self.peak_month:
            self.peaks = {}
            self.peak_month = month
        peak = self.peaks.get(finished.block)
        if peak is None or finished.average > peak.value:
            self.peaks[finished.block] = Peak(finished.average, finished.start)

    def _load_peaks(self, data: dict[str, Any]) -> None:
        self.peak_month = data.get("month")
        for key, item in (data.get("blocks") or {}).items():
            start = dt_util.parse_datetime(item.get("start") or "")
            if start is not None and item.get("value") is not None:
                self.peaks[int(key)] = Peak(float(item["value"]), start)

    # --- storage --------------------------------------------------------

    def _data(self) -> dict[str, Any]:
        data = self.averager.to_dict()
        if self.last_interval is not None:
            data["last_interval"] = self.last_interval.to_dict()
        data["peaks"] = {
            "month": self.peak_month,
            "blocks": {
                str(block): {"value": peak.value, "start": peak.start.isoformat()}
                for block, peak in self.peaks.items()
            },
        }
        return data

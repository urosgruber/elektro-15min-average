"""Tests of the sensors, the restart behaviour and the migration."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.elektro_15min_average.const import DOMAIN
from custom_components.elektro_15min_average.diagnostics import (
    async_get_config_entry_diagnostics,
)

SOURCE = "sensor.grid"
AVERAGE = "sensor.grid_15_minute_average"
PROJECTED = "sensor.grid_projected_15_minute_average"
LAST = "sensor.grid_last_15_minute_average"
START = "2026-11-15 10:00:00+00:00"


def set_source(hass: HomeAssistant, value: str, unit: str = "W") -> None:
    hass.states.async_set(
        SOURCE,
        value,
        {"unit_of_measurement": unit, "device_class": "power", "friendly_name": "Grid"},
    )


async def setup_entry(
    hass: HomeAssistant, *, import_only: bool = False, version: int = 2, **extra
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=version,
        title="Grid",
        unique_id=SOURCE,
        data={"source_entity": SOURCE, "name": "Grid", **extra.get("data", {})},
        options=extra.get("options", {"import_only": import_only}),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def move(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def value(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


@pytest.fixture(autouse=True)
def start_time(freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(START)


async def test_live_projected_and_last(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_source(hass, "1000")
    await setup_entry(hass)
    assert value(hass, AVERAGE) == "1000"
    assert value(hass, PROJECTED) == "1000"
    assert value(hass, LAST) == "unknown"  # nothing finished yet on a new install

    await move(hass, freezer, 5)
    set_source(hass, "3000")
    await hass.async_block_till_done()
    assert value(hass, AVERAGE) == "1000"
    assert value(hass, PROJECTED) == str(round((1000 * 5 + 3000 * 10) / 15))

    # The tick moves the live value on without a source update.
    await move(hass, freezer, 5)
    assert value(hass, AVERAGE) == "2000"

    await move(hass, freezer, 5)  # 10:15, the boundary
    assert value(hass, LAST) == str(round((1000 * 5 + 3000 * 10) / 15))
    # The new interval starts with the carried power, not unknown.
    assert value(hass, AVERAGE) == "3000"
    assert value(hass, PROJECTED) == "3000"


async def test_last_interval_survives_a_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_source(hass, "1500")
    entry = await setup_entry(hass)
    await move(hass, freezer, 15)
    assert value(hass, LAST) == "1500"

    await move(hass, freezer, 3)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert value(hass, LAST) == "1500"
    assert value(hass, AVERAGE) == "1500"
    attrs = hass.states.get(AVERAGE).attributes
    assert attrs["restart_detected"] is True


async def test_import_only_counts_export_as_zero(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_source(hass, "-2000")
    await setup_entry(hass, import_only=True)
    await move(hass, freezer, 5)
    set_source(hass, "900")
    await hass.async_block_till_done()
    await move(hass, freezer, 5)
    assert value(hass, AVERAGE) == str(round((0 * 5 + 900 * 5) / 10))


async def test_net_power_without_import_only(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_source(hass, "-2000")
    await setup_entry(hass)
    await move(hass, freezer, 5)
    assert value(hass, AVERAGE) == "-2000"


async def test_kilowatt_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_source(hass, "1.25", unit="kW")
    await setup_entry(hass)
    assert value(hass, AVERAGE) == "1250"


async def test_unavailable_source_is_skipped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_source(hass, "600")
    await setup_entry(hass)
    await move(hass, freezer, 2)
    set_source(hass, "unavailable")
    await hass.async_block_till_done()
    await move(hass, freezer, 2)
    assert value(hass, AVERAGE) == "600"


async def test_migration_from_version_1(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    set_source(hass, "700")
    hass_storage[f"{DOMAIN}.old_final"] = {"version": 1, "data": {}}
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        entry_id="old",
        title=SOURCE,
        unique_id=SOURCE,
        data={"source_entity": SOURCE, "average_method": "arithmetic"},
        options={
            "average_method": "arithmetic",
            "create_final_sensor": True,
            "entity_picture": "/local/x.png",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.title == "Grid"
    assert entry.data == {"source_entity": SOURCE, "name": "Grid"}
    assert entry.options == {"import_only": False}
    assert f"{DOMAIN}.old_final" not in hass_storage
    assert value(hass, AVERAGE) == "700"


async def test_unload_and_remove(hass: HomeAssistant, hass_storage: dict) -> None:
    set_source(hass, "700")
    entry = await setup_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert f"{DOMAIN}.{entry.entry_id}" in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage


async def test_diagnostics(hass: HomeAssistant) -> None:
    set_source(hass, "450")
    entry = await setup_entry(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["source"]["state"] == "450"
    assert diag["current_interval"]["projected"] == 450
    assert diag["entry"]["options"] == {"import_only": False}

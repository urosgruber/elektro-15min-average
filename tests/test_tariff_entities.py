"""Tests of the tariff block, the agreed-power warning and the monthly peaks."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.elektro_15min_average.const import DOMAIN

SOURCE = "sensor.grid"
BLOCK = "sensor.grid_tariff_block"
EXCEEDED = "binary_sensor.grid_agreed_power_exceeded"
PROJECTED = "sensor.grid_projected_15_minute_average"
LAST = "sensor.grid_last_15_minute_average"


def peak(block: int) -> str:
    return f"sensor.grid_monthly_peak_block_{block}"


@pytest.fixture(autouse=True)
async def ljubljana(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await hass.config.async_set_time_zone("Europe/Ljubljana")
    # Monday 16 November 2026, 08:00 local: high season, block 1.
    freezer.move_to("2026-11-16 07:00:00+00:00")


def set_power(hass: HomeAssistant, watts: float) -> None:
    hass.states.async_set(
        SOURCE, str(watts), {"unit_of_measurement": "W", "friendly_name": "Grid"}
    )


async def setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Grid",
        unique_id=SOURCE,
        data={"source_entity": SOURCE, "name": "Grid"},
        options={"import_only": False, **options},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def move(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def state(hass: HomeAssistant, entity_id: str):
    return hass.states.get(entity_id)


async def test_calculated_block(hass: HomeAssistant) -> None:
    set_power(hass, 500)
    await setup(hass)
    s = state(hass, BLOCK)
    assert s.state == "1"
    assert s.attributes["source"] == "calculated"
    assert s.attributes["high_season"] is True
    assert s.attributes["working_day"] is True


async def test_agreed_power_warning(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_power(hass, 2000)
    await setup(hass, agreed_power_1=5.0, agreed_power_2=6.0)
    assert state(hass, EXCEEDED).state == "off"
    assert state(hass, EXCEEDED).attributes["headroom"] == 3000

    await move(hass, freezer, 5)
    set_power(hass, 8000)  # projected (2000*5 + 8000*10)/15 = 6000
    await hass.async_block_till_done()
    assert state(hass, PROJECTED).state == "6000"
    assert state(hass, PROJECTED).attributes["agreed_power"] == 5000
    assert state(hass, EXCEEDED).state == "on"
    assert state(hass, EXCEEDED).attributes["headroom"] == -1000

    set_power(hass, 2000)  # projected (2000*5 + 8000*0 + 2000*10)/15 = 2000
    await hass.async_block_till_done()
    assert state(hass, EXCEEDED).state == "off"

    await move(hass, freezer, 10)  # the interval closes at 08:15 local
    last = state(hass, LAST)
    assert last.attributes["block"] == 1
    assert last.attributes["exceeded"] is False


async def test_no_agreed_power_means_off(hass: HomeAssistant) -> None:
    set_power(hass, 99000)
    await setup(hass)
    s = state(hass, EXCEEDED)
    assert s.state == "off"
    assert s.attributes["agreed_power"] is None


async def test_monthly_peak_per_block(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_power(hass, 3000)
    entry = await setup(hass)
    await move(hass, freezer, 15)  # 08:00–08:15, block 1: 3000
    set_power(hass, 1000)
    await hass.async_block_till_done()
    await move(hass, freezer, 15)  # 08:15–08:30, block 1: 1000
    assert state(hass, peak(1)).state == "3000"
    assert state(hass, peak(1)).attributes["month"] == "2026-11"
    assert state(hass, peak(1)).attributes["peak_start"].startswith("2026-11-16T08:00")
    assert state(hass, peak(2)).state == "unknown"

    # The peak survives a reload.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, peak(1)).state == "3000"


async def test_peaks_reset_in_a_new_month(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-30 22:30:00+00:00")  # 23:30 local, block 3
    set_power(hass, 1200)
    await setup(hass)
    await move(hass, freezer, 15)
    assert state(hass, peak(3)).state == "1200"
    await move(hass, freezer, 15)  # 00:00 local on 1 December
    await move(hass, freezer, 0.5)  # a tick in the new month
    assert state(hass, peak(3)).state == "unknown"
    assert state(hass, peak(3)).attributes["month"] == "2026-12"


async def test_block_entity_overrides(hass: HomeAssistant) -> None:
    hass.states.async_set("select.block", "b4")
    set_power(hass, 500)
    await setup(hass, block_entity="select.block")
    assert state(hass, BLOCK).state == "4"
    assert state(hass, BLOCK).attributes["source"] == "entity"
    # The tables cannot forecast an entity: no forecast at all.
    attrs = state(hass, BLOCK).attributes
    assert attrs["next_change"] is None
    assert attrs["next_block"] is None
    assert attrs["next_cheap_start"] is None
    assert attrs["today_blocks"] is None
    assert attrs["tomorrow_blocks"] is None
    hass.states.async_set("select.block", "b2")
    await hass.async_block_till_done()
    assert state(hass, BLOCK).state == "2"
    # An unusable state falls back to the calculation.
    hass.states.async_set("select.block", "unknown")
    await hass.async_block_till_done()
    assert state(hass, BLOCK).state == "1"


async def test_holiday_calendar(hass: HomeAssistant) -> None:
    hass.states.async_set("calendar.slovenija", "on")
    set_power(hass, 500)
    await setup(hass, day_entity="calendar.slovenija")
    s = state(hass, BLOCK)
    assert s.attributes["working_day"] is False
    assert s.state == "2"  # high season, non-working day, 08:00


async def test_workday_sensor(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.workday", "off")
    set_power(hass, 500)
    await setup(hass, day_entity="binary_sensor.workday")
    assert state(hass, BLOCK).state == "2"
    hass.states.async_set("binary_sensor.workday", "on")
    await hass.async_block_till_done()
    assert state(hass, BLOCK).state == "1"


async def test_options_validate_agreed_power_order(hass: HomeAssistant) -> None:
    set_power(hass, 500)
    entry = await setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"import_only": True, "agreed_power_1": 7.0, "agreed_power_2": 5.0},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "agreed_power_order"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "import_only": True,
            "agreed_power_1": 5.0,
            "agreed_power_3": 7.0,
            "day_entity": "calendar.slovenija",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "import_only": True,
        "agreed_power_1": 5.0,
        "agreed_power_3": 7.0,
        "day_entity": "calendar.slovenija",
    }
    assert entry.runtime_data.agreed_power == {1: 5000.0, 3: 7000.0}


async def test_next_block_attributes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_power(hass, 500)
    await setup(hass)
    attrs = state(hass, BLOCK).attributes
    assert attrs["next_change"] == "2026-11-16T14:00:00+01:00"
    assert attrs["next_block"] == 2
    assert attrs["next_cheap_start"] == "2026-11-16T22:00:00+01:00"
    # At 22:00 the block is 3: no next cheap start, next change at 06:00.
    await move(hass, freezer, 14 * 60)
    s = state(hass, BLOCK)
    assert s.state == "3"
    assert s.attributes["next_change"] == "2026-11-17T06:00:00+01:00"
    assert s.attributes["next_block"] == 2
    assert s.attributes["next_cheap_start"] is None


async def test_day_block_attributes_refresh_at_midnight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_power(hass, 500)
    await setup(hass)
    attrs = state(hass, BLOCK).attributes
    assert len(attrs["today_blocks"]) == 96
    assert attrs["today_blocks"][32] == 1  # Monday 08:00
    assert attrs["tomorrow_blocks"][32] == 1  # Tuesday
    # Friday 20 November 23:30 local: today is a working day, tomorrow is not.
    await move(hass, freezer, 4 * 24 * 60 + 15.5 * 60)
    attrs = state(hass, BLOCK).attributes
    assert attrs["today_blocks"][32] == 1
    assert attrs["tomorrow_blocks"][32] == 2
    # After midnight, Saturday is today.
    await move(hass, freezer, 60)
    attrs = state(hass, BLOCK).attributes
    assert attrs["today_blocks"][32] == 2
    assert attrs["today_blocks"][0] == 4

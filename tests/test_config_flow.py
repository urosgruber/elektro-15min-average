"""Tests of the config flow and the options flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.elektro_15min_average.const import DOMAIN


def add_source(hass: HomeAssistant, entity_id: str, unit: str = "W") -> None:
    hass.states.async_set(
        entity_id,
        "100",
        {"unit_of_measurement": unit, "device_class": "power", "friendly_name": "Grid"},
    )


async def start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_create_entry_with_defaults(hass: HomeAssistant) -> None:
    add_source(hass, "sensor.grid")
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"source_entity": "sensor.grid"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Grid"
    assert result["data"] == {"source_entity": "sensor.grid", "name": "Grid"}
    assert result["options"] == {"import_only": False}


async def test_create_entry_with_name_and_import_only(hass: HomeAssistant) -> None:
    add_source(hass, "sensor.grid")
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"source_entity": "sensor.grid", "name": " Omrežje ", "import_only": True},
    )
    assert result["title"] == "Omrežje"
    assert result["options"] == {"import_only": True}


async def test_unsupported_unit(hass: HomeAssistant) -> None:
    add_source(hass, "sensor.grid", unit="VA")
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"source_entity": "sensor.grid"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"source_entity": "unsupported_unit"}


async def test_same_source_twice_aborts(hass: HomeAssistant) -> None:
    add_source(hass, "sensor.grid")
    for _ in range(2):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"source_entity": "sensor.grid"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_changes_import_only(hass: HomeAssistant) -> None:
    add_source(hass, "sensor.grid")
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"source_entity": "sensor.grid"}
    )
    await hass.async_block_till_done()
    entry = result["result"]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"import_only": True}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"import_only": True}
    assert entry.runtime_data.import_only is True

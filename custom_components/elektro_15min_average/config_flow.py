"""Config flow of the Elektro 15-minute average integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from . import source_name
from .const import (
    CONF_AGREED_POWER,
    CONF_BLOCK_ENTITY,
    CONF_DAY_ENTITY,
    CONF_IMPORT_ONLY,
    CONF_NAME,
    CONF_SOURCE_ENTITY,
    DEFAULT_IMPORT_ONLY,
    DOMAIN,
)

SUPPORTED_UNITS = {UnitOfPower.WATT, UnitOfPower.KILO_WATT}

_IMPORT_ONLY = selector.BooleanSelector()
_BLOCKS = (1, 2, 3, 4, 5)
_AGREED_POWER = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=1000,
        step=0.1,
        unit_of_measurement=UnitOfPower.KILO_WATT,
        mode=selector.NumberSelectorMode.BOX,
    )
)


def agreed_power_error(values: dict[str, Any]) -> str | None:
    """Check that a higher block has no lower agreed power than a lower one.

    Block 1 is the most expensive. The agreed power may not go down from
    block 1 to block 5. Blocks without a value are skipped.
    """
    last = 0.0
    for block in _BLOCKS:
        value = values.get(CONF_AGREED_POWER.format(block))
        if not value:
            continue
        if value < last:
            return "agreed_power_order"
        last = value
    return None


class ElektroAverageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a 15-minute average for one power sensor."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            source = user_input[CONF_SOURCE_ENTITY]
            await self.async_set_unique_id(source)
            self._abort_if_unique_id_configured()
            state = self.hass.states.get(source)
            unit = state.attributes.get("unit_of_measurement") if state else None
            if unit is not None and unit not in SUPPORTED_UNITS:
                errors[CONF_SOURCE_ENTITY] = "unsupported_unit"
            else:
                name = (user_input.get(CONF_NAME) or "").strip() or source_name(
                    self.hass, source
                )
                return self.async_create_entry(
                    title=name,
                    data={CONF_SOURCE_ENTITY: source, CONF_NAME: name},
                    options={
                        CONF_IMPORT_ONLY: user_input.get(
                            CONF_IMPORT_ONLY, DEFAULT_IMPORT_ONLY
                        )
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class=SensorDeviceClass.POWER
                    )
                ),
                vol.Optional(CONF_NAME): selector.TextSelector(),
                vol.Optional(
                    CONF_IMPORT_ONLY, default=DEFAULT_IMPORT_ONLY
                ): _IMPORT_ONLY,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> ElektroAverageOptionsFlow:
        return ElektroAverageOptionsFlow()


class ElektroAverageOptionsFlow(OptionsFlowWithReload):
    """Change the import-only setting and the tariff settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # An empty number field means: no agreed power for that block.
            data = {k: v for k, v in user_input.items() if v not in (None, "", 0)}
            data[CONF_IMPORT_ONLY] = user_input.get(
                CONF_IMPORT_ONLY, DEFAULT_IMPORT_ONLY
            )
            if (error := agreed_power_error(data)) is None:
                return self.async_create_entry(data=data)
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Optional(CONF_IMPORT_ONLY, default=DEFAULT_IMPORT_ONLY): (
                    _IMPORT_ONLY
                ),
                **{
                    vol.Optional(CONF_AGREED_POWER.format(block)): _AGREED_POWER
                    for block in _BLOCKS
                },
                vol.Optional(CONF_DAY_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["calendar", "binary_sensor"])
                ),
                vol.Optional(CONF_BLOCK_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "select", "input_select", "input_number"]
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self.config_entry.options
            ),
            errors=errors,
        )

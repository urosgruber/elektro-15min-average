"""Config flow for Elektro 15-minute power average."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_METHOD,
    CONF_NAME,
    CONF_PRECISION,
    CONF_SOURCE_ENTITY,
    DEFAULT_METHOD,
    DEFAULT_PRECISION,
    DOMAIN,
    METHOD_ARITHMETIC,
    METHOD_TIME_WEIGHTED,
)


def _method_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": METHOD_ARITHMETIC, "label": "Arithmetic (average of samples)"},
                {
                    "value": METHOD_TIME_WEIGHTED,
                    "label": "Time-weighted (average over time)",
                },
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _precision_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=3, step=1, mode=selector.NumberSelectorMode.SLIDER)
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        if user_input is not None:
            source_entity = user_input[CONF_SOURCE_ENTITY]
            await self.async_set_unique_id(source_entity)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=source_entity, data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_METHOD, default=DEFAULT_METHOD): _method_selector(),
                vol.Optional(CONF_PRECISION, default=DEFAULT_PRECISION): _precision_selector(),
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow."""
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options for the integration."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._entry.options

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_METHOD, default=options.get(CONF_METHOD, DEFAULT_METHOD)
                ): _method_selector(),
                vol.Optional(
                    CONF_PRECISION, default=options.get(CONF_PRECISION, DEFAULT_PRECISION)
                ): _precision_selector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)

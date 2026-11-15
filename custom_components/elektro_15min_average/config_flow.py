"""Config flow for Elektro 15-minute power average."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_FINAL_SENSOR,
    CONF_ENTITY_PICTURE,
    CONF_IMPORT_ONLY,
    CONF_METHOD,
    CONF_NAME,
    CONF_SOURCE_ENTITY,
    DEFAULT_FINAL_SENSOR,
    DEFAULT_ENTITY_PICTURE,
    DEFAULT_IMPORT_ONLY,
    DEFAULT_METHOD,
    DOMAIN,
    METHOD_ARITHMETIC,
    METHOD_TIME_WEIGHTED,
)


def _method_selector() -> selector.SelectSelector:
    # Keep labels user-facing while stored values stay stable for compatibility.
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {
                    "value": METHOD_TIME_WEIGHTED,
                    "label": "Time-weighted (energy / time, like the meter)",
                },
                {"value": METHOD_ARITHMETIC, "label": "Arithmetic (average of samples)"},
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        if user_input is not None:
            source_entity = user_input[CONF_SOURCE_ENTITY]
            # Use the source entity as a stable unique_id to avoid duplicates.
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
                # Count negative values (export) as 0 W, like the meter's import register.
                vol.Optional(
                    CONF_IMPORT_ONLY, default=DEFAULT_IMPORT_ONLY
                ): selector.BooleanSelector(),
                # Optional finalized-only sensor for discrete interval history.
                vol.Optional(
                    CONF_FINAL_SENSOR, default=DEFAULT_FINAL_SENSOR
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_ENTITY_PICTURE, default=DEFAULT_ENTITY_PICTURE
                ): str,
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
                    CONF_IMPORT_ONLY,
                    default=options.get(
                        CONF_IMPORT_ONLY,
                        self._entry.data.get(CONF_IMPORT_ONLY, DEFAULT_IMPORT_ONLY),
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_FINAL_SENSOR,
                    default=options.get(CONF_FINAL_SENSOR, DEFAULT_FINAL_SENSOR),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_ENTITY_PICTURE,
                    default=options.get(
                        CONF_ENTITY_PICTURE,
                        self._entry.data.get(
                            CONF_ENTITY_PICTURE, DEFAULT_ENTITY_PICTURE
                        ),
                    ),
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)

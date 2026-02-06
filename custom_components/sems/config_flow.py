"""Config flow for sems integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_STATION_ID, DEFAULT_SCAN_INTERVAL, DOMAIN, SEMS_CONFIG_SCHEMA
from .sems_api import SemsApi

_LOGGER = logging.getLogger(__name__)


def mask_password(user_input: dict[str, Any]) -> dict[str, Any]:
    """Mask password in user input for logging."""
    masked_input = user_input.copy()
    if CONF_PASSWORD in masked_input:
        masked_input[CONF_PASSWORD] = "<masked>"
    return masked_input


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    _LOGGER.debug(
        "SEMS - Start validation config flow user input, with input data: %s",
        mask_password(data),
    )
    api = SemsApi(hass, data[CONF_USERNAME], data[CONF_PASSWORD])

    authenticated = await hass.async_add_executor_job(api.test_authentication)
    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth
    if not authenticated:
        raise InvalidAuth

    # If optional station ID is not provided, query the SEMS API for the first found
    if CONF_STATION_ID not in data:
        _LOGGER.debug(
            "SEMS - No station ID provided, query SEMS API, using first found"
        )
        powerStationId = await hass.async_add_executor_job(api.getPowerStationIds)
        _LOGGER.debug("SEMS - Found power station IDs: %s", powerStationId)

        data[CONF_STATION_ID] = powerStationId

    # Return info that you want to store in the config entry.
    _LOGGER.debug("SEMS - validate_input Returning data: %s", mask_password(data))
    return data


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for sems."""

    _LOGGER.debug("SEMS - new config flow")

    VERSION = 1
    # CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=SEMS_CONFIG_SCHEMA)

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            _LOGGER.debug(
                "Creating config entry for %s with data: %s",
                info[CONF_STATION_ID],
                mask_password(info),
            )
            return self.async_create_entry(
                title=f"Inverter {info[CONF_STATION_ID]}", data=info
            )

        return self.async_show_form(
            step_id="user", data_schema=SEMS_CONFIG_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth confirmation."""
        errors = {}

        reauth_entry = self._get_reauth_entry()

        if user_input is None:
            # Pre-fill username from existing config
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_USERNAME, default=reauth_entry.data.get(CONF_USERNAME)
                        ): str,
                        vol.Required(CONF_PASSWORD): str,
                    }
                ),
                description_placeholders={
                    "username": reauth_entry.data.get(CONF_USERNAME, ""),
                },
            )

        try:
            # Validate the new credentials
            await validate_input(
                self.hass,
                {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_STATION_ID: reauth_entry.data.get(CONF_STATION_ID),
                },
            )
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception during reauth")
            errors["base"] = "unknown"
        else:
            # Update the entry with new credentials
            return self.async_update_reload_and_abort(
                reauth_entry,
                data={
                    **reauth_entry.data,
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                },
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=user_input.get(CONF_USERNAME)
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "username": user_input.get(CONF_USERNAME, ""),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for SEMS integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update the scan interval in config entry data
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                },
            )
            # Reload the integration for changes to take effect
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.data.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): int,
                }
            ),
        )

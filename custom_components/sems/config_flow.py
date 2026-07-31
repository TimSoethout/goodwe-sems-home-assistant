"""Config flow for sems integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_STATION_ID, DOMAIN, redact_for_log
from .sems_api import SemsApi

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, description={"suggested_value": 60}): int,
    }
)


def _normalize_station_ids(raw: Any) -> list[str]:
    """Normalize a getPowerStationIds result to a list of station ID strings."""
    if isinstance(raw, str) and raw:
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    return []


async def validate_credentials(hass: HomeAssistant, data: dict[str, Any]) -> SemsApi:
    """Validate credentials and return an authenticated API client."""
    _LOGGER.debug(
        "SEMS - Validating credentials for user: %s",
        redact_for_log(data.get(CONF_USERNAME, "")),
    )
    api = SemsApi(hass, data[CONF_USERNAME], data[CONF_PASSWORD])
    authenticated = await hass.async_add_executor_job(api.test_authentication)
    if not authenticated:
        raise InvalidAuth
    return api


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for sems."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._credentials: dict[str, Any] = {}
        self._station_ids: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the credentials step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors: dict[str, str] = {}

        try:
            api = await validate_credentials(self.hass, user_input)

            _LOGGER.debug("SEMS - Credentials valid, fetching station IDs")
            raw_ids = await self.hass.async_add_executor_job(api.getPowerStationIds)
            _LOGGER.debug("SEMS - Found power station IDs: %s", raw_ids)

            station_ids = _normalize_station_ids(raw_ids)

            if not station_ids:
                errors["base"] = "no_stations_found"
            else:
                self._credentials = dict(user_input)
                self._station_ids = station_ids

                if len(station_ids) == 1:
                    station_id = station_ids[0]
                    _LOGGER.debug(
                        "SEMS - Single station found, creating entry for %s",
                        redact_for_log(station_id),
                    )
                    return self.async_create_entry(
                        title=f"Inverter {station_id}",
                        data={**user_input, CONF_STATION_ID: station_id},
                    )

                return await self.async_step_select_station()

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_select_station(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the station selection step (shown when multiple stations are found)."""
        if user_input is None:
            options = [
                {"value": station_id, "label": station_id}
                for station_id in self._station_ids
            ]
            schema = vol.Schema(
                {
                    vol.Required(CONF_STATION_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            )
            return self.async_show_form(
                step_id="select_station",
                data_schema=schema,
            )

        station_id = user_input[CONF_STATION_ID]
        _LOGGER.debug(
            "SEMS - Creating entry for selected station %s",
            redact_for_log(station_id),
        )
        return self.async_create_entry(
            title=f"Inverter {station_id}",
            data={**self._credentials, CONF_STATION_ID: station_id},
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

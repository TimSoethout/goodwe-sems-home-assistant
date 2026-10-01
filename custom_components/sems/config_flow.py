"""Config flow for sems integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_STATION_ID, DOMAIN, account_key, redact_for_log
from .sems_api import SemsApi, SemsRateLimitedError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, description={"suggested_value": 60}): int,
    }
)
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


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

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=cast(Any, STEP_USER_DATA_SCHEMA),
            )

        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        try:
            api = await validate_credentials(self.hass, user_input)

            _LOGGER.debug("SEMS - Credentials valid, fetching station IDs")
            raw_ids = await self.hass.async_add_executor_job(api.getPowerStationIds)
            _LOGGER.debug("SEMS - Found power station IDs: %s", redact_for_log(raw_ids))

            station_ids = _normalize_station_ids(raw_ids)

            if not station_ids:
                errors["base"] = "no_stations_found"
            else:
                # Schedule flows for any additional stations so all are auto-added.
                # Users can disable individual entities or devices via the HA UI after setup.
                for station_id in station_ids[1:]:
                    self.hass.async_create_task(
                        self.hass.config_entries.flow.async_init(
                            DOMAIN,
                            context={"source": config_entries.SOURCE_IMPORT},
                            data={**user_input, CONF_STATION_ID: station_id},
                        )
                    )
                station_id = station_ids[0]
                await self.async_set_unique_id(station_id)
                self._abort_if_unique_id_configured()
                _LOGGER.debug(
                    "SEMS - Creating entry for station %s",
                    redact_for_log(station_id),
                )
                return self.async_create_entry(
                    title=f"Inverter {station_id}",
                    data={**user_input, CONF_STATION_ID: station_id},
                )

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except SemsRateLimitedError as err:
            errors["base"] = "rate_limited"
            placeholders["retry_after"] = str(err.retry_after)
        except AbortFlow:
            raise
        except HomeAssistantError:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=cast(Any, STEP_USER_DATA_SCHEMA),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle rejected credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for the new password of the account."""
        reauth_entry = self._get_reauth_entry()
        username = reauth_entry.data[CONF_USERNAME]
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"username": username}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                await validate_credentials(
                    self.hass, {CONF_USERNAME: username, CONF_PASSWORD: password}
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except SemsRateLimitedError as err:
                errors["base"] = "rate_limited"
                placeholders["retry_after"] = str(err.retry_after)
            except HomeAssistantError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # All stations of the account share one client, so update them
                # together.
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.entry_id == reauth_entry.entry_id or account_key(
                        entry.data.get(CONF_USERNAME, "")
                    ) != account_key(username):
                        continue
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_PASSWORD: password}
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates={CONF_PASSWORD: password}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=cast(Any, STEP_REAUTH_DATA_SCHEMA),
            description_placeholders=placeholders,
            errors=errors,
        )

    async def async_step_import(
        self, import_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Auto-create an entry for an additional discovered station."""
        station_id = str(import_data.get(CONF_STATION_ID, ""))
        await self.async_set_unique_id(station_id)
        self._abort_if_unique_id_configured()
        _LOGGER.debug(
            "SEMS - Auto-adding station %s from multi-station discovery",
            redact_for_log(station_id),
        )
        return self.async_create_entry(
            title=f"Inverter {station_id}",
            data=import_data,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

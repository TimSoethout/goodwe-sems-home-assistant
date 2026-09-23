"""The sems integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    GOODWE_SPELLING,
    PLATFORMS,
    redact_for_log,
)
from .sems_api import SemsApi, SemsRateLimitedError

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_IMMEDIATE_CHARGING_FUNCTION_KEYS = {
    "immediate_charge",
    "stop_charging",
    "end_charge_soc",
    "bat_immediate_charge_power",
}


@dataclass(slots=True)
class SemsRuntimeData:
    """Runtime data stored on the config entry."""

    api: SemsApi
    coordinator: SemsDataUpdateCoordinator


type SemsConfigEntry = ConfigEntry[SemsRuntimeData]


@dataclass(slots=True)
class SemsData:
    """Runtime SEMS data returned by the coordinator."""

    inverters: dict[str, dict[str, Any]]
    batteries: dict[str, dict[str, dict[str, Any]]] | None = None
    immediate_charging: dict[str, dict[str, Any]] | None = None
    homekit: dict[str, Any] | None = None
    currency: str | None = None


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the sems component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SemsConfigEntry) -> bool:
    """Set up sems from a config entry."""
    sems_api = SemsApi(hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = SemsDataUpdateCoordinator(hass, sems_api, entry)
    entry.runtime_data = SemsRuntimeData(api=sems_api, coordinator=coordinator)

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 2:
        _LOGGER.error("Cannot migrate entry version %s", entry.version)
        return False

    if entry.version < 2:
        station_id = entry.data.get(CONF_STATION_ID)
        if entry.unique_id is None and isinstance(station_id, str) and station_id:
            hass.config_entries.async_update_entry(
                entry, version=2, unique_id=station_id
            )
        else:
            hass.config_entries.async_update_entry(entry, version=2)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SemsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class SemsDataUpdateCoordinator(DataUpdateCoordinator[SemsData]):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, sems_api: SemsApi, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        self.sems_api = sems_api
        self.station_id = entry.data[CONF_STATION_ID]

        update_interval = timedelta(
            seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_get_energy_storage_cabinets(
        self, data_result: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch the energy storage cabinets when batteries are available."""
        if not data_result.get("info", {}).get("is_stored", False):
            return {}

        _LOGGER.debug("Getting energy storage integrated cabinets")
        return {
            inverter.get("invert_full", {}).get(
                "sn"
            ): await self.hass.async_add_executor_job(
                self.sems_api.getEnergyStorageIntegratedCabinets,
                self.station_id,
                inverter.get("invert_full", {}).get("sn"),
            )
            for inverter in data_result.get("inverter", {})
        }

    async def _async_get_battery_functions(
        self, energy_storage_cabinets: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, dict[str, Any]]] | None:
        """Fetch and retain supported battery functions."""
        if energy_storage_cabinets:
            _LOGGER.debug("Getting battery general functions for each cabinet")
        battery_general_functions = {
            sn: {
                bat.get("translateCode"): await self.hass.async_add_executor_job(
                    self.sems_api.getBatteryGeneralFunctions, sn, bat.get("no", 0)
                )
                for bat in bats
                if isinstance(bat, dict) and bat.get("translateCode") is not None
            }
            for sn, bats in energy_storage_cabinets.items()
        }

        batteries: dict[str, dict[str, dict[str, Any]]] = {}
        for sn, bats in battery_general_functions.items():
            for bat_id, bat in bats.items():
                if not isinstance(bat_id, str):
                    continue
                for child in bat.get("functionMenus", {}).get("children", []):
                    for func in child.get("functions", []):
                        function_key = func.get("translateKey")
                        if not isinstance(function_key, str):
                            continue
                        if function_key not in _IMMEDIATE_CHARGING_FUNCTION_KEYS:
                            continue

                        if sn not in batteries:
                            batteries[sn] = {}
                        if bat_id not in batteries[sn]:
                            batteries[sn][bat_id] = {
                                "name": next(
                                    (
                                        cabinet.get("name", "")
                                        for cabinet in energy_storage_cabinets.get(
                                            sn, []
                                        )
                                        if cabinet.get("translateCode") == bat_id
                                    ),
                                    "",
                                ),
                                "functions": {},
                            }

                        batteries[sn][bat_id]["functions"][function_key] = {
                            "address": func.get("address"),
                            "id": func.get("id"),
                        }

        return batteries or None

    async def _async_get_immediate_charging(
        self, batteries: dict[str, dict[str, dict[str, Any]]] | None
    ) -> dict[str, dict[str, Any]] | None:
        """Fetch immediate-charging state for battery-equipped inverters."""
        if not batteries:
            return None

        immediate_charging: dict[str, dict[str, Any]] = {}
        for inverter_sn in batteries:
            immediate_charging_result = await self.hass.async_add_executor_job(
                self.sems_api.getBatteryImmediateChargingStates, inverter_sn
            )
            state_data = (immediate_charging_result or {}).get("data", {})
            immediate_charging[inverter_sn] = {
                "enabled": bool(state_data.get("47545", 0)),
                "end_charge_soc": state_data.get("47546", 0),
                "charging_power": state_data.get("47603", 0),
            }

        return immediate_charging

    async def _async_update_data(self) -> SemsData:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        # async with async_timeout.timeout(10):
        try:
            data_result = await self.hass.async_add_executor_job(
                self.sems_api.getData, self.station_id
            )

            energy_storage_cabinets = await self._async_get_energy_storage_cabinets(
                data_result
            )
            batteries = await self._async_get_battery_functions(energy_storage_cabinets)
            immediate_charging = await self._async_get_immediate_charging(batteries)

        except SemsRateLimitedError as err:
            raise UpdateFailed(
                f"SEMS API rate limited (retry after {err.retry_after}s)"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        else:
            _LOGGER.debug("semsApi.getData result: %s", redact_for_log(data_result))

            inverters = data_result.get("inverter")
            inverters_by_sn: dict[str, dict[str, Any]] = {}
            if not inverters or not isinstance(inverters, list):
                raise UpdateFailed(
                    "Error communicating with API: invalid or missing inverter data. See debug logs."
                )

            # Get Inverter Data
            for inverter in inverters:
                inverter_full = inverter.get("invert_full")
                if not isinstance(inverter_full, dict):
                    continue

                name = inverter_full.get("name")
                sn = inverter_full.get("sn")
                if not isinstance(sn, str):
                    continue

                _LOGGER.debug(
                    "Found inverter attribute %s %s",
                    name,
                    redact_for_log(sn),
                )
                inverters_by_sn[sn] = inverter_full

            # Add currency
            kpi = data_result.get("kpi")
            if not isinstance(kpi, dict):
                kpi = {}
            currency = kpi.get("currency")

            has_powerflow = bool(data_result.get("hasPowerflow"))
            has_energy_statistics_charts = bool(
                data_result.get(GOODWE_SPELLING.hasEnergyStatisticsCharts)
            )

            homekit: dict[str, Any] | None = None

            if has_powerflow:
                _LOGGER.debug("Found powerflow data")
                powerflow = data_result.get("powerflow")
                if not isinstance(powerflow, dict):
                    powerflow = {}

                if has_energy_statistics_charts:
                    charts = data_result.get(GOODWE_SPELLING.energyStatisticsCharts)
                    if not isinstance(charts, dict):
                        charts = {}
                    totals = data_result.get(GOODWE_SPELLING.energyStatisticsTotals)
                    if not isinstance(totals, dict):
                        totals = {}

                    powerflow = {
                        **powerflow,
                        **{f"Charts_{key}": val for key, val in charts.items()},
                        **{f"Totals_{key}": val for key, val in totals.items()},
                    }

                # Add the flag so sensors can check if energy statistics are available
                powerflow[GOODWE_SPELLING.hasEnergyStatisticsCharts] = (
                    has_energy_statistics_charts
                )

                homekit_data = data_result.get(GOODWE_SPELLING.homeKit)
                if not isinstance(homekit_data, dict):
                    homekit_data = {}
                powerflow["sn"] = homekit_data.get("sn")

                # Goodwe 'Power Meter' (not HomeKit) doesn't have a sn
                # Let's put something in, otherwise we can't see the data.
                if powerflow["sn"] is None:
                    powerflow["sn"] = "GW-HOMEKIT-NO-SERIAL"

                # _LOGGER.debug("homeKit sn: %s", result["homKit"]["sn"])
                # This seems more accurate than the Chart_sum
                powerflow["all_time_generation"] = kpi.get("total_power")

                homekit = powerflow

            data = SemsData(
                inverters=inverters_by_sn,
                batteries=batteries,
                homekit=homekit,
                currency=currency,
                immediate_charging=immediate_charging,
            )
            _LOGGER.debug(
                "Resulting data: %s",
                redact_for_log(data),
            )
            return data


# Type alias to make type inference working for pylance
type SemsCoordinator = SemsDataUpdateCoordinator

"""The sems integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    GOODWE_SPELLING,
    PLATFORMS,
)
from .sems_api import SemsApi

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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

    async def _async_update_data(self) -> SemsData:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        # async with async_timeout.timeout(10):
        try:
            result = await self.hass.async_add_executor_job(
                self.sems_api.getData, self.station_id
            )
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        else:
            _LOGGER.debug("semsApi.getData result: %s", result)

            inverters = result.get("inverter")
            inverters_by_sn: dict[str, dict[str, Any]] = {}
            if not inverters or not isinstance(inverters, list):
                raise UpdateFailed(
                    "Error communicating with API: invalid or missing inverter data. See debug logs"
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

                _LOGGER.debug("Found inverter attribute %s %s", name, sn)
                inverters_by_sn[sn] = inverter_full

            # Add currency
            kpi = result.get("kpi")
            if not isinstance(kpi, dict):
                kpi = {}
            currency = kpi.get("currency")

            has_powerflow = bool(result.get("hasPowerflow"))
            has_energy_statistics_charts = bool(
                result.get(GOODWE_SPELLING.hasEnergyStatisticsCharts)
            )

            homekit: dict[str, Any] | None = None

            if has_powerflow:
                _LOGGER.debug("Found powerflow data")
                powerflow = result.get("powerflow")
                if not isinstance(powerflow, dict):
                    powerflow = {}

                if has_energy_statistics_charts:
                    charts = result.get(GOODWE_SPELLING.energyStatisticsCharts)
                    if not isinstance(charts, dict):
                        charts = {}
                    totals = result.get(GOODWE_SPELLING.energyStatisticsTotals)
                    if not isinstance(totals, dict):
                        totals = {}

                    powerflow = {
                        **powerflow,
                        **{f"Charts_{key}": val for key, val in charts.items()},
                        **{f"Totals_{key}": val for key, val in totals.items()},
                    }

                homekit_data = result.get(GOODWE_SPELLING.homeKit)
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
                inverters=inverters_by_sn, homekit=homekit, currency=currency
            )
            _LOGGER.debug("Resulting data: %s", data)
            return data


# Type alias to make type inference working for pylance
type SemsCoordinator = SemsDataUpdateCoordinator

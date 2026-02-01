"""The sems integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_NIGHT_INTERVAL,
    CONF_NIGHT_MODE,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    DEFAULT_NIGHT_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .sems_api import SemsApi

_LOGGER: logging.Logger = logging.getLogger(__package__)


@dataclass(slots=True)
class SemsData:
    """Runtime SEMS data returned by the coordinator."""

    inverters: dict[str, dict[str, Any]]
    homekit: dict[str, Any] | None = None
    currency: str | None = None


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the sems component."""
    # Ensure our name space for storing objects is a known type. A dict is
    # common/preferred as it allows a separate instance of your class for each
    # instance that has been created in the UI.
    hass.data.setdefault(DOMAIN, {})

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up sems from a config entry."""
    semsApi = SemsApi(hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = SemsDataUpdateCoordinator(hass, semsApi, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class SemsDataUpdateCoordinator(DataUpdateCoordinator[SemsData]):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, semsApi: SemsApi, entry) -> None:
        """Initialize."""
        self.semsApi = semsApi
        self.platforms = []
        self.stationId = entry.data[CONF_STATION_ID]
        self.hass = hass

        # Night mode configuration
        self._night_mode_enabled = entry.data.get(CONF_NIGHT_MODE, True)
        self._night_interval = entry.data.get(CONF_NIGHT_INTERVAL, DEFAULT_NIGHT_INTERVAL)
        self._base_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self._is_night = False
        self._last_detailed_fetch: float = 0

        update_interval = timedelta(seconds=self._base_interval)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

    def _is_night_time(self, inverters: dict[str, dict[str, Any]]) -> bool:
        """Check if inverter is in night mode (offline/not producing)."""
        if not inverters:
            return False

        for inv_data in inverters.values():
            status = inv_data.get("status")
            # Status -1=Offline, 0=Waiting, 1=Normal, 2=Fault
            if status in (-1, 0, "-1", "0"):
                return True
            # Also check if power output is zero
            pac = inv_data.get("pac", 0)
            try:
                if float(pac) <= 0:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    def _update_night_status(self, is_night: bool) -> None:
        """Update night mode status and log transitions."""
        if not self._night_mode_enabled:
            return

        if is_night and not self._is_night:
            _LOGGER.info(
                "SEMS: Entering night mode - skipping detailed inverter data fetch"
            )
            self._is_night = True
        elif not is_night and self._is_night:
            _LOGGER.info("SEMS: Exiting night mode - resuming full data fetch")
            self._is_night = False

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
                self.semsApi.getData, self.stationId
            )
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        else:
            _LOGGER.debug("semsApi.getData result: %s", result)

            # _LOGGER.warning("SEMS - Try get getPowerStationIds")
            # powerStationIds = await self.hass.async_add_executor_job(
            #     self.semsApi.getPowerStationIds
            # )
            # _LOGGER.warning(
            #     "SEMS - getPowerStationIds: Found power station IDs: %s",
            #     powerStationIds,
            # )

            inverters = result["inverter"]

            # found = []
            # _LOGGER.debug("Found inverters: %s", inverters)
            inverters_by_sn: dict[str, dict[str, Any]] = {}
            if inverters is None:
                # something went wrong, probably token could not be fetched
                raise UpdateFailed(
                    "Error communicating with API, probably token could not be fetched, see debug logs"
                )

            # Get Inverter Data
            for inverter in inverters:
                name = inverter["invert_full"]["name"]
                # powerstation_id = inverter["invert_full"]["powerstation_id"]
                sn = inverter["invert_full"]["sn"]
                _LOGGER.debug("Found inverter attribute %s %s", name, sn)
                inverters_by_sn[sn] = inverter["invert_full"]

            # Check night mode status
            is_night = self._is_night_time(inverters_by_sn)
            self._update_night_status(is_night)

            # Fetch detailed inverter data (AC voltage, current, temp, PV strings, etc.)
            # Skip during night mode to reduce API calls
            import time
            should_fetch_detailed = (
                not is_night
                or not self._night_mode_enabled
                or (time.time() - self._last_detailed_fetch) > self._night_interval
            )

            if should_fetch_detailed:
                try:
                    detailed_data = await self.hass.async_add_executor_job(
                        self.semsApi.getInverterAllPoint, self.stationId
                    )
                    if detailed_data:
                        inverter_points = detailed_data.get("inverterPoints", [])
                        for inv_point in inverter_points:
                            inv_sn = inv_point.get("sn")
                            if inv_sn and inv_sn in inverters_by_sn:
                                # Extract detailed readings from dict.left and dict.right
                                inv_dict = inv_point.get("dict", {})
                                for section in ["left", "right"]:
                                    for item in inv_dict.get(section, []):
                                        key = item.get("key", "")
                                        value = item.get("value")
                                        unit = item.get("unit", "")
                                        if key and value is not None:
                                            # Store with descriptive key including unit
                                            inverters_by_sn[inv_sn][key] = (
                                                f"{value} {unit}".strip()
                                            )
                                _LOGGER.debug(
                                    "Added detailed data for inverter %s", inv_sn
                                )
                        self._last_detailed_fetch = time.time()
                except Exception as err:
                    _LOGGER.debug("Could not fetch detailed inverter data: %s", err)
            else:
                _LOGGER.debug("SEMS: Night mode - skipping detailed inverter fetch")

            # Add currency
            kpi = result["kpi"]
            currency = kpi.get("currency")

            hasPowerflow = result["hasPowerflow"]
            hasEnergeStatisticsCharts = result["hasEnergeStatisticsCharts"]

            homekit: dict[str, Any] | None = None

            if hasPowerflow:
                _LOGGER.debug("Found powerflow data")
                if hasEnergeStatisticsCharts:
                    StatisticsCharts = {
                        f"Charts_{key}": val
                        for key, val in result["energeStatisticsCharts"].items()
                    }
                    StatisticsTotals = {
                        f"Totals_{key}": val
                        for key, val in result["energeStatisticsTotals"].items()
                    }
                    powerflow = {
                        **result["powerflow"],
                        **StatisticsCharts,
                        **StatisticsTotals,
                    }
                else:
                    powerflow = result["powerflow"]

                powerflow["sn"] = result["homKit"]["sn"]

                # Goodwe 'Power Meter' (not HomeKit) doesn't have a sn
                # Let's put something in, otherwise we can't see the data.
                if powerflow["sn"] is None:
                    powerflow["sn"] = "GW-HOMEKIT-NO-SERIAL"

                # _LOGGER.debug("homeKit sn: %s", result["homKit"]["sn"])
                # This seems more accurate than the Chart_sum
                powerflow["all_time_generation"] = result["kpi"]["total_power"]

                homekit = powerflow

            data = SemsData(
                inverters=inverters_by_sn, homekit=homekit, currency=currency
            )
            _LOGGER.debug("Resulting data: %s", data)
            return data


# Type alias to make type inference working for pylance
type SemsCoordinator = SemsDataUpdateCoordinator

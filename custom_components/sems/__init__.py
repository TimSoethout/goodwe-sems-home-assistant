"""The sems integration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ALWAYS_POLL_POWERFLOW,
    CONF_MIDNIGHT_SKIP,
    CONF_NIGHT_INTERVAL,
    CONF_NIGHT_MODE,
    CONF_SCAN_INTERVAL,
    CONF_STALE_THRESHOLD,
    CONF_STATION_ID,
    DEFAULT_NIGHT_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_THRESHOLD,
    DOMAIN,
    GOODWE_SPELLING,
    MIDNIGHT_SKIP_END_HOUR,
    MIDNIGHT_SKIP_END_MINUTE,
    MIDNIGHT_SKIP_START_HOUR,
    MIDNIGHT_SKIP_START_MINUTE,
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
    last_updated: float | None = None  # Unix timestamp of last successful fetch
    warnings: list[dict[str, Any]] | None = None
    weather: dict[str, Any] | None = None
    energy_statistics: dict[str, Any] | None = None


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

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: SemsConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SemsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class SemsDataUpdateCoordinator(DataUpdateCoordinator[SemsData]):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, sems_api: SemsApi, entry: SemsConfigEntry
    ) -> None:
        """Initialize."""
        self.sems_api = sems_api
        self.station_id = entry.data[CONF_STATION_ID]

        # Night mode configuration
        self._night_mode_enabled = entry.data.get(CONF_NIGHT_MODE, True)
        self._night_interval = entry.data.get(CONF_NIGHT_INTERVAL, DEFAULT_NIGHT_INTERVAL)
        self._base_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self._is_night = False
        self._last_detailed_fetch: float = 0

        # Midnight skip configuration (avoid phantom data around midnight)
        self._midnight_skip_enabled = entry.data.get(CONF_MIDNIGHT_SKIP, True)
        self._in_midnight_skip = False
        self._cached_data: SemsData | None = None

        # Staleness detection
        self._stale_threshold = entry.data.get(CONF_STALE_THRESHOLD, DEFAULT_STALE_THRESHOLD)
        self._last_successful_fetch: float = 0
        self._was_stale = False

        # Split polling - always poll powerflow at normal rate, full data less often
        self._always_poll_powerflow = entry.data.get(CONF_ALWAYS_POLL_POWERFLOW, True)
        self._last_full_fetch: float = 0

        # Cached data for quick mode merging
        self._cached_inverter_data: dict[str, dict[str, Any]] | None = None
        self._cached_warnings: list[dict[str, Any]] | None = None
        self._cached_weather: dict[str, Any] | None = None
        self._cached_energy_stats: dict[str, Any] | None = None

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
            if self._always_poll_powerflow:
                _LOGGER.info(
                    "SEMS: Entering night mode - powerflow at %ds, full fetch every %ds",
                    self._base_interval,
                    self._night_interval,
                )
            else:
                _LOGGER.info(
                    "SEMS: Entering night mode - skipping detailed inverter data fetch"
                )
            self._is_night = True
        elif not is_night and self._is_night:
            _LOGGER.info("SEMS: Exiting night mode - resuming full data fetch")
            self._is_night = False

    def _should_do_full_fetch(self) -> bool:
        """Determine if we should do a full fetch or quick (powerflow-only) fetch."""
        # Always do full fetch if night mode is disabled
        if not self._night_mode_enabled:
            return True

        # Always do full fetch if not in night time
        if not self._is_night:
            return True

        # If split polling is disabled, always do full fetch
        if not self._always_poll_powerflow:
            return True

        # In night mode with split polling - check if it's time for a full fetch
        if self._last_full_fetch == 0:
            return True

        time_since_full = time.time() - self._last_full_fetch
        return time_since_full >= self._night_interval

    def _is_midnight_window(self) -> bool:
        """Check if current time is in the midnight skip window (23:55-00:10).

        SEMS API returns phantom/incorrect data around midnight, so we skip
        fetching during this window and use cached data instead.
        """
        from datetime import datetime

        now = datetime.now()
        hour = now.hour
        minute = now.minute

        # Check if in window: 23:55-23:59 or 00:00-00:10
        if hour == MIDNIGHT_SKIP_START_HOUR and minute >= MIDNIGHT_SKIP_START_MINUTE:
            return True
        if hour == MIDNIGHT_SKIP_END_HOUR and minute <= MIDNIGHT_SKIP_END_MINUTE:
            return True
        return False

    def _update_midnight_skip_status(self, in_window: bool) -> None:
        """Update midnight skip status and log transitions."""
        if not self._midnight_skip_enabled:
            return

        if in_window and not self._in_midnight_skip:
            _LOGGER.info(
                "SEMS: Entering midnight skip window - using cached data to avoid phantom values"
            )
            self._in_midnight_skip = True
        elif not in_window and self._in_midnight_skip:
            _LOGGER.info("SEMS: Exiting midnight skip window - resuming API fetches")
            self._in_midnight_skip = False

    @property
    def is_stale(self) -> bool:
        """Check if data is stale (older than threshold)."""
        if self._last_successful_fetch == 0:
            return False  # No data yet, not stale
        return (time.time() - self._last_successful_fetch) > self._stale_threshold

    @property
    def data_age_seconds(self) -> float:
        """Return age of data in seconds."""
        if self._last_successful_fetch == 0:
            return 0
        return time.time() - self._last_successful_fetch

    @property
    def data_age_minutes(self) -> float:
        """Return age of data in minutes."""
        return self.data_age_seconds / 60

    def _check_staleness(self) -> None:
        """Check and log staleness transitions."""
        is_now_stale = self.is_stale
        if is_now_stale and not self._was_stale:
            _LOGGER.warning(
                "SEMS: Data is stale - last successful update was %.1f seconds ago "
                "(threshold: %d seconds)",
                self.data_age_seconds,
                self._stale_threshold,
            )
            self._was_stale = True
        elif not is_now_stale and self._was_stale:
            _LOGGER.info("SEMS: Data is no longer stale - fresh data received")
            self._was_stale = False

    async def _async_update_data(self) -> SemsData:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        # Check staleness before update
        self._check_staleness()

        # Check midnight skip window
        if self._midnight_skip_enabled:
            in_midnight_window = self._is_midnight_window()
            self._update_midnight_skip_status(in_midnight_window)

            if in_midnight_window and self._cached_data is not None:
                _LOGGER.debug(
                    "SEMS: Midnight skip active - returning cached data"
                )
                return self._cached_data

        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
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
            if not inverters:
                raise UpdateFailed(
                    "Error communicating with API: missing inverter data"
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

            # Check night mode status
            is_night = self._is_night_time(inverters_by_sn)
            self._update_night_status(is_night)

            # Determine if we should do full fetch (detailed data, warnings, weather, etc.)
            do_full_fetch = self._should_do_full_fetch()

            # Variables for additional data
            warnings_data: list[dict[str, Any]] | None = None
            weather_data: dict[str, Any] | None = None
            energy_stats_data: dict[str, Any] | None = None

            if do_full_fetch:
                # Full fetch - get detailed inverter data
                try:
                    detailed_data = await self.hass.async_add_executor_job(
                        self.sems_api.getInverterAllPoint, self.station_id
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

                # Fetch warnings
                try:
                    warnings_data = await self.hass.async_add_executor_job(
                        self.sems_api.getWarnings, self.station_id
                    )
                    self._cached_warnings = warnings_data
                except Exception as err:
                    _LOGGER.debug("Could not fetch warnings: %s", err)

                # Fetch weather
                try:
                    weather_data = await self.hass.async_add_executor_job(
                        self.sems_api.getWeather, self.station_id
                    )
                    self._cached_weather = weather_data
                except Exception as err:
                    _LOGGER.debug("Could not fetch weather: %s", err)

                # Fetch energy statistics
                try:
                    energy_stats_data = await self.hass.async_add_executor_job(
                        self.sems_api.getEnergyStatistics, self.station_id
                    )
                    if energy_stats_data:
                        self._cached_energy_stats = energy_stats_data
                        _LOGGER.debug(
                            "SEMS: Energy stats - buy=%.1f, sell=%.1f, self_use=%.1f%%",
                            energy_stats_data.get("buy", 0),
                            energy_stats_data.get("sell", 0),
                            energy_stats_data.get("self_use_ratio", 0),
                        )
                except Exception as err:
                    _LOGGER.debug("Could not fetch energy statistics: %s", err)

                # Update full fetch timestamp
                self._last_full_fetch = time.time()
                mode_str = "full"
            else:
                # Quick mode - use cached data
                warnings_data = self._cached_warnings
                weather_data = self._cached_weather
                energy_stats_data = self._cached_energy_stats
                mode_str = "quick (powerflow only)"
                _LOGGER.debug("SEMS: %s - using cached detailed data", mode_str)

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

                # Make a copy to avoid modifying original
                powerflow_data = powerflow.copy()

                # Add energy statistics charts if available
                if has_energy_statistics_charts:
                    charts = result.get(GOODWE_SPELLING.energyStatisticsCharts)
                    if isinstance(charts, dict):
                        for key, val in charts.items():
                            powerflow_data[f"Charts_{key}"] = val
                    totals = result.get(GOODWE_SPELLING.energyStatisticsTotals)
                    if isinstance(totals, dict):
                        for key, val in totals.items():
                            powerflow_data[f"Totals_{key}"] = val

                # Get serial number from homKit
                homekit_data = result.get(GOODWE_SPELLING.homeKit)
                if not isinstance(homekit_data, dict):
                    homekit_data = {}
                sn = homekit_data.get("sn")
                # Goodwe 'Power Meter' (not HomeKit) doesn't have a sn
                if sn is None:
                    sn = "GW-HOMEKIT-NO-SERIAL"

                # Build homekit structure that sensors expect
                # Sensors use value_paths like ["powerflow", "load"], so we need the nested structure
                homekit = {
                    "powerflow": powerflow_data,
                    "sn": sn,
                    "all_time_generation": kpi.get("total_power"),
                }

                # Add energy statistics charts flag if available
                if has_energy_statistics_charts:
                    homekit[GOODWE_SPELLING.hasEnergyStatisticsCharts] = True
                    if result.get(GOODWE_SPELLING.energyStatisticsCharts):
                        homekit[GOODWE_SPELLING.energyStatisticsCharts] = result[GOODWE_SPELLING.energyStatisticsCharts]
                    if result.get(GOODWE_SPELLING.energyStatisticsTotals):
                        homekit[GOODWE_SPELLING.energyStatisticsTotals] = result[GOODWE_SPELLING.energyStatisticsTotals]

            current_time = time.time()
            data = SemsData(
                inverters=inverters_by_sn,
                homekit=homekit,
                currency=currency,
                last_updated=current_time,
                warnings=warnings_data,
                weather=weather_data,
                energy_statistics=energy_stats_data,
            )
            _LOGGER.debug("SEMS %s update complete: %d inverters", mode_str, len(inverters_by_sn))

            # Track successful fetch for staleness detection
            self._last_successful_fetch = current_time
            self._check_staleness()

            # Cache data for midnight skip window
            self._cached_data = data

            return data


# Type alias to make type inference working for pylance
SemsCoordinator = SemsDataUpdateCoordinator

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

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


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
        import time

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
        import time

        if self._last_successful_fetch == 0:
            return False  # No data yet, not stale
        return (time.time() - self._last_successful_fetch) > self._stale_threshold

    @property
    def data_age_seconds(self) -> float:
        """Return age of data in seconds."""
        import time

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

                # Fetch warnings
                try:
                    warnings_data = await self.hass.async_add_executor_job(
                        self.semsApi.getWarnings, self.stationId
                    )
                    self._cached_warnings = warnings_data
                except Exception as err:
                    _LOGGER.debug("Could not fetch warnings: %s", err)

                # Fetch weather
                try:
                    weather_data = await self.hass.async_add_executor_job(
                        self.semsApi.getWeather, self.stationId
                    )
                    self._cached_weather = weather_data
                except Exception as err:
                    _LOGGER.debug("Could not fetch weather: %s", err)

                # Fetch energy statistics
                try:
                    energy_stats_data = await self.hass.async_add_executor_job(
                        self.semsApi.getEnergyStatistics, self.stationId
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
            kpi = result["kpi"]
            currency = kpi.get("currency")

            hasPowerflow = result["hasPowerflow"]
            hasEnergeStatisticsCharts = result["hasEnergeStatisticsCharts"]

            homekit: dict[str, Any] | None = None

            if hasPowerflow:
                _LOGGER.debug("Found powerflow data")
                powerflow_data = result["powerflow"].copy()

                # Get serial number from homKit
                sn = result["homKit"]["sn"]
                # Goodwe 'Power Meter' (not HomeKit) doesn't have a sn
                if sn is None:
                    sn = "GW-HOMEKIT-NO-SERIAL"

                # Build homekit structure that sensors expect
                # Sensors use value_paths like ["powerflow", "load"], so we need the nested structure
                homekit = {
                    "powerflow": powerflow_data,
                    "sn": sn,
                    "all_time_generation": result["kpi"]["total_power"],
                }

                # Add energy statistics charts if available
                if hasEnergeStatisticsCharts:
                    homekit[GOODWE_SPELLING.hasEnergyStatisticsCharts] = True
                    if result.get("energeStatisticsCharts"):
                        homekit[GOODWE_SPELLING.energyStatisticsCharts] = result["energeStatisticsCharts"]
                    if result.get("energeStatisticsTotals"):
                        homekit[GOODWE_SPELLING.energyStatisticsTotals] = result["energeStatisticsTotals"]

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

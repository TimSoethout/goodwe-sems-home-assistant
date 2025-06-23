"""The sems integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.entity_registry import async_migrate_entries

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .sems_api import SemsApi

_LOGGER: logging.Logger = logging.getLogger(__package__)


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


# async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
#     """Set up this integration using UI."""
#     if hass.data.get(DOMAIN) is None:
#         hass.data.setdefault(DOMAIN, {})
#         _LOGGER.info(STARTUP_MESSAGE)

#     username = entry.data.get(CONF_USERNAME)
#     password = entry.data.get(CONF_PASSWORD)

#     conn = Connection(username, password)
#     client = MyenergiClient(conn)

#     coordinator = MyenergiDataUpdateCoordinator(hass, client=client, entry=entry)
#     await coordinator.async_config_entry_first_refresh()

#     hass.data[DOMAIN][entry.entry_id] = coordinator

#     for platform in PLATFORMS:
#         if entry.options.get(platform, True):
#             coordinator.platforms.append(platform)
#             hass.async_add_job(
#                 hass.config_entries.async_forward_entry_setup(entry, platform)
#             )

#     entry.add_update_listener(async_reload_entry)
#     return True


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


# async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
#     """Handle removal of an entry."""
#     coordinator = hass.data[DOMAIN][entry.entry_id]
#     unloaded = all(
#         await asyncio.gather(
#             *[
#                 hass.config_entries.async_forward_entry_unload(entry, platform)
#                 for platform in PLATFORMS
#                 if platform in coordinator.platforms
#             ]
#         )
#     )
#     if unloaded:
#         hass.data[DOMAIN].pop(entry.entry_id)

#     return unloaded


# async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
#     """Reload config entry."""
#     await async_unload_entry(hass, entry)
#     await async_setup_entry(hass, entry)


class SemsDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, semsApi: SemsApi, entry) -> None:
        """Initialize."""
        self.semsApi = semsApi
        self.platforms = []
        self.stationId = entry.data[CONF_STATION_ID]
        self.hass = hass

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

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            # async with async_timeout.timeout(10):
            result = await self.hass.async_add_executor_job(
                self.semsApi.getData, self.stationId
            )
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
            data = {}
            if inverters is None:
                # something went wrong, probably token could not be fetched
                raise UpdateFailed(
                    "Error communicating with API, probably token could not be fetched, see debug logs"
                )
            for inverter in inverters:
                name = inverter["invert_full"]["name"]
                # powerstation_id = inverter["invert_full"]["powerstation_id"]
                sn = inverter["invert_full"]["sn"]
                _LOGGER.debug("Found inverter attribute %s %s", name, sn)
                data[sn] = inverter["invert_full"]

            hasPowerflow = result["hasPowerflow"]
            hasEnergeStatisticsCharts = result["hasEnergeStatisticsCharts"]

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

                data["homeKit"] = powerflow

            _LOGGER.debug("Resulting data: %s", data)
            return data
        # except ApiError as err:
        except Exception as err:
            # logging.exception("Something awful happened!")
            raise UpdateFailed(f"Error communicating with API: {err}") from err


# # migrate to _power ids for inverter entry
# async def async_migrate_entry(hass, config_entry):
#     """Migrate old entry."""
#     _LOGGER.debug(
#         "Migrating configuration from version %s.%s",
#         config_entry.version,
#         config_entry.minor_version,
#     )

#     if config_entry.version < 7:
#         # get existing entities for device
#         semsApi = SemsApi(
#             hass, config_entry.data[CONF_USERNAME], config_entry.data[CONF_PASSWORD]
#         )
#         coordinator = SemsDataUpdateCoordinator(hass, semsApi, config_entry)
#         await coordinator.async_config_entry_first_refresh()

#         _LOGGER.debug(f"found inverter {coordinator.data}")

#         for idx, ent in enumerate(coordinator.data):
#             _LOGGER.debug("Found inverter: %s", ent)

#             old_unique_id = f"{ent}"
#             new_unique_id = f"{old_unique_id}-XXX"
#             _LOGGER.debug(
#                 "Old unique id: %s; new unique id: %s", old_unique_id, new_unique_id
#             )

#             @callback
#             def update_unique_id(entity_entry):
#                 """Update unique ID of entity entry."""
#                 return {
#                     "new_unique_id": entity_entry.unique_id.replace(
#                         old_unique_id, new_unique_id
#                     )
#                 }

#             if old_unique_id != new_unique_id:
#                 await async_migrate_entries(
#                     hass, config_entry.entry_id, update_unique_id
#                 )

#                 hass.config_entries.async_update_entry(
#                     config_entry, unique_id=new_unique_id
#                 )
#                 # version = 7
#                 _LOGGER.info(
#                     "Migrated unique id from %s to %s", old_unique_id, new_unique_id
#                 )

#     _LOGGER.info(
#         "Migration from version %s.%s successful",
#         config_entry.version,
#         config_entry.minor_version,
#     )

#     return True

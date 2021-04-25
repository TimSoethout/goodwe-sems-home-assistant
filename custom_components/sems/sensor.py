"""
Support for power production statistics from GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import logging

from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.const import DEVICE_CLASS_POWER, POWER_WATT, CONF_SCAN_INTERVAL
from homeassistant.helpers.entity import Entity
from .const import DOMAIN, CONF_STATION_ID, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    # _LOGGER.debug("hass.data[DOMAIN] %s", hass.data[DOMAIN])
    semsApi = hass.data[DOMAIN][config_entry.entry_id]
    stationId = config_entry.data[CONF_STATION_ID]

    # _LOGGER.debug("config_entry %s", config_entry.data)
    update_interval = timedelta(
        seconds=config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    async def async_update_data():
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            # async with async_timeout.timeout(10):
            inverters = await hass.async_add_executor_job(semsApi.getData, stationId)
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
            # _LOGGER.debug("Resulting data: %s", data)
            return data
        # except ApiError as err:
        except Exception as err:
            # logging.exception("Something awful happened!")
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        # Name of the data. For logging purposes.
        name="SEMS API",
        update_method=async_update_data,
        # Polling interval. Will only be polled if there are subscribers.
        update_interval=update_interval,
    )

    #
    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    #
    await coordinator.async_config_entry_first_refresh()

    # _LOGGER.debug("Initial coordinator data: %s", coordinator.data)
    async_add_entities(
        SemsSensor(coordinator, ent) for idx, ent in enumerate(coordinator.data)
    )


class SemsSensor(CoordinatorEntity, Entity):
    """SemsSensor using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available
    """

    def __init__(self, coordinator, sn):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.sn = sn
        _LOGGER.debug("Creating SemsSensor with id %s", self.sn)

    @property
    def device_class(self):
        return DEVICE_CLASS_POWER

    @property
    def unit_of_measurement(self):
        return POWER_WATT

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"Inverter {self.coordinator.data[self.sn]['name']}"

    @property
    def unique_id(self) -> str:
        return self.coordinator.data[self.sn]["sn"]

    @property
    def state(self):
        """Return the state of the device."""
        # _LOGGER.debug("state, coordinator data: %s", self.coordinator.data)
        # _LOGGER.debug("self.sn: %s", self.sn)
        # _LOGGER.debug(
        #     "state, self data: %s", self.coordinator.data[self.sn]
        # )
        data = self.coordinator.data[self.sn]
        return data["pac"] if data["status"] == 1 else 0

    def statusText(self, status) -> str:
        labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
        return labels[status] if status in labels else "Unknown"

    # For backwards compatibility
    @property
    def extra_state_attributes(self):
        """Return the state attributes of the monitored installation."""
        data = self.coordinator.data[self.sn]
        # _LOGGER.debug("state, self data: %s", data.items())
        attributes = {k: v for k, v in data.items() if k is not None and v is not None}
        attributes["statusText"] = self.statusText(data["status"])
        return attributes

    @property
    def is_on(self) -> bool:
        """Return entity status."""
        self.coordinator.data[self.sn]["status"] == 1

    @property
    def should_poll(self):
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self.coordinator.async_request_refresh()

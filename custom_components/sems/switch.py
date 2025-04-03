"""Support for switch controlling an output of a GoodWe SEMS inverter.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add switches for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    # stationId = config_entry.data[CONF_STATION_ID]

    async_add_entities(
        SemsStatusSwitch(coordinator, ent) for idx, ent in enumerate(coordinator.data)
    )


class SemsStatusSwitch(CoordinatorEntity, SwitchEntity):
    """SemsStatusSwitch using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available
    """

    # Sensor has device name (e.g. Inverter 123456 Power)
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator, sn) -> None:
        """Initialize the SemsStatusSwitch.

        Args:
            coordinator: The data update coordinator for managing updates.
            sn: The serial number of the inverter.

        """
        super().__init__(coordinator, context=sn)
        self.coordinator = coordinator
        # self.api = api
        self.sn = sn
        _LOGGER.debug("Creating SemsStatusSwitch for Inverter %s", self.sn)

    # @property
    # def name(self) -> str:
    #     """Return the name of the switch."""
    #     return f"Inverter {self.coordinator.data[self.sn]['name']} Switch"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{self.sn}-switch"

    @property
    def device_info(self):
        """Return device information for the inverter."""
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.sn)
            },
            "name": self.name,
            "manufacturer": "GoodWe",
        }

    @property
    def is_on(self) -> bool:
        """Return entity status."""
        _LOGGER.debug("coordinator.data[sn]: %s", self.coordinator.data[self.sn])
        return self.coordinator.data[self.sn]["status"] == 1

    async def async_turn_off(self, **kwargs):
        """Turn off the inverter."""
        _LOGGER.debug("Inverter %s set to Off", self.sn)
        await self.hass.async_add_executor_job(
            self.coordinator.semsApi.change_status, self.sn, 2
        )

    async def async_turn_on(self, **kwargs):
        """Turn on the inverter."""
        _LOGGER.debug("Inverter %s set to On", self.sn)
        await self.hass.async_add_executor_job(
            self.coordinator.semsApi.change_status, self.sn, 4
        )

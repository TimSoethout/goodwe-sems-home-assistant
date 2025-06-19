"""Support for switch controlling an output of a GoodWe SEMS inverter.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
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
    # _attr_name = None

    def __init__(self, coordinator, sn) -> None:
        """Initialize the SemsStatusSwitch.

        Args:
            coordinator: The data update coordinator for managing updates.
            sn: The serial number of the inverter.

        """
        super().__init__(coordinator, context=sn)
        self.coordinator = coordinator
        self.sn = sn
        self._attr_device_info = DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.sn)
            },
            name=f"Inverter {self.coordinator.data[self.sn]['name']}",
        )
        self._attr_unique_id = f"{self.sn}-switch"
        # somehow needed, no default naming
        self._attr_name = "Switch"
        self._attr_device_class = SwitchDeviceClass.OUTLET
        _LOGGER.debug("Creating SemsStatusSwitch for Inverter %s", self.sn)

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

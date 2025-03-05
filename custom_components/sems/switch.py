"""
Support for switch controlling an output of a GoodWe SEMS inverter.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import logging

from homeassistant.const import (
    CONF_SCAN_INTERVAL,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import UpdateFailed
from .const import DOMAIN, CONF_STATION_ID
from homeassistant.components.switch import SwitchEntity

from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add switches for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    # semsApi = hass.data[DOMAIN][config_entry.entry_id]
    stationId = config_entry.data[CONF_STATION_ID]

    # try:
    #     result = await hass.async_add_executor_job(semsApi.getData, stationId)

    # except Exception as err:
    #     # logging.exception("Something awful happened!")
    #     raise UpdateFailed(f"Error communicating with API: {err}")

    # inverters = result["inverter"]
    # entities = []
    # for inverter in inverters:
    # entities.append(SemsSwitch(semsApi, inverter["invert_full"]["sn"]))

    async_add_entities(
        SemsStatusSwitch(coordinator, ent) for idx, ent in enumerate(coordinator.data)
    )
    # async_add_entities(entities)


class SemsStatusSwitch(CoordinatorEntity, SwitchEntity):
    """SemsStatusSwitch using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available
    """

    def __init__(self, coordinator, api, sn):
        super().__init__(coordinator, context=sn)
        self.coordinator = coordinator
        self.api = api
        self.sn = sn
        _LOGGER.debug(f"Creating SemsStatusSwitch for Inverter {self.sn}")

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return f"Inverter {self.sn} Status Switch"

    @property
    def unique_id(self) -> str:
        return f"{self.sn}-status-switch"

    @property
    def device_info(self):
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
        return self.coordinator.data[self.sn]["status"] == 1

    async def async_turn_off(self, **kwargs):
        _LOGGER.debug(f"Inverter {self.sn} set to Off")
        await self.api.change_status(self.sn, 2)

    async def async_turn_on(self, **kwargs):
        _LOGGER.debug(f"Inverter {self.sn} set to On")
        await self.api.change_status(self.sn, 4)


# class SemsSwitch(SwitchEntity):

#     def __init__(self, api, sn):
#         super().__init__()
#         self.api = api
#         self.sn = sn
#         _LOGGER.debug(f"Creating SemsSwitch for Inverter {self.sn}")

#     @property
#     def name(self) -> str:
#         """Return the name of the switch."""
#         return f"Inverter {self.sn} Switch"


#     @property
#     def unique_id(self) -> str:
#         return f"{self.sn}-switch"

#     @property
#     def device_info(self):
#         return {
#             "identifiers": {
#                 # Serial numbers are unique identifiers within a specific domain
#                 (DOMAIN, self.sn)
#             },
#             "name": "Homekit",
#             "manufacturer": "GoodWe",
#         }

#     async def async_turn_off(self, **kwargs):
#         _LOGGER.debug(f"Inverter {self.sn} set to Off")
#         await self.api.change_status(self.sn, 2)

#     async def async_turn_on(self, **kwargs):
#         _LOGGER.debug(f"Inverter {self.sn} set to On")
#         await self.api.change_status(self.sn, 4)

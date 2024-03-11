"""
Support for power production statistics from GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

from typing import Coroutine
from homeassistant.core import HomeAssistant
import homeassistant
import logging

from datetime import timedelta

from homeassistant.const import (
    CONF_SCAN_INTERVAL,
)
from homeassistant.helpers.entity import Entity
from .const import DOMAIN, CONF_STATION_ID
from homeassistant.components.switch import SwitchEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    # _LOGGER.debug("hass.data[DOMAIN] %s", hass.data[DOMAIN])
    semsApi = hass.data[DOMAIN][config_entry.entry_id]
    stationId = config_entry.data[CONF_STATION_ID]

    entities = [SemsSwitch(semsApi, stationId)]
    async_add_entities(entities)

class SemsSwitch(SwitchEntity):

    def __init__(self, api, stationId):
        super().__init__()
        self.api = api
        self.stationId = stationId
        _LOGGER.info("Creating SemsSwitch with id %s", self.stationId)

    # def turn_off(self, **kwargs):
    #     _LOGGER.warn("Off " + self.stationId)

    # def turn_on(self, **kwargs):
    #     _LOGGER.warn("On " + self.stationId)

    @property
    def is_on(self) -> bool:
        """Return entity status."""
        return True

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return f"Inverter {self.stationId} Switch"


    @property
    def unique_id(self) -> str:
        return f"{self.stationId}-switch"

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.stationId)
            },
            "name": "Homekit",
            "manufacturer": "GoodWe",
        }

    def async_turn_off(self, **kwargs):
        _LOGGER.warn("Off " + self.stationId)
        self.api.change_status(self.stationId, 0)

    def async_turn_on(self, **kwargs):
        _LOGGER.warn("On " + self.stationId)
        self.api.change_status(self.stationId, 1)

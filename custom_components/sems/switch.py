"""Support for inverter control switches from the GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SemsCoordinator
from .const import DOMAIN
from .device import device_info_for_inverter

_LOGGER = logging.getLogger(__name__)

_INVERTER_STATUS_ON = 1
_COMMAND_TURN_OFF = 2
_COMMAND_TURN_ON = 4


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEMS switches from a config entry."""
    coordinator: SemsCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities(
        SemsStatusSwitch(coordinator, sn)
        for sn in coordinator.data.inverters
        if sn != "homeKit"
    )


class SemsStatusSwitch(CoordinatorEntity[SemsCoordinator], SwitchEntity):
    """Switch to control inverter status, backed by the SEMS coordinator."""

    # Sensor has device name (e.g. Inverter 123456 Power)
    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SemsCoordinator, sn: str) -> None:
        """Initialize the SemsStatusSwitch.

        Args:
            coordinator: The data update coordinator for managing updates.
            sn: The serial number of the inverter.

        """
        _LOGGER.debug("Try create SemsStatusSwitch for inverter %s", sn)
        super().__init__(coordinator)
        self._sn = sn
        inverter_data = coordinator.data.inverters.get(sn, {})
        self._attr_device_info = device_info_for_inverter(sn, inverter_data)
        self._attr_unique_id = f"{self._sn}-switch"
        # somehow needed, no default naming
        self._attr_name = "Switch"
        _LOGGER.debug("Creating SemsStatusSwitch for Inverter %s", self._sn)

    @property
    def is_on(self) -> bool:
        """Return entity status."""
        status = self.coordinator.data.inverters.get(self._sn, {}).get("status")
        return status == _INVERTER_STATUS_ON

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the inverter."""
        _LOGGER.debug("Inverter %s set to off", self._sn)
        await self.hass.async_add_executor_job(
            self.coordinator.semsApi.change_status,
            self._sn,
            _COMMAND_TURN_OFF,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the inverter."""
        _LOGGER.debug("Inverter %s set to on", self._sn)
        await self.hass.async_add_executor_job(
            self.coordinator.semsApi.change_status,
            self._sn,
            _COMMAND_TURN_ON,
        )
        await self.coordinator.async_request_refresh()

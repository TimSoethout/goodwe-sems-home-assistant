"""Support for inverter control switches from the GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SemsCoordinator
from .const import CONF_STATION_ID
from .device import device_info_for_inverter

_LOGGER = logging.getLogger(__name__)

_INVERTER_STATUS_ON = 1
_COMMAND_TURN_OFF = 2
_COMMAND_TURN_ON = 4


class SemsSwitchBase(CoordinatorEntity[SemsCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: SemsCoordinator,
        serial_number: str,
        function_name: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        inverter_data = coordinator.data.inverters.get(serial_number, {})
        self._attr_device_info = device_info_for_inverter(serial_number, inverter_data)
        self._attr_unique_id = f"{serial_number}-{function_name}"
        self._attr_name = name
        self.serial_number = serial_number

    async def _async_execute(self, method: Any, *args: Any) -> None:
        """Execute a blocking API method and refresh coordinator data."""
        if self.coordinator.data is None:
            raise HomeAssistantError(
                f"Unable to update {self.entity_id}: no coordinator data"
            )

        await self.hass.async_add_executor_job(method, *args)
        await self.coordinator.async_request_refresh()


class SemsInverterSwitch(SemsSwitchBase):
    """Switch controlling an inverter's operating status."""

    def __init__(self, coordinator: SemsCoordinator, serial_number: str) -> None:
        super().__init__(coordinator, serial_number, "switch", "Switch")

    @property
    def is_on(self) -> bool | None:
        return (
            self.coordinator.data.inverters.get(self.serial_number, {}).get("status")
            == _INVERTER_STATUS_ON
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_execute(
            self.coordinator.sems_api.change_status,
            self.serial_number,
            _COMMAND_TURN_ON,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_execute(
            self.coordinator.sems_api.change_status,
            self.serial_number,
            _COMMAND_TURN_OFF,
        )


class SemsBatteryImmediateChargingSwitch(SemsSwitchBase):
    """Switch controlling a battery's immediate charging mode."""

    def __init__(
        self,
        coordinator: SemsCoordinator,
        plant_id: str,
        serial_number: str,
        battery_id: str,
        battery_name: str,
        functions: dict[str, dict[str, str]],
    ) -> None:
        super().__init__(
            coordinator,
            serial_number,
            f"{battery_id}-battery_immediate_charging",
            f"Battery {battery_name} Immediate Charging",
        )
        self.plant_id = plant_id
        self.battery_id = battery_id
        self.functions = functions

    @property
    def is_on(self) -> bool | None:
        return bool(
            (self.coordinator.data.immediate_charging or {})
            .get(self.serial_number, {})
            .get("enabled", False)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        function = self.functions["immediate_charge"]
        await self._async_execute(
            self.coordinator.sems_api.startImmediateCharging,
            self.plant_id,
            self.serial_number,
            self.battery_id,
            function["address"],
            function["id"],
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        function = self.functions["stop_charging"]
        await self._async_execute(
            self.coordinator.sems_api.stopImmediateCharging,
            self.plant_id,
            self.serial_number,
            self.battery_id,
            function["address"],
            function["id"],
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEMS switches from a config entry."""
    coordinator = config_entry.runtime_data.coordinator

    switch_entities: list[SwitchEntity] = []

    for sn in coordinator.data.inverters:
        switch_entities.append(SemsInverterSwitch(coordinator, sn))

    for sn, bats in (coordinator.data.batteries or {}).items():
        for bat_id, bat_data in bats.items():
            functions = bat_data["functions"]
            if {"immediate_charge", "stop_charging"} <= functions.keys():
                switch_entities.append(
                    SemsBatteryImmediateChargingSwitch(
                        coordinator,
                        config_entry.data[CONF_STATION_ID],
                        sn,
                        bat_id,
                        bat_data["name"],
                        functions,
                    )
                )

    async_add_entities(switch_entities)

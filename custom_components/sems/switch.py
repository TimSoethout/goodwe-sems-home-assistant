"""Support for inverter control switches from the GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
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


class SemsSwitch(CoordinatorEntity[SemsCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_name = ""

    plant_id: str = ""
    serial_number: str = ""
    device_name: str = ""
    on_address: str = ""
    on_function_id: str = ""
    off_address: str = ""
    off_function_id: str = ""
    is_on_fn: Callable[[SemsSwitch], bool]
    turn_on_fn: Callable[[SemsSwitch], None]
    turn_off_fn: Callable[[SemsSwitch], None]
    coordinator: SemsCoordinator

    def __init__(
        self,
        coordinator: SemsCoordinator,
        is_on_fn: Callable[[SemsSwitch], bool],
        turn_on_fn: Callable[[SemsSwitch], None],
        turn_off_fn: Callable[[SemsSwitch], None],
        plant_id: str = "",
        serial_number: str = "",
        device_name: str = "",
        function_name: str = "",
        friendly_name: str = "",
        on_address: str = "",
        on_function_id: str = "",
        off_address: str = "",
        off_function_id: str = "",
    ) -> None:
        super().__init__(coordinator)
        inverter_data = coordinator.data.inverters.get(serial_number, {})
        self._attr_device_info = device_info_for_inverter(serial_number, inverter_data)

        unique_id = serial_number
        if device_name != "":
            unique_id += "-" + device_name

        if function_name != "":
            unique_id += "-" + function_name

        if device_name == "" and function_name == "":
            unique_id += "-switch"

        self._attr_unique_id = unique_id

        self._attr_name = friendly_name
        self.plant_id = plant_id
        self.serial_number = serial_number
        self.device_name = device_name
        self.on_address = on_address
        self.on_function_id = on_function_id
        self.off_address = off_address
        self.off_function_id = off_function_id
        self.is_on_fn = is_on_fn
        self.turn_on_fn = turn_on_fn
        self.turn_off_fn = turn_off_fn
        self.coordinator = coordinator

        _LOGGER.debug(
            "Created SemsSwitch with id `%s`, `%s`",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        try:
            value = self.is_on_fn(self)
            # Ensure the value is a boolean
            return bool(value)

        except (TypeError, ValueError, KeyError) as e:
            _LOGGER.error(
                "Error getting on value for %s: %s",
                self.entity_id,
                e,
            )
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.coordinator.data is None:
            raise HomeAssistantError(
                f"Unable to turn on {self.entity_id}: no coordinator data"
            )

        # Run the blocking API call in the executor
        await self.hass.async_add_executor_job(self.turn_on_fn, self)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.coordinator.data is None:
            raise HomeAssistantError(
                f"Unable to turn off {self.entity_id}: no coordinator data"
            )

        # Run the blocking API call in the executor
        await self.hass.async_add_executor_job(self.turn_off_fn, self)
        await self.coordinator.async_request_refresh()


@dataclass(frozen=True)
class SemsSwitchEntityDescription(SwitchEntityDescription):
    """Class describing SEMS switch entities."""

    on_key: str | None = None
    off_key: str | None = None
    is_on_fn: Callable[[SemsSwitch], bool] = lambda switch: False
    turn_on_fn: Callable[[SemsSwitch], None] = lambda switch: None
    turn_off_fn: Callable[[SemsSwitch], None] = lambda switch: None


BATTERY_SWITCHES = [
    SemsSwitchEntityDescription(
        key="battery_immediate_charging",
        name="Immediate Charging",
        on_key="immediate_charge",
        off_key="stop_charging",
        is_on_fn=lambda switch: (
            (switch.coordinator.data.immediate_charging or {})
            .get(switch.serial_number, {})
            .get("enabled", False)
        ),
        turn_on_fn=lambda switch: switch.coordinator.sems_api.startImmediateCharging(
            switch.plant_id,
            switch.serial_number,
            switch.device_name,
            switch.on_address,
            switch.on_function_id,
        ),
        turn_off_fn=lambda switch: switch.coordinator.sems_api.stopImmediateCharging(
            switch.plant_id,
            switch.serial_number,
            switch.device_name,
            switch.off_address,
            switch.off_function_id,
        ),
    ),
]

INVERTER_SWITCHES = [
    SemsSwitchEntityDescription(
        key="switch",
        name="Switch",
        is_on_fn=lambda switch: (
            switch.coordinator.data.inverters.get(switch.serial_number, {}).get(
                "status"
            )
            == _INVERTER_STATUS_ON
        ),
        turn_on_fn=lambda switch: switch.coordinator.sems_api.change_status(
            switch.serial_number, _COMMAND_TURN_ON
        ),
        turn_off_fn=lambda switch: switch.coordinator.sems_api.change_status(
            switch.serial_number, _COMMAND_TURN_OFF
        ),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEMS switches from a config entry."""
    coordinator = config_entry.runtime_data.coordinator

    switch_entities: list[SemsSwitch] = []

    for sn in coordinator.data.inverters:
        for switch in INVERTER_SWITCHES:
            switch_entities.append(
                SemsSwitch(
                    coordinator,
                    switch.is_on_fn,
                    switch.turn_on_fn,
                    switch.turn_off_fn,
                    config_entry.data[CONF_STATION_ID],
                    sn,
                    "",
                    switch.key,
                    str(switch.name),
                    "",
                    "",
                    "",
                    "",
                )
            )

    for sn, bats in (coordinator.data.batteries or {}).items():
        for bat_id, bat_data in bats.items():
            for switch in BATTERY_SWITCHES:
                if (
                    switch.on_key in bat_data["functions"]
                    and switch.off_key in bat_data["functions"]
                ):
                    switch_entities.append(
                        SemsSwitch(
                            coordinator,
                            switch.is_on_fn,
                            switch.turn_on_fn,
                            switch.turn_off_fn,
                            config_entry.data[CONF_STATION_ID],
                            sn,
                            bat_id,
                            switch.key,
                            f"Battery {bat_data['name']} {switch.name}",
                            bat_data["functions"][switch.on_key]["address"],
                            bat_data["functions"][switch.on_key]["id"],
                            bat_data["functions"][switch.off_key]["address"],
                            bat_data["functions"][switch.off_key]["id"],
                        )
                    )

    async_add_entities(switch_entities)

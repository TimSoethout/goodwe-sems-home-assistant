"""Number platform for SEMS integration"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SemsConfigEntry, SemsCoordinator
from .const import CONF_STATION_ID
from .device import device_info_for_inverter

_LOGGER = logging.getLogger(__name__)


class SemsNumber(CoordinatorEntity[SemsCoordinator], NumberEntity):
    _attr_has_entity_name = True

    plant_id: str = ""
    serial_number: str = ""
    device_name: str = ""
    address: str = ""
    function_id: str = ""
    value_fn: Callable[["SemsNumber"], float]
    set_value_fn: Callable[["SemsNumber", float], None]
    coordinator: SemsCoordinator

    def __init__(
        self,
        coordinator: SemsCoordinator,
        value_fn: Callable[["SemsNumber"], float],
        set_value_fn: Callable[["SemsNumber", float], None],
        plant_id: str = "",
        serial_number: str = "",
        device_name: str = "",
        function_name: str = "",
        friendly_name: str = "",
        address: str = "",
        function_id: str = "",
    ):
        super().__init__(coordinator)
        inverter_data = coordinator.data.inverters.get(serial_number, {})
        self._attr_device_info = device_info_for_inverter(serial_number, inverter_data)
        self._attr_unique_id = f"{serial_number}-{device_name}-{function_name}"
        self._attr_name = friendly_name
        self.plant_id = plant_id
        self.serial_number = serial_number
        self.device_name = device_name
        self.address = address
        self.function_id = function_id
        self.value_fn = value_fn
        self.set_value_fn = set_value_fn
        self.coordinator = coordinator

        _LOGGER.debug(
            "Created SemsNumber with id `%s`, `%s`",
            self._attr_unique_id,
            self._attr_name,
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        try:
            value = self.value_fn(self)
            # Ensure the value is a float
            return float(value) if value is not None else None

        except (TypeError, ValueError, KeyError) as e:
            _LOGGER.error(
                "Error getting native value for %s: %s",
                self.entity_id,
                e,
            )
            return None

    async def async_set_native_value(self, value: float) -> None:
        if self.coordinator.data is None:
            raise HomeAssistantError(
                f"Unable to set value for {self.entity_id}: no coordinator data"
            )

        await self.hass.async_add_executor_job(self.set_value_fn, self, value)
        await self.coordinator.async_request_refresh()


@dataclass(frozen=True)
class SemsNumberEntityDescription(NumberEntityDescription):
    """Class describing SEMS number entities."""

    value_fn: Callable[[SemsNumber], float] = lambda num: 0.0
    set_value_fn: Callable[[SemsNumber, float], None] = lambda num, value: None


IMMEDIATE_CHARGING_NUMBERS = {
    "end_charge_soc": SemsNumberEntityDescription(
        key="end_charge_soc",
        name="End Charge SoC",
        native_max_value=100,
        native_min_value=0,
        native_step=1,
        value_fn=lambda number: (
            (number.coordinator.data.immediate_charging or {})
            .get(number.serial_number, {})
            .get("end_charge_soc", 0.0)
        ),
        set_value_fn=lambda number, value: (
            number.coordinator.sems_api.setImmediateChargingEndSoC(
                number.plant_id,
                number.serial_number,
                number.device_name,
                int(value),
                number.address,
                number.function_id,
            )
        ),
    ),
    "bat_immediate_charge_power": SemsNumberEntityDescription(
        key="bat_immediate_charge_power",
        name="Charging Power",
        native_max_value=100,
        native_min_value=0,
        native_step=1,
        value_fn=lambda number: (
            (number.coordinator.data.immediate_charging or {})
            .get(number.serial_number, {})
            .get("charging_power", 0.0)
        ),
        set_value_fn=lambda number, value: (
            number.coordinator.sems_api.setImmediateChargingChargingPower(
                number.plant_id,
                number.serial_number,
                number.device_name,
                int(value),
                number.address,
                number.function_id,
            )
        ),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SemsConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up SEMS number entities from a config entry."""
    coordinator: SemsCoordinator = config_entry.runtime_data.coordinator

    number_entities: list[SemsNumber] = []

    for sn, bats in (coordinator.data.batteries or {}).items():
        for bat_id, bat_data in bats.items():
            for func_name, func_data in bat_data["functions"].items():
                if func_name in IMMEDIATE_CHARGING_NUMBERS:
                    number_entities.append(
                        SemsNumber(
                            coordinator,
                            IMMEDIATE_CHARGING_NUMBERS[func_name].value_fn,
                            IMMEDIATE_CHARGING_NUMBERS[func_name].set_value_fn,
                            config_entry.data[CONF_STATION_ID],
                            sn,
                            bat_id,
                            func_name,
                            f"Battery {bat_data['name']} {IMMEDIATE_CHARGING_NUMBERS[func_name].name}",
                            func_data["address"],
                            func_data["id"],
                        )
                    )

    async_add_entities(number_entities)

"""Number platform for the GoodWe SEMS integration."""

from collections.abc import Callable

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SemsConfigEntry, SemsCoordinator
from .const import CONF_STATION_ID
from .device import device_info_for_inverter

type SetBatteryValueMethod = Callable[[str, str, str, int, str, str], None]


class SemsBatteryNumber(CoordinatorEntity[SemsCoordinator], NumberEntity):
    """Base class for battery immediate-charging controls."""

    _attr_has_entity_name = True
    function_name: str
    name: str

    def __init__(
        self,
        coordinator: SemsCoordinator,
        plant_id: str,
        serial_number: str,
        battery_id: str,
        battery_name: str,
        function: dict[str, str],
    ) -> None:
        super().__init__(coordinator)
        inverter_data = coordinator.data.inverters.get(serial_number, {})
        self._attr_device_info = device_info_for_inverter(serial_number, inverter_data)
        self._attr_unique_id = f"{serial_number}-{battery_id}-{self.function_name}"
        self._attr_name = f"Battery {battery_name} {self.name}"
        self.plant_id = plant_id
        self.serial_number = serial_number
        self.battery_id = battery_id
        self.function = function

    async def _async_set_value(self, method: SetBatteryValueMethod, value: float) -> None:
        if self.coordinator.data is None:
            raise HomeAssistantError(
                f"Unable to set value for {self.entity_id}: no coordinator data"
            )

        await self.hass.async_add_executor_job(
            method,
            self.plant_id,
            self.serial_number,
            self.battery_id,
            int(value),
            self.function["address"],
            self.function["id"],
        )
        await self.coordinator.async_request_refresh()


class SemsBatteryEndChargeSocNumber(SemsBatteryNumber):
    """Number controlling the immediate-charging end state of charge."""

    _attr_native_max_value = 100
    _attr_native_min_value = 0
    _attr_native_step = 1
    function_name = "end_charge_soc"
    name = "End Charge SoC"

    @property
    def native_value(self) -> float:
        return float(
            (self.coordinator.data.immediate_charging or {})
            .get(self.serial_number, {})
            .get("end_charge_soc", 0.0)
        )

    async def async_set_native_value(self, value: float) -> None:
        await self._async_set_value(
            self.coordinator.sems_api.setImmediateChargingEndSoC, value
        )


class SemsBatteryChargingPowerNumber(SemsBatteryNumber):
    """Number controlling immediate-charging power."""

    _attr_native_max_value = 100
    _attr_native_min_value = 0
    _attr_native_step = 1
    function_name = "bat_immediate_charge_power"
    name = "Charging Power"

    @property
    def native_value(self) -> float:
        return float(
            (self.coordinator.data.immediate_charging or {})
            .get(self.serial_number, {})
            .get("charging_power", 0.0)
        )

    async def async_set_native_value(self, value: float) -> None:
        await self._async_set_value(
            self.coordinator.sems_api.setImmediateChargingChargingPower, value
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SemsConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up SEMS number entities from a config entry."""
    coordinator: SemsCoordinator = config_entry.runtime_data.coordinator

    number_entities: list[NumberEntity] = []

    for sn, bats in (coordinator.data.batteries or {}).items():
        for bat_id, bat_data in bats.items():
            functions = bat_data["functions"]
            for function_name, number_class in (
                ("end_charge_soc", SemsBatteryEndChargeSocNumber),
                ("bat_immediate_charge_power", SemsBatteryChargingPowerNumber),
            ):
                if function := functions.get(function_name):
                    number_entities.append(
                        number_class(
                            coordinator,
                            config_entry.data[CONF_STATION_ID],
                            sn,
                            bat_id,
                            bat_data["name"],
                            function,
                        )
                    )

    async_add_entities(number_entities)

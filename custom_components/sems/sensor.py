"""Support for power production statistics from GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    Platform,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SemsConfigEntry, SemsCoordinator, SemsData
from .const import (
    AC_CURRENT_EMPTY,
    AC_EMPTY,
    AC_FEQ_EMPTY,
    DOMAIN,
    GOODWE_SPELLING,
    STALE_THRESHOLD_MINUTES,
    STATUS_LABELS,
)
from .device import device_info_for_inverter

_LOGGER = logging.getLogger(__name__)

type SemsValuePath = list[str | int]


@dataclass(slots=True)
class SemsSensorType:
    """SEMS sensor definition."""

    device_info: DeviceInfo
    unique_id: str
    value_path: SemsValuePath
    name: str | None = None  # Name is None when it is determined by device class / UOM.
    device_class: SensorDeviceClass | None = None
    native_unit_of_measurement: str | None = None
    state_class: SensorStateClass | None = None
    empty_value: Any = None
    data_type_converter: Callable = Decimal
    custom_value_handler: Callable[[Any, dict[str, Any]], Any] | None = None


@dataclass(slots=True)
class SemsHomekitSensorType(SemsSensorType):
    """SEMS HomeKit/powerflow sensor definition."""


@dataclass(slots=True)
class SemsInverterSensorType(SemsSensorType):
    """SEMS inverter sensor definition."""


def get_homekit_sn(homekit_data: dict[str, Any] | None) -> str | None:
    """Return the HomeKit serial number from coordinator data, if available."""

    if homekit_data is None:
        return None
    value = homekit_data.get("sn")
    return value if isinstance(value, str) else None


def get_has_existing_homekit_entity(
    homekit_data: dict[str, Any] | None, hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Return whether a HomeKit entity already exists for this config entry."""

    home_kit_sn = get_homekit_sn(homekit_data)
    if home_kit_sn is not None:
        ent_reg = er.async_get(hass)
        entities = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
        for entity in entities:
            if entity.unique_id == home_kit_sn:
                return True
    return False


def sensor_options_for_data(
    data: SemsData, has_existing_homekit_entity: bool = False
) -> list[SemsSensorType]:
    """Build a list of sensor definitions for the given coordinator data."""

    sensors: list[SemsSensorType] = []
    currency = data.currency
    _LOGGER.debug("Detected currency: %s", currency)

    for serial_number, inverter_data in data.inverters.items():
        # serial_number = inverter["sn"]
        path_to_inverter: SemsValuePath = [serial_number]
        # device_data = get_value_from_path(data, path_to_inverter)

        device_info = device_info_for_inverter(serial_number, inverter_data)
        sensors += [
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-status",
                [*path_to_inverter, "status"],
                "Status",
                data_type_converter=lambda status, labels=STATUS_LABELS: labels.get(
                    int(status), "Unknown"
                ),
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-capacity",
                [*path_to_inverter, "capacity"],
                "Capacity",
                SensorDeviceClass.POWER,
                UnitOfPower.KILO_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-power",
                # "Power",
                [*path_to_inverter, "pac"],
                device_class=SensorDeviceClass.POWER,
                native_unit_of_measurement=UnitOfPower.WATT,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-energy",
                [*path_to_inverter, "etotal"],
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                state_class=SensorStateClass.TOTAL_INCREASING,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-hour-total",
                [*path_to_inverter, "hour_total"],
                "Total Hours",
                native_unit_of_measurement=UnitOfTime.HOURS,
                state_class=SensorStateClass.TOTAL_INCREASING,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-temperature",
                [*path_to_inverter, GOODWE_SPELLING.temperature],
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                state_class=SensorStateClass.MEASUREMENT,
                empty_value=0,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-eday",
                [*path_to_inverter, "eday"],
                "Energy Today",
                SensorDeviceClass.ENERGY,
                UnitOfEnergy.KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-{GOODWE_SPELLING.thisMonthTotalE}",
                [*path_to_inverter, GOODWE_SPELLING.thisMonthTotalE],
                "Energy This Month",
                SensorDeviceClass.ENERGY,
                UnitOfEnergy.KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-{GOODWE_SPELLING.lastMonthTotalE}",
                [*path_to_inverter, GOODWE_SPELLING.lastMonthTotalE],
                "Energy Last Month",
                SensorDeviceClass.ENERGY,
                UnitOfEnergy.KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-iday",
                [*path_to_inverter, "iday"],
                "Income Today",
                SensorDeviceClass.MONETARY,
                currency,
                SensorStateClass.TOTAL,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-itotal",
                [*path_to_inverter, "itotal"],
                "Income Total",
                SensorDeviceClass.MONETARY,
                currency,
                SensorStateClass.TOTAL,
            ),
        ]
        # Multiple strings
        sensors += [
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-vpv{idx}",
                [*path_to_inverter, f"vpv{idx}"],
                f"PV String {idx} Voltage",
                SensorDeviceClass.VOLTAGE,
                UnitOfElectricPotential.VOLT,
                SensorStateClass.MEASUREMENT,
                0,
            )
            for idx in range(1, 5)
            if get_value_from_path(data.inverters, [*path_to_inverter, f"vpv{idx}"])
            is not None
        ]
        sensors += [
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-ipv{idx}",
                [*path_to_inverter, f"ipv{idx}"],
                f"PV String {idx} Current",
                SensorDeviceClass.CURRENT,
                UnitOfElectricCurrent.AMPERE,
                SensorStateClass.MEASUREMENT,
                0,
            )
            for idx in range(1, 5)
            if get_value_from_path(data.inverters, [*path_to_inverter, f"ipv{idx}"])
            is not None
        ]
        sensors += [
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-vac{idx}",
                [*path_to_inverter, f"vac{idx}"],
                f"Grid {idx} AC Voltage",
                SensorDeviceClass.VOLTAGE,
                UnitOfElectricPotential.VOLT,
                SensorStateClass.MEASUREMENT,
                AC_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-iac{idx}",
                [*path_to_inverter, f"iac{idx}"],
                f"Grid {idx} AC Current",
                SensorDeviceClass.CURRENT,
                UnitOfElectricCurrent.AMPERE,
                SensorStateClass.MEASUREMENT,
                AC_CURRENT_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-fac{idx}",
                [*path_to_inverter, f"fac{idx}"],
                f"Grid {idx} AC Frequency",
                SensorDeviceClass.FREQUENCY,
                UnitOfFrequency.HERTZ,
                SensorStateClass.MEASUREMENT,
                AC_FEQ_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-vbattery1",
                [*path_to_inverter, "vbattery1"],
                "Battery Voltage",
                SensorDeviceClass.VOLTAGE,
                UnitOfElectricPotential.VOLT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsInverterSensorType(
                device_info,
                f"{serial_number}-ibattery1",
                [*path_to_inverter, "ibattery1"],
                "Battery Current",
                SensorDeviceClass.CURRENT,
                UnitOfElectricCurrent.AMPERE,
                SensorStateClass.MEASUREMENT,
            ),
        ]
        battery_count = get_value_from_path(
            data.inverters, [*path_to_inverter, "battery_count"]
        )
        if isinstance(battery_count, int):
            for idx in range(battery_count):
                path_to_battery: SemsValuePath = [
                    *path_to_inverter,
                    "more_batterys",
                    idx,
                ]
                sensors += [
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-pbattery",
                        [*path_to_battery, "pbattery"],
                        f"Battery {idx} Power",
                        SensorDeviceClass.POWER,
                        UnitOfPower.WATT,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-vbattery",
                        [*path_to_battery, "vbattery"],
                        f"Battery {idx} Voltage",
                        SensorDeviceClass.VOLTAGE,
                        UnitOfElectricPotential.VOLT,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-ibattery",
                        [*path_to_battery, "ibattery"],
                        f"Battery {idx} Current",
                        SensorDeviceClass.CURRENT,
                        UnitOfElectricCurrent.AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-soc",
                        [*path_to_battery, "soc"],
                        f"Battery {idx} State of Charge",
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-soh",
                        [*path_to_battery, "soh"],
                        f"Battery {idx} State of Health",
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-bms_temperature",
                        [*path_to_battery, "bms_temperature"],
                        f"Battery {idx} BMS Temperature",
                        SensorDeviceClass.TEMPERATURE,
                        UnitOfTemperature.CELSIUS,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-bms_discharge_i_max",
                        [*path_to_battery, "bms_discharge_i_max"],
                        f"Battery {idx} BMS Discharge Max Current",
                        SensorDeviceClass.CURRENT,
                        UnitOfElectricCurrent.AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsInverterSensorType(
                        device_info,
                        f"{serial_number}-{idx}-bms_charge_i_max",
                        [*path_to_battery, "bms_charge_i_max"],
                        f"Battery {idx} BMS Charge Max Current",
                        SensorDeviceClass.CURRENT,
                        UnitOfElectricCurrent.AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                ]
        _LOGGER.debug("Sensors for inverter %s: %s", serial_number, sensors)

    # HomeKit powerflow + SEMS charts live in `SemsData.homekit`.
    if data.homekit is not None:
        inverter_serial_number = get_homekit_sn(data.homekit)
        if not has_existing_homekit_entity or inverter_serial_number is None:
            inverter_serial_number = "powerflow"
        serial_backwards_compatibility = (
            "homeKit"  # the old code uses homeKit for the serial number
        )
        device_info = DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, serial_backwards_compatibility)
            },
            name="HomeKit",
            manufacturer="GoodWe",
        )

        def status_value_handler(
            status_path: SemsValuePath,
        ) -> Callable[[Any, dict[str, Any]], Any]:
            """Return a handler that applies a sign depending on grid status."""

            def value_status_handler(value: Any, data: dict[str, Any]) -> Any:
                """Apply the grid status sign to the given value."""
                if value is None:
                    return None
                grid_status = get_value_from_path(data, status_path)
                if grid_status is None:
                    return value
                try:
                    return Decimal(str(value)) * int(grid_status)
                except (TypeError, ValueError):
                    return value

            return value_status_handler

        def grid_value_handler(value: Any, data: dict[str, Any]) -> Any:
            """Apply sign to grid power: positive=importing, negative=exporting."""
            if value is None:
                return None
            grid_status = get_value_from_path(data, ["powerflow", "gridStatus"])
            if grid_status is None:
                return value
            try:
                # gridStatus: -1=importing, 1=exporting
                # We want: positive=importing, negative=exporting
                # So: if exporting (status=1), negate the value
                status = int(grid_status)
                if status == 1:  # Exporting
                    return -Decimal(str(value))
                return Decimal(str(value))  # Importing or idle
            except (TypeError, ValueError):
                return value

        sensors += [
            SemsHomekitSensorType(
                device_info,
                f"{inverter_serial_number}",  # backwards compatibility otherwise would be f"{serial_number}-load"
                ["powerflow", "load"],
                "HomeKit Load",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
                custom_value_handler=status_value_handler(["powerflow", "loadStatus"]),
            ),
            SemsHomekitSensorType(
                device_info,
                f"{inverter_serial_number}-pv",
                ["powerflow", "pv"],
                "HomeKit PV",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsHomekitSensorType(
                device_info,
                f"{inverter_serial_number}-grid",
                ["powerflow", "grid"],
                "HomeKit Grid",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
                custom_value_handler=grid_value_handler,
            ),
            SemsHomekitSensorType(
                device_info,
                f"{inverter_serial_number}-load-status",
                ["powerflow", "loadStatus"],
                "HomeKit Load Status",
                None,
                None,
                SensorStateClass.MEASUREMENT,
                custom_value_handler=status_value_handler(["powerflow", "gridStatus"]),
            ),
            SemsHomekitSensorType(
                device_info,
                f"{inverter_serial_number}-battery",
                ["powerflow", GOODWE_SPELLING.battery],
                "HomeKit Battery",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
                custom_value_handler=status_value_handler(
                    ["powerflow", GOODWE_SPELLING.batteryStatus]
                ),
            ),
            SemsHomekitSensorType(
                device_info,
                f"{inverter_serial_number}-genset",
                ["powerflow", "genset"],
                "HomeKit generator",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsHomekitSensorType(
                device_info,
                f"{inverter_serial_number}-soc",
                ["powerflow", "soc"],
                "HomeKit State of Charge",
                SensorDeviceClass.BATTERY,
                PERCENTAGE,
                SensorStateClass.MEASUREMENT,
            ),
        ]
        if data.homekit.get(GOODWE_SPELLING.hasEnergyStatisticsCharts):
            if data.homekit.get(GOODWE_SPELLING.energyStatisticsCharts):
                sensors += [
                    SemsHomekitSensorType(
                        device_info,
                        f"{inverter_serial_number}-import-energy",
                        [GOODWE_SPELLING.energyStatisticsCharts, "buy"],
                        "SEMS Import",
                        SensorDeviceClass.ENERGY,
                        UnitOfEnergy.KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                    SemsHomekitSensorType(
                        device_info,
                        f"{inverter_serial_number}-export-energy",
                        [GOODWE_SPELLING.energyStatisticsCharts, "sell"],
                        "SEMS Export",
                        SensorDeviceClass.ENERGY,
                        UnitOfEnergy.KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                ]
            if data.homekit.get(GOODWE_SPELLING.energyStatisticsTotals):
                sensors += [
                    SemsHomekitSensorType(
                        device_info,
                        f"{inverter_serial_number}-import-energy-total",
                        [GOODWE_SPELLING.energyStatisticsTotals, "buy"],
                        "SEMS Total Import",
                        SensorDeviceClass.ENERGY,
                        UnitOfEnergy.KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                    SemsHomekitSensorType(
                        device_info,
                        f"{inverter_serial_number}-export-energy-total",
                        [GOODWE_SPELLING.energyStatisticsTotals, "sell"],
                        "SEMS Total Export",
                        SensorDeviceClass.ENERGY,
                        UnitOfEnergy.KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                ]
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SemsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coordinator = config_entry.runtime_data.coordinator

    # _LOGGER.debug("Initial coordinator data: %s", coordinator.data)

    # Backwards compatibility note: keep IDs stable for existing entity registry entries.
    for _idx, ent in enumerate(coordinator.data.inverters):
        _migrate_to_new_unique_id(hass, ent)

    has_existing_homekit_entity = get_has_existing_homekit_entity(
        coordinator.data.homekit, hass, config_entry
    )

    sensor_options: list[SemsSensorType] = sensor_options_for_data(
        coordinator.data, has_existing_homekit_entity
    )
    sensors = [
        (
            SemsHomekitSensor
            if isinstance(sensor_option, SemsHomekitSensorType)
            else SemsInverterSensor
        )(
            coordinator,
            sensor_option.device_info,
            sensor_option.unique_id,
            sensor_option.name,
            sensor_option.value_path,
            sensor_option.data_type_converter,
            sensor_option.device_class,
            sensor_option.native_unit_of_measurement,
            sensor_option.state_class,
            sensor_option.empty_value,
            sensor_option.custom_value_handler,
        )
        for sensor_option in sensor_options
    ]

    # Create device info for plant-level sensors
    plant_device = DeviceInfo(
        identifiers={(DOMAIN, "sems_plant")},
        name="SEMS Plant",
        manufacturer="GoodWe",
        model="Power Plant Monitor",
    )

    # Add powerflow status sensors if homekit data available
    if coordinator.data.homekit is not None:
        powerflow = coordinator.data.homekit.get("powerflow", {})
        if powerflow:
            sensors.append(SemsPowerflowStatusSensor(
                coordinator, plant_device, "grid", "Grid Status"
            ))
            sensors.append(SemsPowerflowStatusSensor(
                coordinator, plant_device, "pv", "Solar Status"
            ))
            # Battery status only if battery present
            if powerflow.get(GOODWE_SPELLING.battery) is not None:
                sensors.append(SemsPowerflowStatusSensor(
                    coordinator, plant_device, GOODWE_SPELLING.battery, "Battery Status"
                ))

    # Add weather sensors if weather data available
    weather_device = DeviceInfo(
        identifiers={(DOMAIN, "sems_weather")},
        name="Solar Site Weather",
        manufacturer="GoodWe",
        model="Weather Station",
    )
    if coordinator.data.weather is not None:
        sensors.append(SemsWeatherSensor(coordinator, weather_device, "temp", "Temperature"))
        sensors.append(SemsWeatherSensor(coordinator, weather_device, "humidity", "Humidity"))
        sensors.append(SemsWeatherSensor(coordinator, weather_device, "weather_type", "Conditions"))
        sensors.append(SemsWeatherSensor(coordinator, weather_device, "uv_index", "UV Index"))

    # Add energy statistics sensors if data available
    stats_device = DeviceInfo(
        identifiers={(DOMAIN, "energy_stats")},
        name="Energy Statistics",
        manufacturer="GoodWe",
        model="Grid Metering",
    )
    if coordinator.data.energy_statistics is not None:
        sensors.append(SemsEnergyStatsSensor(
            coordinator, stats_device, "buy", "Grid Import Today"
        ))
        sensors.append(SemsEnergyStatsSensor(
            coordinator, stats_device, "sell", "Grid Export Today"
        ))
        sensors.append(SemsEnergyStatsSensor(
            coordinator, stats_device, "self_use_of_pv", "Self Consumption Today"
        ))
        sensors.append(SemsEnergyStatsSensor(
            coordinator, stats_device, "consumption_of_load", "Total Load Today"
        ))
        sensors.append(SemsSelfConsumptionSensor(coordinator, stats_device))
        sensors.append(SemsContributionRatioSensor(coordinator, stats_device))

    # Add warning sensor
    sensors.append(SemsWarningSensor(coordinator, plant_device))

    # Add data age sensor for staleness detection
    sensors.append(SemsDataAgeSensor(coordinator, plant_device))

    async_add_entities(sensors)

    # async_add_entities(
    #     SemsSensor(coordinator, ent)
    #     for idx, ent in enumerate(coordinator.data)
    #     # Don't make SemsSensor for homeKit, since it is not an inverter; unsure how this could work before...
    #     if ent != "homeKit"
    # )
    # async_add_entities(
    #     SemsStatisticsSensor(coordinator, ent)
    #     for idx, ent in enumerate(coordinator.data)


# Migrate old power sensor unique ids to new unique ids (with `-power`)
def _migrate_to_new_unique_id(hass: HomeAssistant, sn: str) -> None:
    """Migrate old unique ids to new unique ids."""
    ent_reg = er.async_get(hass)

    old_unique_id = sn
    new_unique_id = f"{old_unique_id}-power"
    _LOGGER.debug("Old unique id: %s; new unique id: %s", old_unique_id, new_unique_id)
    entity_id = ent_reg.async_get_entity_id(Platform.SENSOR, DOMAIN, old_unique_id)
    _LOGGER.debug("Entity ID: %s", entity_id)
    if entity_id is not None:
        try:
            ent_reg.async_update_entity(entity_id, new_unique_id=new_unique_id)
        except ValueError:
            _LOGGER.warning(
                "Skip migration of id [%s] to [%s] because it already exists",
                old_unique_id,
                new_unique_id,
            )
        else:
            _LOGGER.info(
                "Migrating unique_id from [%s] to [%s]",
                old_unique_id,
                new_unique_id,
            )


def get_value_from_path(data: dict[str, Any], path: SemsValuePath) -> Any:
    """Return the value at a nested path in a dict, or `None` if missing."""

    value: Any = data
    try:
        for key in path:
            value = value[key]
    except (KeyError, TypeError):
        return None
    return value


class SemsSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Representation of a GoodWe SEMS sensor backed by the shared coordinator."""

    str_clean_regex = re.compile(r"(\d+\.?\d*)")

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
        unique_id: str,
        name: str | None,
        value_path: SemsValuePath,
        data_type_converter: Callable,
        device_class: SensorDeviceClass | None = None,
        native_unit_of_measurement: str | None = None,
        state_class: SensorStateClass | None = None,
        empty_value=None,
        custom_value_handler=None,
    ) -> None:
        """Initialize a SEMS sensor."""

        super().__init__(coordinator)
        self._value_path = value_path
        self._data_type_converter = data_type_converter
        self._empty_value = empty_value

        self._attr_unique_id = unique_id
        self._attr_device_info = device_info
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = native_unit_of_measurement
        self._attr_state_class = state_class

        # When `name` is None, Home Assistant determines the name from
        # device class / unit (using has_entity_name).
        if name is not None:
            self._attr_name = name

        self._custom_value_handler = custom_value_handler

        raw_value = self._get_native_value_from_coordinator()

        # Disable-by-default must be decided before registry entry is created.
        if raw_value is None or (
            self._empty_value is not None and raw_value == self._empty_value
        ):
            _LOGGER.debug(
                "Disabling SemsSensor `%s` by default since initial value is None or empty (`%s`)",
                unique_id,
                raw_value,
            )
            self._attr_entity_registry_enabled_default = False

        _LOGGER.debug(
            "Created SemsSensor with id `%s`, `%s`, value path `%s`",  # , data `%s`",
            unique_id,
            name,
            value_path,
        )

    def _get_native_value_from_coordinator(self) -> Any:
        """Get the raw value from coordinator data."""

        data = self._get_data_dict()
        if data is None:
            return None
        return get_value_from_path(data, self._value_path)

    def _get_data_dict(self) -> dict[str, Any] | None:
        """Return the dict to read values from."""

        return self.coordinator.data.inverters

    @property
    def native_value(self) -> Any:
        """Return the current value."""

        value = self._get_native_value_from_coordinator()

        if isinstance(value, str):
            if match := self.str_clean_regex.search(value):
                value = match.group(1)

        if value is None:
            return None
        if self._empty_value is not None and value == self._empty_value:
            return None

        if self._custom_value_handler is not None:
            data = self._get_data_dict()
            if data is None:
                return None
            return self._custom_value_handler(value, data)

        try:
            return self._data_type_converter(value)
        except (TypeError, ValueError):
            return value

    # @property
    # def suggested_display_precision(self):
    #     """Return the suggested number of decimal digits for display."""
    #     return 2


class SemsInverterSensor(SemsSensor):
    """Sensor that reads from inverter data."""

    def _get_data_dict(self) -> dict[str, Any] | None:
        """Return inverter dict."""

        return self.coordinator.data.inverters

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return inverter attributes for backwards compatibility."""

        if not (unique_id := self._attr_unique_id) or not unique_id.endswith("-power"):
            return None

        if not self._value_path:
            return None

        inverter_sn = self._value_path[0]
        if not isinstance(inverter_sn, str):
            return None

        inverter_data = self.coordinator.data.inverters.get(inverter_sn)
        if inverter_data is None:
            return None

        attributes = {
            key: value
            for key, value in inverter_data.items()
            if key is not None and value is not None
        }

        status = inverter_data.get("status")
        if status is None:
            attributes["statusText"] = "Unknown"
        else:
            try:
                attributes["statusText"] = STATUS_LABELS.get(int(status), "Unknown")
            except (TypeError, ValueError):
                attributes["statusText"] = "Unknown"

        return attributes


class SemsHomekitSensor(SemsSensor):
    """Sensor that reads from HomeKit/powerflow data."""

    def _get_data_dict(self) -> dict[str, Any] | None:
        """Return HomeKit dict."""

        return self.coordinator.data.homekit


class SemsPowerflowStatusSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Sensor for power flow status (direction) - Importing/Exporting/Idle."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"powerflow_{key}_status"
        self._attr_name = name
        self._attr_device_info = device_info

    @property
    def native_value(self) -> str | None:
        """Return the status as human-readable value."""
        if self.coordinator.data.homekit is None:
            return None
        powerflow = self.coordinator.data.homekit.get("powerflow", {})
        status = powerflow.get(f"{self._key}Status", 0)

        if self._key == "grid":
            if status == -1:
                return "Importing"
            elif status == 1:
                return "Exporting"
            return "Idle"
        elif self._key == "pv":
            if status == -1:
                return "Generating"
            return "Idle"
        elif self._key == GOODWE_SPELLING.battery:
            if status == -1:
                return "Charging"
            elif status == 1:
                return "Discharging"
            return "Idle"
        return str(status)

    @property
    def icon(self) -> str:
        """Return icon based on status."""
        if self.coordinator.data.homekit is None:
            return "mdi:power-plug-off"
        powerflow = self.coordinator.data.homekit.get("powerflow", {})
        status = powerflow.get(f"{self._key}Status", 0)

        if self._key == "grid":
            if status == -1:
                return "mdi:transmission-tower-import"
            elif status == 1:
                return "mdi:transmission-tower-export"
            return "mdi:transmission-tower"
        elif self._key == "pv":
            if status == -1:
                return "mdi:solar-power"
            return "mdi:solar-power-variant-outline"
        elif self._key == GOODWE_SPELLING.battery:
            if status == -1:
                return "mdi:battery-charging"
            elif status == 1:
                return "mdi:battery-arrow-down"
            return "mdi:battery"
        return "mdi:help-circle"


class SemsWeatherSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Sensor for weather data at the solar site."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"weather_{key}"
        self._attr_name = name
        self._attr_device_info = device_info

        if key == "temp":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif key == "humidity":
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif key == "uv_index":
            self._attr_icon = "mdi:sun-wireless"
            self._attr_state_class = SensorStateClass.MEASUREMENT
        else:
            self._attr_icon = "mdi:weather-partly-cloudy"

    def _get_today_forecast(self) -> dict[str, Any]:
        """Extract today's forecast from HeWeather6 data."""
        if self.coordinator.data.weather is None:
            return {}

        weather = self.coordinator.data.weather
        he_weather = weather.get("HeWeather6", [])
        if he_weather and len(he_weather) > 0:
            daily = he_weather[0].get("daily_forecast", [])
            if daily and len(daily) > 0:
                return daily[0]
        return weather

    @property
    def native_value(self) -> Any:
        """Return the weather value."""
        forecast = self._get_today_forecast()

        if self._key == "temp":
            temp = forecast.get("tmp_max", forecast.get("temp", forecast.get("temperature")))
            if temp is not None:
                try:
                    return float(str(temp).replace("°C", "").replace("℃", "").strip())
                except (ValueError, TypeError):
                    pass
            return None
        elif self._key == "humidity":
            humidity = forecast.get("hum", forecast.get("humidity"))
            if humidity is not None:
                try:
                    return float(str(humidity).replace("%", "").strip())
                except (ValueError, TypeError):
                    pass
            return None
        elif self._key == "weather_type":
            return forecast.get("cond_txt_d", forecast.get("weather_type", forecast.get("condition")))
        elif self._key == "uv_index":
            uv = forecast.get("uv_index")
            if uv is not None:
                try:
                    return int(uv)
                except (ValueError, TypeError):
                    pass
            return None

        return forecast.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all weather data as attributes."""
        forecast = self._get_today_forecast()
        attrs = {}
        field_map = {
            "tmp_max": "high_temp",
            "tmp_min": "low_temp",
            "hum": "humidity",
            "cond_txt_d": "condition_day",
            "cond_txt_n": "condition_night",
            "wind_dir": "wind_direction",
            "wind_spd": "wind_speed",
            "uv_index": "uv_index",
        }
        for api_key, attr_name in field_map.items():
            if api_key in forecast and forecast[api_key] is not None:
                attrs[attr_name] = forecast[api_key]
        return attrs


class SemsEnergyStatsSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Sensor for energy statistics (grid import/export)."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
        stat_key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._stat_key = stat_key
        self._attr_unique_id = f"energy_stats_{stat_key}"
        self._attr_name = name
        self._attr_device_info = device_info

        if stat_key == "sell":
            self._attr_icon = "mdi:transmission-tower-export"
        elif stat_key == "buy":
            self._attr_icon = "mdi:transmission-tower-import"
        elif stat_key == "self_use_of_pv":
            self._attr_icon = "mdi:solar-power"
        else:
            self._attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self) -> float | None:
        """Return the energy statistic value."""
        if self.coordinator.data.energy_statistics is None:
            return None
        return self.coordinator.data.energy_statistics.get(self._stat_key, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional statistics as attributes."""
        if self.coordinator.data.energy_statistics is None:
            return {}
        energy_stats = self.coordinator.data.energy_statistics
        attrs = {}
        if self._stat_key == "buy":
            attrs["percentage_of_load"] = energy_stats.get("buy_percent", 0)
        elif self._stat_key == "sell":
            attrs["percentage_of_generation"] = energy_stats.get("sell_percent", 0)
        return attrs


class SemsSelfConsumptionSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Sensor for self-consumption rate (percentage of PV used directly)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "self_consumption_rate"
        self._attr_name = "Self Consumption Rate"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        """Return the self-consumption rate from API."""
        if self.coordinator.data.energy_statistics is None:
            return None
        ratio = self.coordinator.data.energy_statistics.get("self_use_ratio")
        if ratio is not None:
            return round(ratio, 1)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed energy breakdown."""
        if self.coordinator.data.energy_statistics is None:
            return {}
        energy_stats = self.coordinator.data.energy_statistics
        return {
            "generation_today": energy_stats.get("generation", 0),
            "self_consumed": energy_stats.get("self_use_of_pv", 0),
            "export_today": energy_stats.get("sell", 0),
            "import_today": energy_stats.get("buy", 0),
            "total_load": energy_stats.get("consumption_of_load", 0),
        }


class SemsContributionRatioSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Sensor for PV contribution ratio (percentage of load supplied by PV)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:solar-power-variant"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "pv_contribution_rate"
        self._attr_name = "PV Contribution Rate"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        """Return the PV contribution rate."""
        if self.coordinator.data.energy_statistics is None:
            return None
        ratio = self.coordinator.data.energy_statistics.get("contribution_ratio")
        if ratio is not None:
            return round(ratio * 100, 1)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return energy breakdown."""
        if self.coordinator.data.energy_statistics is None:
            return {}
        energy_stats = self.coordinator.data.energy_statistics
        return {
            "pv_used_by_load": energy_stats.get("self_use_of_pv", 0),
            "total_load": energy_stats.get("consumption_of_load", 0),
            "grid_import": energy_stats.get("buy", 0),
            "grid_import_percent": energy_stats.get("buy_percent", 0),
        }


class SemsWarningSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Sensor for active warnings count."""

    _attr_icon = "mdi:alert"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "sems_warnings"
        self._attr_name = "Active Warnings"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int:
        """Return the warning count."""
        if self.coordinator.data.warnings is None:
            return 0
        warnings = self.coordinator.data.warnings
        if isinstance(warnings, list):
            return len(warnings)
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return warning details."""
        if self.coordinator.data.warnings is None:
            return {}
        warnings = self.coordinator.data.warnings
        if not warnings:
            return {}
        return {"warnings": warnings}

    @property
    def icon(self) -> str:
        """Return icon based on warning count."""
        count = self.native_value
        if count > 0:
            return "mdi:alert-circle"
        return "mdi:check-circle"


class SemsDataAgeSensor(CoordinatorEntity[SemsCoordinator], SensorEntity):
    """Sensor for data freshness/staleness detection."""

    _attr_icon = "mdi:clock-check-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "min"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SemsCoordinator,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "sems_data_age"
        self._attr_name = "Data Age"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        """Return the data age in minutes."""
        age = self.coordinator.data_age_minutes
        if age is not None:
            return round(age, 1)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return staleness details."""
        return {
            "is_stale": self.coordinator.is_stale,
            "stale_threshold_minutes": STALE_THRESHOLD_MINUTES,
            "data_age_seconds": round(self.coordinator.data_age_seconds, 1),
        }

    @property
    def icon(self) -> str:
        """Return icon based on staleness."""
        if self.coordinator.is_stale:
            return "mdi:clock-alert-outline"
        return "mdi:clock-check-outline"

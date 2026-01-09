"""Support for power production statistics from GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import re
from typing import Any

# from typing import Coroutine
import homeassistant
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
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
from homeassistant.helpers import entity_registry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import (
    async_entries_for_config_entry as entities_for_config_entry,
    async_get as async_get_entity_registry,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import SemsData, SemsDataUpdateCoordinator
from .const import (
    AC_CURRENT_EMPTY,
    AC_EMPTY,
    AC_FEQ_EMPTY,
    DOMAIN,
    # CONF_STATION_ID,
    # DEFAULT_SCAN_INTERVAL,
    # API_UPDATE_ERROR_MSG,
    GOODWE_SPELLING,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SemsSensorType:
    """SEMS Sensor Definition"""

    device_info: DeviceInfo
    unique_id: str
    value_path: list[str]
    name: str | None = (
        None  # name is None, when the sensor name is determined by device class / unit of measurement
    )
    device_class: SensorDeviceClass | None = None
    native_unit_of_measurement: str | None = None
    state_class: SensorStateClass | None = None
    empty_value: Any = None
    data_type_converter: Callable = Decimal
    custom_value_handler = None


def get_home_kit_sn(data):
    return get_value_from_path(data, [GOODWE_SPELLING.homeKit, "sn"])


def get_has_existing_homekit_entity(data, hass, config_entry) -> bool:
    home_kit_sn = get_home_kit_sn(data)
    if home_kit_sn is not None:
        ent_reg = async_get_entity_registry(hass)
        entities = entities_for_config_entry(ent_reg, config_entry.entry_id)
        for entity in entities:
            if entity.unique_id == home_kit_sn:
                return True
    return False


def sensor_options_for_data(
    data: SemsData, has_existing_homekit_entity: bool = False
) -> list[SemsSensorType]:
    # if has_existing_homekit_entity is None:
    # has_existing_homekit_entity = False
    sensors: list[SemsSensorType] = []
    currency = data.currency
    _LOGGER.debug("Detected currency: %s", currency)

    for serial_number, inverter_data in data.inverters.items():
        # serial_number = inverter["sn"]
        path_to_inverter = [serial_number]
        name = inverter_data.get("name", "unknown")
        # device_data = get_value_from_path(data, path_to_inverter)

        device_info = DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, serial_number)
            },
            name=f"Inverter {name}",
            manufacturer="GoodWe",
            model=inverter_data.get("model_type", "unknown"),
            sw_version=inverter_data.get("firmwareversion", "unknown"),
            configuration_url=f"https://semsportal.com/PowerStation/PowerStatusSnMin/{inverter_data['powerstation_id']}",
        )
        sensors += [
            SemsSensorType(
                device_info,
                f"{serial_number}-capacity",
                path_to_inverter + ["capacity"],
                "Capacity",
                SensorDeviceClass.POWER,
                UnitOfPower.KILO_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-power",  # backwards compatibility otherwise would be f"{serial_number}-power"
                # TODO maybe add all attributes to this sensor
                # "Power",
                path_to_inverter + ["pac"],
                device_class=SensorDeviceClass.POWER,
                native_unit_of_measurement=UnitOfPower.WATT,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-energy",
                path_to_inverter + ["etotal"],
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                state_class=SensorStateClass.TOTAL_INCREASING,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-hour-total",
                path_to_inverter + ["hour_total"],
                "Total Hours",
                native_unit_of_measurement=UnitOfTime.HOURS,
                state_class=SensorStateClass.TOTAL_INCREASING,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-temperature",
                path_to_inverter + [GOODWE_SPELLING.temperature],
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-eday ",
                path_to_inverter + ["eday"],
                "Energy Today",
                SensorDeviceClass.ENERGY,
                UnitOfEnergy.KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-{GOODWE_SPELLING.thisMonthTotalE}",
                path_to_inverter + [GOODWE_SPELLING.thisMonthTotalE],
                "Energy This Month",
                SensorDeviceClass.ENERGY,
                UnitOfEnergy.KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-{GOODWE_SPELLING.lastMonthTotalE}",
                path_to_inverter + [GOODWE_SPELLING.lastMonthTotalE],
                "Energy Last Month",
                SensorDeviceClass.ENERGY,
                UnitOfEnergy.KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-iday",
                path_to_inverter + ["iday"],
                "Income Today",
                SensorDeviceClass.MONETARY,
                currency,
                SensorStateClass.TOTAL,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-itotal",
                path_to_inverter + ["itotal"],
                "Income Total",
                SensorDeviceClass.MONETARY,
                currency,
                SensorStateClass.TOTAL,
            ),
        ]
        # Multiple strings
        sensors += [
            SemsSensorType(
                device_info,
                f"{serial_number}-vpv{idx}",
                path_to_inverter + [f"vpv{idx}"],
                f"PV String {idx} Voltage",
                SensorDeviceClass.VOLTAGE,
                UnitOfElectricPotential.VOLT,
                SensorStateClass.MEASUREMENT,
                0,
            )
            for idx in range(1, 5)
            if get_value_from_path(data.inverters, path_to_inverter + [f"vpv{idx}"])
            is not None
        ]
        sensors += [
            SemsSensorType(
                device_info,
                f"{serial_number}-ipv{idx}",
                path_to_inverter + [f"ipv{idx}"],
                f"PV String {idx} Current",
                SensorDeviceClass.CURRENT,
                UnitOfElectricCurrent.AMPERE,
                SensorStateClass.MEASUREMENT,
                0,
            )
            for idx in range(1, 5)
            if get_value_from_path(data.inverters, path_to_inverter + [f"ipv{idx}"])
            is not None
        ]
        sensors += [
            SemsSensorType(
                device_info,
                f"{serial_number}-vac{idx}",
                path_to_inverter + [f"vac{idx}"],
                f"Grid {idx} AC Voltage",
                SensorDeviceClass.VOLTAGE,
                UnitOfElectricPotential.VOLT,
                SensorStateClass.MEASUREMENT,
                AC_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SemsSensorType(
                device_info,
                f"{serial_number}-iac{idx}",
                path_to_inverter + [f"iac{idx}"],
                f"Grid {idx} AC Current",
                SensorDeviceClass.CURRENT,
                UnitOfElectricCurrent.AMPERE,
                SensorStateClass.MEASUREMENT,
                AC_CURRENT_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SemsSensorType(
                device_info,
                f"{serial_number}-fac{idx}",
                path_to_inverter + [f"fac{idx}"],
                f"Grid {idx} AC Frequency",
                SensorDeviceClass.FREQUENCY,
                UnitOfFrequency.HERTZ,
                SensorStateClass.MEASUREMENT,
                AC_FEQ_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SemsSensorType(
                device_info,
                f"{serial_number}-vbattery1",
                path_to_inverter + ["vbattery1"],
                "Battery Voltage",
                SensorDeviceClass.VOLTAGE,
                UnitOfElectricPotential.VOLT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsSensorType(
                device_info,
                f"{serial_number}-ibattery1",
                path_to_inverter + ["ibattery1"],
                "Battery Current",
                SensorDeviceClass.CURRENT,
                UnitOfElectricCurrent.AMPERE,
                SensorStateClass.MEASUREMENT,
            ),
        ]
        # TODO Consider separate devices?
        battery_count = get_value_from_path(
            data.inverters, path_to_inverter + ["battery_count"]
        )
        if battery_count is not None:
            for idx in range(0, battery_count):
                path_to_battery = path_to_inverter + ["more_batterys", idx]
                sensors += [
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-pbattery",
                        path_to_battery + ["pbattery"],
                        "Battery {idx} Power",
                        SensorDeviceClass.POWER,
                        UnitOfPower.WATT,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-vbattery",
                        path_to_battery + ["vbattery"],
                        f"Battery {idx} Voltage",
                        SensorDeviceClass.VOLTAGE,
                        UnitOfElectricPotential.VOLT,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-ibattery",
                        path_to_battery + ["ibattery"],
                        f"Battery {idx} Current",
                        SensorDeviceClass.CURRENT,
                        UnitOfElectricCurrent.AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-soc",
                        path_to_battery + ["soc"],
                        f"Battery {idx} State of Charge",
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-soh",
                        path_to_battery + ["soh"],
                        f"Battery {idx} State of Health",
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-bms_temperature",
                        path_to_battery + ["bms_temperature"],
                        f"Battery {idx} BMS Temperature",
                        SensorDeviceClass.TEMPERATURE,
                        UnitOfTemperature.CELSIUS,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-bms_discharge_i_max",
                        path_to_battery + ["bms_discharge_i_max"],
                        f"Battery {idx} BMS Discharge Max Current",
                        SensorDeviceClass.CURRENT,
                        UnitOfElectricCurrent.AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{serial_number}-{idx}-bms_charge_i_max",
                        path_to_battery + ["bms_charge_i_max"],
                        f"Battery {idx} BMS Charge Max Current",
                        SensorDeviceClass.CURRENT,
                        UnitOfElectricCurrent.AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                ]
        _LOGGER.debug("Sensors for inverter %s: %s", serial_number, sensors)

    # Powerflow + SEMS charts live inside the "homeKit" inverter payload.
    if "homeKit" in data.inverters:
        inverter_serial_number = get_home_kit_sn(data.inverters)
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

        def status_value_handler(status_path):
            """
            Handler for values that are dependent on the status of the grid.
            @param status_path: the path to the status value
            """

            def value_status_handler(value, data):
                """
                Handler for the value that is dependent on the status of the grid.
                @param value: the value to be handled
                @param data: the data from the coordinator
                """
                if value is None:
                    return None
                grid_status = get_value_from_path(data, status_path)
                if grid_status is None:
                    return value
                return value * int(grid_status)

            return value_status_handler

        sensors += [
            SemsSensorType(
                device_info,
                f"{inverter_serial_number}",  # backwards compatibility otherwise would be f"{serial_number}-load"
                ["powerflow", "load"],
                "HomeKit Load",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
                status_value_handler(["powerflow", "loadStatus"]),
            ),
            SemsSensorType(
                device_info,
                f"{inverter_serial_number}-pv",
                ["powerflow", "pv"],
                "HomeKit PV",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsSensorType(
                device_info,
                f"{inverter_serial_number}-grid",
                ["powerflow", "grid"],
                "HomeKit Grid",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsSensorType(
                device_info,
                f"{inverter_serial_number}-load-status",
                ["powerflow", "loadStatus"],
                "HomeKit Load Status",
                None,
                None,
                SensorStateClass.MEASUREMENT,
                status_value_handler(["powerflow", "gridStatus"]),
            ),
            SemsSensorType(
                device_info,
                f"{inverter_serial_number}-battery",
                ["powerflow", GOODWE_SPELLING.battery],
                "HomeKit Battery",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
                status_value_handler(["powerflow", GOODWE_SPELLING.batteryStatus]),
            ),
            SemsSensorType(
                device_info,
                f"{inverter_serial_number}-genset",
                ["powerflow", "genset"],
                "HomeKit generator",
                SensorDeviceClass.POWER,
                UnitOfPower.WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SemsSensorType(
                device_info,
                f"{inverter_serial_number}-soc",
                ["powerflow", "soc"],
                "HomeKit State of Charge",
                SensorDeviceClass.BATTERY,
                PERCENTAGE,
                SensorStateClass.MEASUREMENT,
            ),
        ]
        if (
            GOODWE_SPELLING.hasEnergyStatisticsCharts in data.inverters["homeKit"]
            and data.inverters["homeKit"][GOODWE_SPELLING.hasEnergyStatisticsCharts]
        ):
            if data.inverters["homeKit"][GOODWE_SPELLING.energyStatisticsCharts]:
                sensors += [
                    SemsSensorType(
                        device_info,
                        f"{inverter_serial_number}-import-energy",
                        [GOODWE_SPELLING.energyStatisticsCharts, "buy"],
                        "SEMS Import",
                        SensorDeviceClass.ENERGY,
                        UnitOfEnergy.KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                    SemsSensorType(
                        device_info,
                        f"{inverter_serial_number}-export-energy",
                        [GOODWE_SPELLING.energyStatisticsCharts, "sell"],
                        "SEMS Export",
                        SensorDeviceClass.ENERGY,
                        UnitOfEnergy.KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                ]
            if data.inverters["homeKit"][GOODWE_SPELLING.energyStatisticsTotals]:
                sensors += [
                    SemsSensorType(
                        device_info,
                        f"{inverter_serial_number}-import-energy-total",
                        [GOODWE_SPELLING.energyStatisticsTotals, "buy"],
                        "SEMS Total Import",
                        SensorDeviceClass.ENERGY,
                        UnitOfEnergy.KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                    SemsSensorType(
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
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    #
    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    #
    await coordinator.async_config_entry_first_refresh()

    # _LOGGER.debug("Initial coordinator data: %s", coordinator.data)

    # TODO check new power id, also migrate from old new power id to current
    for _idx, ent in enumerate(coordinator.data.inverters):
        _migrate_to_new_unique_id(hass, ent)

    has_existing_homekit_entity = get_has_existing_homekit_entity(
        coordinator.data.inverters, hass, config_entry
    )

    sensor_options: list[SemsSensorType] = sensor_options_for_data(
        coordinator.data, has_existing_homekit_entity
    )
    sensors: list[SemsSensor] = []
    for sensor_option in sensor_options:
        sensors.append(
            SemsSensor(
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
        )
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
    #     # Don't make SemsStatisticsSensor for homeKit, since it is not an inverter; unsure how this could work before...
    #     if ent != "homeKit"
    # )
    # async_add_entities(
    #     SemsPowerflowSensor(coordinator, ent)
    #     for idx, ent in enumerate(coordinator.data)
    #     if ent == "homeKit"
    # )
    # async_add_entities(
    #     SemsTotalImportSensor(coordinator, ent)
    #     for idx, ent in enumerate(coordinator.data)
    #     if ent == "homeKit"
    # )
    # async_add_entities(
    #     SemsTotalExportSensor(coordinator, ent)
    #     for idx, ent in enumerate(coordinator.data)
    #     if ent == "homeKit"
    # )


# Migrate old power sensor unique ids to new unique ids (with `-power`)
def _migrate_to_new_unique_id(hass: HomeAssistant, sn: str) -> None:
    """Migrate old unique ids to new unique ids."""
    ent_reg = entity_registry.async_get(hass)

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


def get_value_from_path(data, path) -> dict | None:
    """Get value from a nested dictionary."""
    value = data
    try:
        for key in path:
            value = value[key]
    except KeyError:
        return None
    return value


class SemsSensor(CoordinatorEntity[SemsDataUpdateCoordinator], SensorEntity):
    """Representation of a GoodWe SEMS sensor backed by the shared coordinator."""

    str_clean_regex = re.compile(r"(\d+\.?\d*)")

    def __init__(
        self,
        coordinator: SemsDataUpdateCoordinator,
        device_info: DeviceInfo,
        unique_id: str,
        name: str | None,
        value_path: list[str],
        data_type_converter: Callable,
        device_class: SensorDeviceClass | None = None,
        native_unit_of_measurement: str | None = None,
        state_class: SensorStateClass | None = None,
        empty_value=None,
        custom_value_handler=None,
    ):
        super().__init__(coordinator)
        self._value_path = value_path
        self._data_type_converter = data_type_converter
        self._empty_value = empty_value
        self._attr_unique_id = unique_id
        # If name is None, the entity name will be generated from the device class and unit
        # (e.g., "Inverter 123456 Power"); otherwise, use the explicit name provided.
        if name is None:
            # Sensor has name determined by device class (e.g. Inverter 123456 Power)
            self._attr_has_entity_name = True
        else:
            self._attr_name = name
        self._attr_native_unit_of_measurement = native_unit_of_measurement
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_device_info = device_info
        self._custom_value_handler = custom_value_handler

        raw_value = self._get_native_value_from_coordinator()
        self._attr_available = raw_value is not None

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
            # self.coordinator.data,
        )

    def _get_native_value_from_coordinator(self):
        return get_value_from_path(self.coordinator.data.inverters, self._value_path)

    @property
    def native_value(self):
        """Return the state of the device."""
        value = self._get_native_value_from_coordinator()
        # _LOGGER.debug(
        #     "SemsSensor `%s` raw value from coordinator: `%s`",
        #     self._attr_unique_id,
        #     value,
        # )
        if isinstance(value, str):
            value = self.str_clean_regex.search(value).group(1)
        if self._empty_value is not None and self._empty_value == value:
            return None
        if value is None:
            return value
        # _LOGGER.debug(
        #     "SemsSensor `%s`, applying type converter: `%s`",
        #     self._attr_unique_id,
        #     self._data_type_converter,
        # )
        # removed typed value
        # typed_value = self._data_type_converter(value)
        # _LOGGER.debug(
        #     "SemsSensor `%s` value %s `%s` -> typed value: `%s`",
        #     self._attr_unique_id,
        #     type(value).__name__,
        #     value,
        #     typed_value,
        # )
        if self._custom_value_handler is not None:
            return self._custom_value_handler(value, self.coordinator.data)
        return value

    # @property
    # def suggested_display_precision(self):
    #     """Return the suggested number of decimal digits for display."""
    #     return 2


# class SemsSensor(CoordinatorEntity, SensorEntity):
#     """SemsSensor using CoordinatorEntity.

#     The CoordinatorEntity class provides:
#       should_poll
#       async_update
#       async_added_to_hass
#       available
#     """

#     # Sensor has name determined by device class (e.g. Inverter 123456 Power)
#     _attr_has_entity_name = True

#     def __init__(self, coordinator, sn) -> None:
#         """Pass coordinator to CoordinatorEntity."""
#         super().__init__(coordinator)
#         self.coordinator = coordinator
#         self.sn = sn
#         self._attr_unique_id = f"{self.coordinator.data[self.sn]['sn']}-power"
#         _LOGGER.debug("Creating SemsSensor with id %s", self.sn)
#         self._attr_unique_id = f"{self.coordinator.data[self.sn]['sn']}-power"
#         _LOGGER.debug(
#             "Creating SemsSensor with id %s and data %s",
#             self.sn,
#             self.coordinator.data[self.sn],
#         )

#     _attr_device_class = SensorDeviceClass.POWER
#     _attr_native_unit_of_measurement = UnitOfPower.WATT
#     _attr_should_poll = False

#     @property
#     def native_value(self):
#         """Return the value reported by the sensor."""
#         data = self.coordinator.data[self.sn]
#         return data["pac"] if data["status"] == 1 else 0

#     def _statusText(self, status) -> str:
#         labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
#         return labels.get(status, "Unknown")

#     # For backwards compatibility
#     @property
#     def extra_state_attributes(self):
#         """Return the state attributes of the monitored installation."""
#         data = self.coordinator.data[self.sn]
#         attributes = {k: v for k, v in data.items() if k is not None and v is not None}
#         attributes["statusText"] = self._statusText(data["status"])
#         return attributes

#     @property
#     def is_on(self) -> bool:
#         """Return entity status."""
#         return self.coordinator.data[self.sn]["status"] == 1

#     @property
#     def available(self):
#         """Return if entity is available."""
#         return self.coordinator.last_update_success

#     @property
#     def device_info(self) -> DeviceInfo:
#         """Return device information."""
#         return DeviceInfo(
#             identifiers={(DOMAIN, self.sn)},
#             name=f"Inverter {self.coordinator.data[self.sn]['name']}",
#             manufacturer="GoodWe",
#             model=self.extra_state_attributes.get("model_type", "unknown"),
#             sw_version=self.extra_state_attributes.get("firmwareversion", "unknown"),
#             configuration_url=f"https://semsportal.com/PowerStation/PowerStatusSnMin/{self.coordinator.data[self.sn]['powerstation_id']}",
#         )

#     async def async_added_to_hass(self):
#         """When entity is added to hass."""
#         self.async_on_remove(
#             self.coordinator.async_add_listener(self.async_write_ha_state)
#         )

#     async def async_update(self):
#         """Update the entity.

#         Only used by the generic entity update service.
#         """
#         await self.coordinator.async_request_refresh()


# class SemsStatisticsSensor(CoordinatorEntity, SensorEntity):
#     """Sensor in kWh to enable HA statistics, in the end usable in the power component."""

#     _attr_has_entity_name = True

#     def __init__(self, coordinator, sn) -> None:
#         """Pass coordinator to CoordinatorEntity."""
#         super().__init__(coordinator)
#         self.coordinator = coordinator
#         self.sn = sn
#         _LOGGER.debug("Creating SemsStatisticsSensor with id %s", self.sn)
#         _LOGGER.debug(
#             "Creating SemsSensor with id %s and data %s",
#             self.sn,
#             self.coordinator.data[self.sn],
#         )

#     @property
#     def device_class(self):
#         return SensorDeviceClass.ENERGY

#     @property
#     def unit_of_measurement(self):
#         return UnitOfEnergy.KILO_WATT_HOUR

#     # @property
#     # def name(self) -> str:
#     #     """Return the name of the sensor."""
#     #     return f"Inverter {self.coordinator.data[self.sn]['name']} Energy"

#     @property
#     def unique_id(self) -> str:
#         return f"{self.coordinator.data[self.sn]['sn']}-energy"

#     @property
#     def state(self):
#         """Return the state of the device."""
#         _LOGGER.debug(
#             "SemsStatisticsSensor state, coordinator data: %s", self.coordinator.data
#         )
#         _LOGGER.debug("SemsStatisticsSensor self.sn: %s", self.sn)
#         _LOGGER.debug(
#             "SemsStatisticsSensor state, self data: %s", self.coordinator.data[self.sn]
#         )
#         data = self.coordinator.data[self.sn]
#         return data["etotal"]

#     @property
#     def should_poll(self) -> bool:
#         """No need to poll. Coordinator notifies entity of updates."""
#         return False

#     @property
#     def device_info(self):
#         # _LOGGER.debug("self.device_state_attributes: %s", self.device_state_attributes)
#         data = self.coordinator.data[self.sn]
#         return {
#             "identifiers": {
#                 # Serial numbers are unique identifiers within a specific domain
#                 (DOMAIN, self.sn)
#             },
#             # "name": self.name,
#             "manufacturer": "GoodWe",
#             "model": data.get("model_type", "unknown"),
#             "sw_version": data.get("firmwareversion", "unknown"),
#             # "via_device": (DOMAIN, self.api.bridgeid),
#         }

#     @property
#     def state_class(self):
#         """used by Metered entities / Long Term Statistics"""
#         return SensorStateClass.TOTAL_INCREASING

#     async def async_added_to_hass(self):
#         """When entity is added to hass."""
#         self.async_on_remove(
#             self.coordinator.async_add_listener(self.async_write_ha_state)
#         )

#     async def async_update(self):
#         """Update the entity.

#         Only used by the generic entity update service.
#         """
#         await self.coordinator.async_request_refresh()


# class SemsTotalImportSensor(CoordinatorEntity, SensorEntity):
#     """Sensor in kWh to enable HA statistics, in the end usable in the power component."""

#     _attr_has_entity_name = True

#     def __init__(self, coordinator, sn):
#         """Pass coordinator to CoordinatorEntity."""
#         super().__init__(coordinator)
#         self.coordinator = coordinator
#         self.sn = sn
#         _LOGGER.debug("Creating SemsStatisticsSensor with id %s", self.sn)

#     @property
#     def device_class(self):
#         return SensorDeviceClass.ENERGY

#     @property
#     def unit_of_measurement(self):
#         return UnitOfEnergy.KILO_WATT_HOUR

#     @property
#     def name(self) -> str:
#         """Return the name of the sensor."""
#         return "HomeKit Import"

#     @property
#     def unique_id(self) -> str:
#         return f"{self.coordinator.data[self.sn]['sn']}-import-energy"

#     @property
#     def state(self):
#         """Return the state of the device."""
#         data = self.coordinator.data[self.sn]
#         return data["Charts_buy"]

#     def statusText(self, status) -> str:
#         labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
#         return labels[status] if status in labels else "Unknown"

#     @property
#     def should_poll(self) -> bool:
#         """No need to poll. Coordinator notifies entity of updates."""
#         return False

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

#     @property
#     def state_class(self):
#         """used by Metered entities / Long Term Statistics"""
#         return SensorStateClass.TOTAL_INCREASING

#     async def async_added_to_hass(self):
#         """When entity is added to hass."""
#         self.async_on_remove(
#             self.coordinator.async_add_listener(self.async_write_ha_state)
#         )

#     async def async_update(self):
#         """Update the entity.

#         Only used by the generic entity update service.
#         """
#         await self.coordinator.async_request_refresh()


# class SemsTotalExportSensor(CoordinatorEntity, SensorEntity):
#     """Sensor in kWh to enable HA statistics, in the end usable in the power component."""

#     _attr_has_entity_name = True

#     def __init__(self, coordinator, sn):
#         """Pass coordinator to CoordinatorEntity."""
#         super().__init__(coordinator)
#         self.coordinator = coordinator
#         self.sn = sn
#         _LOGGER.debug("Creating SemsStatisticsSensor with id %s", self.sn)

#     @property
#     def device_class(self):
#         return SensorDeviceClass.ENERGY

#     @property
#     def unit_of_measurement(self):
#         return UnitOfEnergy.KILO_WATT_HOUR

#     @property
#     def name(self) -> str:
#         """Return the name of the sensor."""
#         return "HomeKit Export"

#     @property
#     def unique_id(self) -> str:
#         return f"{self.coordinator.data[self.sn]['sn']}-export-energy"

#     @property
#     def state(self):
#         """Return the state of the device."""
#         data = self.coordinator.data[self.sn]
#         return data["Charts_sell"]

#     def statusText(self, status) -> str:
#         labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
#         return labels[status] if status in labels else "Unknown"

#     @property
#     def should_poll(self) -> bool:
#         """No need to poll. Coordinator notifies entity of updates."""
#         return False

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

#     @property
#     def state_class(self):
#         """used by Metered entities / Long Term Statistics"""
#         return SensorStateClass.TOTAL_INCREASING

#     async def async_added_to_hass(self):
#         """When entity is added to hass."""
#         self.async_on_remove(
#             self.coordinator.async_add_listener(self.async_write_ha_state)
#         )

#     async def async_update(self):
#         """Update the entity.

#         Only used by the generic entity update service.
#         """
#         await self.coordinator.async_request_refresh()


# class SemsPowerflowSensor(CoordinatorEntity, SensorEntity):
#     """SemsPowerflowSensor using CoordinatorEntity.

#     The CoordinatorEntity class provides:
#       should_poll
#       async_update
#       async_added_to_hass
#       available
#     """

#     _attr_has_entity_name = True

#     def __init__(self, coordinator, sn):
#         """Pass coordinator to CoordinatorEntity."""
#         super().__init__(coordinator)
#         self.coordinator = coordinator
#         self.sn = sn

#     @property
#     def device_class(self):
#         return SensorDeviceClass.POWER_FACTOR

#     @property
#     def unit_of_measurement(self):
#         return UnitOfPower.WATT

#     @property
#     def name(self) -> str:
#         """Return the name of the sensor."""
#         return f"HomeKit {self.coordinator.data[self.sn]['sn']}"

#     @property
#     def unique_id(self) -> str:
#         return f"{self.coordinator.data[self.sn]['sn']}-homekit"

#     @property
#     def state(self):
#         """Return the state of the device."""
#         data = self.coordinator.data[self.sn]
#         load = data["load"]

#         if load:
#             load = load.replace("(W)", "")

#         return load if data["gridStatus"] == 1 else 0

#     def statusText(self, status) -> str:
#         labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
#         return labels[status] if status in labels else "Unknown"

#     # For backwards compatibility
#     @property
#     def extra_state_attributes(self):
#         """Return the state attributes of the monitored installation."""
#         data = self.coordinator.data[self.sn]

#         attributes = {k: v for k, v in data.items() if k is not None and v is not None}

#         attributes["pv"] = data["pv"].replace("(W)", "")
#         attributes["bettery"] = data["bettery"].replace("(W)", "")
#         attributes["load"] = data["load"].replace("(W)", "")
#         attributes["grid"] = data["grid"].replace("(W)", "")

#         attributes["statusText"] = self.statusText(data["gridStatus"])

#         if data["loadStatus"] == -1:
#             attributes["PowerFlowDirection"] = "Export %s" % data["grid"]
#         if data["loadStatus"] == 1:
#             attributes["PowerFlowDirection"] = "Import %s" % data["grid"]

#         return attributes

#     @property
#     def is_on(self) -> bool:
#         """Return entity status."""
#         self.coordinator.data[self.sn]["gridStatus"] == 1

#     @property
#     def should_poll(self) -> bool:
#         """No need to poll. Coordinator notifies entity of updates."""
#         return False

#     @property
#     def available(self):
#         """Return if entity is available."""
#         return self.coordinator.last_update_success

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

#     async def async_added_to_hass(self):
#         """When entity is added to hass."""
#         self.async_on_remove(
#             self.coordinator.async_add_listener(self.async_write_ha_state)
#         )

#     async def async_update(self):
#         """Update the entity.

#         Only used by the generic entity update service.
#         """
#         await self.coordinator.async_request_refresh()

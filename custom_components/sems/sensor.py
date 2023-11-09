"""
Support for power production statistics from GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import List, Callable, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    POWER_WATT,
    CONF_SCAN_INTERVAL,
    ENERGY_KILO_WATT_HOUR,
    TEMP_CELSIUS,
    ELECTRIC_POTENTIAL_VOLT,
    ELECTRIC_CURRENT_AMPERE,
    FREQUENCY_HERTZ,
    PERCENTAGE,
    POWER_KILO_WATT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
    API_UPDATE_ERROR_MSG,
    GOODWE_SPELLING,
    AC_EMPTY,
    AC_CURRENT_EMPTY,
    AC_FEQ_EMPTY,
)

_LOGGER = logging.getLogger(__name__)


def get_value_from_path(data, path):
    """
    Get value from a nested dictionary.
    """
    value = data
    try:
        for key in path:
            value = value[key]
    except KeyError:
        return None
    return value


class Sensor(CoordinatorEntity, SensorEntity):
    str_clean_regex = re.compile(r"(\d+\.?\d*)")

    def __init__(
        self,
        coordinator,
        device_info: DeviceInfo,
        unique_id: str,
        name: str,
        value_path: List[str],
        data_type_converter: Callable,
        device_class: Optional[SensorDeviceClass] = None,
        native_unit_of_measurement: Optional[str] = None,
        state_class: Optional[SensorStateClass] = None,
        empty_value=None,
    ):
        super().__init__(coordinator)
        self._value_path = value_path
        self._data_type_converter = data_type_converter
        self._empty_value = empty_value

        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_native_unit_of_measurement = native_unit_of_measurement
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_device_info = device_info

    def _get_native_value_from_coordinator(self):
        return get_value_from_path(self.coordinator.data, self._value_path)

    @property
    def native_value(self):
        """Return the state of the device."""
        value = get_value_from_path(self.coordinator.data, self._value_path)
        if isinstance(value, str):
            value = self.str_clean_regex.search(value).group(1)
        if self._empty_value is not None and self._empty_value == value:
            value = 0
        typed_value = self._data_type_converter(value)
        return typed_value

    @property
    def suggested_display_precision(self):
        return 2


class SensorOptions:
    def __init__(
        self,
        device_info: DeviceInfo,
        unique_id: str,
        name: str,
        value_path: List[str],
        device_class: Optional[SensorDeviceClass] = None,
        native_unit_of_measurement: Optional[str] = None,
        state_class: Optional[SensorStateClass] = None,
        empty_value=None,
        data_type_converter=Decimal,
    ):
        self.device_info = device_info
        self.unique_id = unique_id
        self.name = name
        self.value_path = value_path
        self.device_class = device_class
        self.native_unit_of_measurement = native_unit_of_measurement
        self.state_class = state_class
        self.empty_value = empty_value
        self.data_type_converter = data_type_converter

    def __str__(self):
        return f"SensorOptions(device_info={self.device_info}, unique_id={self.unique_id}, name={self.name}, value_path={self.value_path}, device_class={self.device_class}, native_unit_of_measurement={self.native_unit_of_measurement}, state_class={self.state_class}, empty_value={self.empty_value}, data_type_converter={self.data_type_converter})"


def sensor_options_for_data(data) -> List[SensorOptions]:
    sensors: List[SensorOptions] = []
    try:
        currency = data["kpi"]["currency"]
    except KeyError:
        currency = None

    for idx, inverter in enumerate(data["inverter"]):
        serial_number = inverter["sn"]
        path_to_inverter = ["inverter", idx, "invert_full"]
        name = inverter.get("name", "unknown")
        device_data = get_value_from_path(data, path_to_inverter)
        device_info = DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, serial_number)
            },
            name=f"Inverter {name}",
            manufacturer="GoodWe",
            model=device_data.get("model_type", "unknown"),
            sw_version=device_data.get("firmwareversion", "unknown"),
        )
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}-capacity",
                f"Inverter {inverter['name']} Capacity",
                path_to_inverter + ["capacity"],
                SensorDeviceClass.POWER,
                POWER_KILO_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                serial_number,  # backwards compatibility otherwise would be f"{serial_number}-power"
                f"Inverter {inverter['name']} Power",
                path_to_inverter + ["pac"],
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-energy",
                f"Inverter {inverter['name']} Energy",
                path_to_inverter + ["etotal"],
                SensorDeviceClass.ENERGY,
                ENERGY_KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-hour-total",
                f"Inverter {inverter['name']} Total Hours",
                path_to_inverter + ["hour_total"],
                state_class=SensorStateClass.TOTAL_INCREASING,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-temperature",
                f"Inverter {inverter['name']} Temperature",
                path_to_inverter + [GOODWE_SPELLING.temperature],
                SensorDeviceClass.TEMPERATURE,
                TEMP_CELSIUS,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-eday ",
                f"Inverter {inverter['name']} Energy Today",
                path_to_inverter + ["eday"],
                SensorDeviceClass.ENERGY,
                ENERGY_KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-{GOODWE_SPELLING.thisMonthTotalE}",
                f"Inverter {inverter['name']} Energy This Month",
                path_to_inverter + [GOODWE_SPELLING.thisMonthTotalE],
                SensorDeviceClass.ENERGY,
                ENERGY_KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-{GOODWE_SPELLING.lastMonthTotalE}",
                f"Inverter {inverter['name']} Energy Last Month",
                path_to_inverter + [GOODWE_SPELLING.lastMonthTotalE],
                SensorDeviceClass.ENERGY,
                ENERGY_KILO_WATT_HOUR,
                SensorStateClass.TOTAL_INCREASING,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-iday",
                f"Inverter {inverter['name']} Income Today",
                path_to_inverter + ["iday"],
                SensorDeviceClass.MONETARY,
                currency,
                SensorStateClass.TOTAL,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-itotal",
                f"Inverter {inverter['name']} Income Total",
                path_to_inverter + ["itotal"],
                SensorDeviceClass.MONETARY,
                currency,
                SensorStateClass.TOTAL,
            ),
        ]
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}-vpv{idx}",
                f"Inverter {inverter['name']} PV String {idx} Voltage",
                path_to_inverter + [f"vpv{idx}"],
                SensorDeviceClass.VOLTAGE,
                ELECTRIC_POTENTIAL_VOLT,
                SensorStateClass.MEASUREMENT,
            )
            for idx in range(1, 5)
            if get_value_from_path(data, path_to_inverter + [f"vpv{idx}"]) is not None
        ]
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}-ipv{idx}",
                f"Inverter {inverter['name']} PV String {idx} Current",
                path_to_inverter + [f"ipv{idx}"],
                SensorDeviceClass.CURRENT,
                ELECTRIC_CURRENT_AMPERE,
                SensorStateClass.MEASUREMENT,
            )
            for idx in range(1, 5)
            if get_value_from_path(data, path_to_inverter + [f"ipv{idx}"]) is not None
        ]
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}-vac{idx}",
                f"Inverter {inverter['name']} Grid {idx} AC Voltage",
                path_to_inverter + [f"vac{idx}"],
                SensorDeviceClass.VOLTAGE,
                ELECTRIC_POTENTIAL_VOLT,
                SensorStateClass.MEASUREMENT,
                AC_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}-iac{idx}",
                f"Inverter {inverter['name']} Grid {idx} AC Current",
                path_to_inverter + [f"iac{idx}"],
                SensorDeviceClass.CURRENT,
                ELECTRIC_CURRENT_AMPERE,
                SensorStateClass.MEASUREMENT,
                AC_CURRENT_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}-fac{idx}",
                f"Inverter {inverter['name']} Grid {idx} AC Frequency",
                path_to_inverter + [f"fac{idx}"],
                SensorDeviceClass.FREQUENCY,
                FREQUENCY_HERTZ,
                SensorStateClass.MEASUREMENT,
                AC_FEQ_EMPTY,
            )
            for idx in range(1, 4)
        ]
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}-vbattery1",
                f"Inverter {inverter['name']} Battery Voltage",
                path_to_inverter + ["vbattery1"],
                SensorDeviceClass.VOLTAGE,
                ELECTRIC_POTENTIAL_VOLT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-ibattery1",
                f"Inverter {inverter['name']} Battery Current",
                path_to_inverter + ["ibattery1"],
                SensorDeviceClass.CURRENT,
                ELECTRIC_CURRENT_AMPERE,
                SensorStateClass.MEASUREMENT,
            ),
        ]
        battery_count = get_value_from_path(data, path_to_inverter + ["battery_count"])
        if battery_count is not None:
            for idx in range(0, battery_count):
                path_to_battery = path_to_inverter + ["more_batterys", idx]
                sensors += [
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-pbattery",
                        f"Inverter {inverter['name']} Battery {idx} Power",
                        path_to_battery + ["pbattery"],
                        SensorDeviceClass.POWER,
                        POWER_WATT,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-vbattery",
                        f"Inverter {inverter['name']} Battery {idx} Voltage",
                        path_to_battery + ["vbattery"],
                        SensorDeviceClass.VOLTAGE,
                        ELECTRIC_POTENTIAL_VOLT,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-ibattery",
                        f"Inverter {inverter['name']} Battery {idx} Current",
                        path_to_battery + ["ibattery"],
                        SensorDeviceClass.CURRENT,
                        ELECTRIC_CURRENT_AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-soc",
                        f"Inverter {inverter['name']} Battery {idx} State of Charge",
                        path_to_battery + ["soc"],
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-soh",
                        f"Inverter {inverter['name']} Battery {idx} State of Health",
                        path_to_battery + ["soh"],
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-bms_temperature",
                        f"Inverter {inverter['name']} Battery {idx} BMS Temperature",
                        path_to_battery + ["bms_temperature"],
                        SensorDeviceClass.TEMPERATURE,
                        TEMP_CELSIUS,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-bms_discharge_i_max",
                        f"Inverter {inverter['name']} Battery {idx} BMS Discharge Max Current",
                        path_to_battery + ["bms_discharge_i_max"],
                        SensorDeviceClass.CURRENT,
                        ELECTRIC_CURRENT_AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-{idx}-bms_charge_i_max",
                        f"Inverter {inverter['name']} Battery {idx} BMS Charge Max Current",
                        path_to_battery + ["bms_charge_i_max"],
                        SensorDeviceClass.CURRENT,
                        ELECTRIC_CURRENT_AMPERE,
                        SensorStateClass.MEASUREMENT,
                    ),
                ]

    if "hasPowerflow" in data and data["hasPowerflow"] and "powerflow" in data:
        serial_number = "powerflow"
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
        sensors += [
            SensorOptions(
                device_info,
                f"{serial_number}",  # backwards compatibility otherwise would be f"{serial_number}-load"
                f"HomeKit Load",
                ["powerflow", "load"],
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-pv",
                f"HomeKit PV",
                ["powerflow", "pv"],
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-grid",
                f"HomeKit Grid",
                ["powerflow", "grid"],
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-battery",
                f"HomeKit Battery",
                ["powerflow", GOODWE_SPELLING.battery],
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-genset",
                f"HomeKit generator",
                ["powerflow", "genset"],
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            SensorOptions(
                device_info,
                f"{serial_number}-soc",
                f"HomeKit State of Charge",
                ["powerflow", "soc"],
                SensorDeviceClass.BATTERY,
                PERCENTAGE,
                SensorStateClass.MEASUREMENT,
            ),
        ]
        if (
            GOODWE_SPELLING.hasEnergyStatisticsCharts in data
            and data[GOODWE_SPELLING.hasEnergyStatisticsCharts]
        ):
            if data[GOODWE_SPELLING.energyStatisticsCharts]:
                sensors += [
                    SensorOptions(
                        device_info,
                        f"{serial_number}-import-energy",
                        f"Sems Import",
                        [GOODWE_SPELLING.energyStatisticsCharts, "buy"],
                        SensorDeviceClass.ENERGY,
                        ENERGY_KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-export-energy",
                        f"Sems Export",
                        [GOODWE_SPELLING.energyStatisticsCharts, "sell"],
                        SensorDeviceClass.ENERGY,
                        ENERGY_KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                ]
            if data[GOODWE_SPELLING.energyStatisticsTotals]:
                sensors += [
                    SensorOptions(
                        device_info,
                        f"{serial_number}-import-energy-total",
                        f"Sems Total Import",
                        [GOODWE_SPELLING.energyStatisticsTotals, "buy"],
                        SensorDeviceClass.ENERGY,
                        ENERGY_KILO_WATT_HOUR,
                        SensorStateClass.TOTAL_INCREASING,
                    ),
                    SensorOptions(
                        device_info,
                        f"{serial_number}-export-energy-total",
                        f"Sems Total Export",
                        [GOODWE_SPELLING.energyStatisticsTotals, "sell"],
                        SensorDeviceClass.ENERGY,
                        ENERGY_KILO_WATT_HOUR,
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
    semsApi = hass.data[DOMAIN][config_entry.entry_id]
    stationId = config_entry.data[CONF_STATION_ID]

    update_interval = timedelta(
        seconds=config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    async def async_update_data():
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            # async with async_timeout.timeout(10):
            result = await hass.async_add_executor_job(semsApi.getData, stationId)
            _LOGGER.debug("Resulting result: %s", result)

            if "inverter" not in result:
                raise UpdateFailed(API_UPDATE_ERROR_MSG)
            inverters = result["inverter"]
            if inverters is None:
                raise UpdateFailed(API_UPDATE_ERROR_MSG)
            return result
        # except ApiError as err:
        except Exception as err:
            # logging.exception("Something awful happened!")
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        # Name of the data. For logging purposes.
        name="SEMS API",
        update_method=async_update_data,
        # Polling interval. Will only be polled if there are subscribers.
        update_interval=update_interval,
    )

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

    data = coordinator.data

    sensor_options: List[SensorOptions] = sensor_options_for_data(data)
    sensors: List[Sensor] = []
    for sensor_option in sensor_options:
        sensors.append(
            Sensor(
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
            )
        )
    async_add_entities(sensors)

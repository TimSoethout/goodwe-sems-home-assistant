"""
Support for power production statistics from GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import List, Callable

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    POWER_WATT,
    CONF_SCAN_INTERVAL,
    ENERGY_KILO_WATT_HOUR, TEMP_CELSIUS, ELECTRIC_POTENTIAL_VOLT, ELECTRIC_CURRENT_AMPERE, FREQUENCY_HERTZ, PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, CONF_STATION_ID, DEFAULT_SCAN_INTERVAL, API_UPDATE_ERROR_MSG, GOODWE_SPELLING, AC_EMPTY, \
    AC_CURRENT_EMPTY, AC_FEQ_EMPTY

_LOGGER = logging.getLogger(__name__)


def get_value_from_path(data, path):
    value = data
    for key in path:
        value = value[key]
    return value


class Sensor(CoordinatorEntity, SensorEntity):
    str_clean_regex = re.compile(r"(\d+\.?\d*)")

    def __init__(self, coordinator, device_info: DeviceInfo, serial_number, unique_id: str, name: str,
                 value_path: List[str], data_type_converter: Callable, device_class: SensorDeviceClass,
                 native_unit_of_measurement: str, state_class: SensorStateClass, empty_value=None):
        super().__init__(coordinator)
        self._sn = serial_number
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

    try:
        currency = data['kpi']['currency']
    except KeyError:
        currency = None

    cloud_id = "sems"
    device_info = DeviceInfo(
        identifiers={
            # Serial numbers are unique identifiers within a specific domain
            (DOMAIN, cloud_id)
        },
        name="SEMS Cloud",
        manufacturer="GoodWe",
    )

    for idx, inverter in enumerate(data["inverter"]):
        serial_number = inverter['sn']
        path_to_inverter = ["inverter", idx, "invert_full"]
        name = inverter.get('name', 'unknown')
        device_data = get_value_from_path(coordinator.data, path_to_inverter)
        device_info = DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, serial_number)
            },
            name=name,
            manufacturer="GoodWe",
            model=device_data.get("model_type", "unknown"),
            sw_version=device_data.get("firmwareversion", "unknown"),
        )
        async_add_entities([
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-capacity",
                                   f"Inverter {inverter['name']} Capacity",
                                   path_to_inverter + ["capacity"],
                                   Decimal,
                                   SensorDeviceClass.POWER,
                                   ENERGY_KILO_WATT_HOUR,
                                   SensorStateClass.MEASUREMENT
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   serial_number,
                                   # should be {serial_number}-pac but is serial_number for backwards compatibility
                                   f"Inverter {inverter['name']} Power",
                                   path_to_inverter + ["pac"],
                                   Decimal,
                                   SensorDeviceClass.POWER,
                                   POWER_WATT,
                                   SensorStateClass.MEASUREMENT
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-energy",
                                   # should be {serial_number}-etotal but is {serial_number}-energy for backwards compatibility
                                   f"Inverter {inverter['name']} Energy",
                                   path_to_inverter + ["etotal"],
                                   Decimal,
                                   SensorDeviceClass.ENERGY,
                                   ENERGY_KILO_WATT_HOUR,
                                   SensorStateClass.TOTAL_INCREASING
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-temperature",
                                   f"Inverter {inverter['name']} Temperature",
                                   path_to_inverter + [GOODWE_SPELLING.temperature],
                                   Decimal,
                                   SensorDeviceClass.TEMPERATURE,
                                   TEMP_CELSIUS,
                                   SensorStateClass.MEASUREMENT
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-eday ",
                                   f"Inverter {inverter['name']} Energy Today",
                                   path_to_inverter + ["eday"],
                                   Decimal,
                                   SensorDeviceClass.ENERGY,
                                   ENERGY_KILO_WATT_HOUR,
                                   SensorStateClass.TOTAL_INCREASING
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-{GOODWE_SPELLING.thisMonthTotalE}",
                                   f"Inverter {inverter['name']} Energy This Month",
                                   path_to_inverter + [GOODWE_SPELLING.thisMonthTotalE],
                                   Decimal,
                                   SensorDeviceClass.ENERGY,
                                   ENERGY_KILO_WATT_HOUR,
                                   SensorStateClass.TOTAL_INCREASING
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-{GOODWE_SPELLING.lastMonthTotalE}",
                                   f"Inverter {inverter['name']} Energy Last Month",
                                   path_to_inverter + [GOODWE_SPELLING.lastMonthTotalE],
                                   Decimal,
                                   SensorDeviceClass.ENERGY,
                                   ENERGY_KILO_WATT_HOUR,
                                   SensorStateClass.TOTAL_INCREASING
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-iday",
                                   f"Inverter {inverter['name']} Income Today",
                                   path_to_inverter + ["iday"],
                                   Decimal,
                                   SensorDeviceClass.MONETARY,
                                   currency,
                                   SensorStateClass.TOTAL_INCREASING,
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-itotal",
                                   f"Inverter {inverter['name']} Income Total",
                                   path_to_inverter + ["itotal"],
                                   Decimal,
                                   SensorDeviceClass.MONETARY,
                                   currency,
                                   SensorStateClass.TOTAL_INCREASING,
                               ),
                           ] + [
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-vpv{idx}",
                                   f"Inverter {inverter['name']} PV String {idx} Voltage",
                                   path_to_inverter + [f"vpv{idx}"],
                                   Decimal,
                                   SensorDeviceClass.VOLTAGE,
                                   ELECTRIC_POTENTIAL_VOLT,
                                   SensorStateClass.MEASUREMENT
                               ) for idx in range(1, 5)
                           ] + [
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-ipv{idx}",
                                   f"Inverter {inverter['name']} PV String {idx} Current",
                                   path_to_inverter + [f"ipv{idx}"],
                                   Decimal,
                                   SensorDeviceClass.CURRENT,
                                   ELECTRIC_CURRENT_AMPERE,
                                   SensorStateClass.MEASUREMENT
                               ) for idx in range(1, 5)
                           ] + [
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-vac{idx}",
                                   f"Inverter {inverter['name']} {idx} AC Voltage",
                                   path_to_inverter + [f"vac{idx}"],
                                   Decimal,
                                   SensorDeviceClass.VOLTAGE,
                                   ELECTRIC_POTENTIAL_VOLT,
                                   SensorStateClass.MEASUREMENT,
                                   AC_EMPTY
                               ) for idx in range(1, 4)
                           ] + [
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-iac{idx}",
                                   f"Inverter {inverter['name']} Grid {idx} AC Current",
                                   path_to_inverter + [f"iac{idx}"],
                                   Decimal,
                                   SensorDeviceClass.CURRENT,
                                   ELECTRIC_CURRENT_AMPERE,
                                   SensorStateClass.MEASUREMENT,
                                   AC_CURRENT_EMPTY
                               ) for idx in range(1, 4)
                           ] + [
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-fac{idx}",
                                   f"Inverter {inverter['name']} Grid {idx} AC Frequency",
                                   path_to_inverter + [f"fac{idx}"],
                                   Decimal,
                                   SensorDeviceClass.FREQUENCY,
                                   FREQUENCY_HERTZ,
                                   SensorStateClass.MEASUREMENT,
                                   AC_FEQ_EMPTY
                               ) for idx in range(1, 4)
                           ] + [
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-vbattery1",
                                   f"Inverter {inverter['name']} Battery Voltage",
                                   path_to_inverter + ["vbattery1"],
                                   Decimal,
                                   SensorDeviceClass.VOLTAGE,
                                   ELECTRIC_POTENTIAL_VOLT,
                                   SensorStateClass.MEASUREMENT
                               ),
                               Sensor(
                                   coordinator,
                                   device_info,
                                   serial_number,
                                   f"{serial_number}-ibattery1",
                                   f"Inverter {inverter['name']} Battery Current",
                                   path_to_inverter + ["ibattery1"],
                                   Decimal,
                                   SensorDeviceClass.CURRENT,
                                   ELECTRIC_CURRENT_AMPERE,
                                   SensorStateClass.MEASUREMENT
                               ),
                           ])

    if "hasPowerflow" in data and data["hasPowerflow"] and 'powerflow' in data:
        serial_number = data[GOODWE_SPELLING.homeKit]["sn"]
        async_add_entities([
            Sensor(
                coordinator,
                device_info,
                serial_number,
                f"{serial_number}",  # should be {serial_number}-load but is {serial_number} for backwards compatibility
                f"HomeKit Load",
                ["powerflow", "load"],
                Decimal,
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT
            ),
            Sensor(
                coordinator,
                device_info,
                serial_number,
                f"{serial_number}-pv",
                f"HomeKit PV",
                ["powerflow", "pv"],
                Decimal,
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT
            ),
            Sensor(
                coordinator,
                device_info,
                serial_number,
                f"{serial_number}-grid",
                f"HomeKit Grid",
                ["powerflow", "grid"],
                Decimal,
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT
            ),
            Sensor(
                coordinator,
                device_info,
                serial_number,
                f"{serial_number}-battery",
                f"HomeKit Battery",
                ["powerflow" + GOODWE_SPELLING.battery],
                Decimal,
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT,
            ),
            Sensor(
                coordinator,
                device_info,
                serial_number,
                f"{serial_number}-genset",
                f"HomeKit generator",
                ["powerflow", "genset"],
                Decimal,
                SensorDeviceClass.POWER,
                POWER_WATT,
                SensorStateClass.MEASUREMENT
            ),
            Sensor(
                coordinator,
                device_info,
                serial_number,
                f"{serial_number}-soc",
                f"HomeKit State of Charge",
                ["powerflow", "soc"],
                Decimal,
                SensorDeviceClass.BATTERY,
                PERCENTAGE,
                SensorStateClass.MEASUREMENT,
            ),
        ])
    if GOODWE_SPELLING.hasEnergyStatisticsCharts in data and data[GOODWE_SPELLING.hasEnergyStatisticsCharts]:
        if data[GOODWE_SPELLING.energyStatisticsCharts]:
            async_add_entities([
                Sensor(
                    coordinator,
                    device_info,
                    serial_number,
                    f"{serial_number}-import-energy",
                    # should be {serial_number}-import but is {serial_number}-import-energy for backwards compatibility
                    f"Sems Import",
                    [GOODWE_SPELLING.energyStatisticsCharts, "buy"],
                    Decimal,
                    SensorDeviceClass.ENERGY,
                    ENERGY_KILO_WATT_HOUR,
                    SensorStateClass.TOTAL_INCREASING
                ),
                Sensor(
                    coordinator,
                    device_info,
                    serial_number,
                    f"{serial_number}-export-energy",
                    # should be {serial_number}-export but is {serial_number}-export-energy for backwards compatibility
                    f"Sems Export",
                    [GOODWE_SPELLING.energyStatisticsCharts, "sell"],
                    Decimal,
                    SensorDeviceClass.ENERGY,
                    ENERGY_KILO_WATT_HOUR,
                    SensorStateClass.TOTAL_INCREASING
                ),
            ])
        if data[GOODWE_SPELLING.energyStatisticsTotals]:
            async_add_entities([
                Sensor(
                    coordinator,
                    device_info,
                    serial_number,
                    f"{serial_number}-import-energy-total",
                    f"Sems Total Import",
                    [GOODWE_SPELLING.energyStatisticsTotals, "buy"],
                    Decimal,
                    SensorDeviceClass.ENERGY,
                    ENERGY_KILO_WATT_HOUR,
                    SensorStateClass.TOTAL_INCREASING
                ),
                Sensor(
                    coordinator,
                    device_info,
                    serial_number,
                    f"{serial_number}-export-energy-total",
                    f"Sems Total Export",
                    [GOODWE_SPELLING.energyStatisticsTotals, "sell"],
                    Decimal,
                    SensorDeviceClass.ENERGY,
                    ENERGY_KILO_WATT_HOUR,
                    SensorStateClass.TOTAL_INCREASING
                ),
            ])

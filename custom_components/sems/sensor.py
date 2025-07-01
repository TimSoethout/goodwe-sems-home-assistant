"""Support for power production statistics from GoodWe SEMS API.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

from datetime import timedelta
import logging
# from typing import Coroutine

import homeassistant
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_SCAN_INTERVAL, UnitOfEnergy, UnitOfPower, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_STATION_ID, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    # _LOGGER.debug("hass.data[DOMAIN] %s", hass.data[DOMAIN])
    # semsApi = hass.data[DOMAIN][config_entry.entry_id]
    # stationId = config_entry.data[CONF_STATION_ID]

    # _LOGGER.debug("config_entry %s", config_entry.data)
    # update_interval = timedelta(
    #     seconds=config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    # )

    # async def async_update_data():
    #     """Fetch data from API endpoint.

    #     This is the place to pre-process the data to lookup tables
    #     so entities can quickly look up their data.
    #     """
    #     try:
    #         # Note: asyncio.TimeoutError and aiohttp.ClientError are already
    #         # handled by the data update coordinator.
    #         # async with async_timeout.timeout(10):
    #         result = await hass.async_add_executor_job(semsApi.getData, stationId)
    #         _LOGGER.debug("Resulting result: %s", result)

    #         inverters = result["inverter"]

    #         # found = []
    #         # _LOGGER.debug("Found inverters: %s", inverters)
    #         data = {}
    #         if inverters is None:
    #             # something went wrong, probably token could not be fetched
    #             raise UpdateFailed(
    #                 "Error communicating with API, probably token could not be fetched, see debug logs"
    #             )
    #         for inverter in inverters:
    #             name = inverter["invert_full"]["name"]
    #             # powerstation_id = inverter["invert_full"]["powerstation_id"]
    #             sn = inverter["invert_full"]["sn"]
    #             _LOGGER.debug("Found inverter attribute %s %s", name, sn)
    #             data[sn] = inverter["invert_full"]

    #         hasPowerflow = result["hasPowerflow"]
    #         hasEnergeStatisticsCharts = result["hasEnergeStatisticsCharts"]

    #         if hasPowerflow:
    #             if hasEnergeStatisticsCharts:
    #                 StatisticsCharts = {
    #                     f"Charts_{key}": val
    #                     for key, val in result["energeStatisticsCharts"].items()
    #                 }
    #                 StatisticsTotals = {
    #                     f"Totals_{key}": val
    #                     for key, val in result["energeStatisticsTotals"].items()
    #                 }
    #                 powerflow = {
    #                     **result["powerflow"],
    #                     **StatisticsCharts,
    #                     **StatisticsTotals,
    #                 }
    #             else:
    #                 powerflow = result["powerflow"]

    # powerflow["sn"] = result["homKit"]["sn"]

    # # Goodwe 'Power Meter' (not HomeKit) doesn't have a sn
    # # Let's put something in, otherwise we can't see the data.
    # if powerflow["sn"] is None:
    #     powerflow["sn"] = "GW-HOMEKIT-NO-SERIAL"

    # #_LOGGER.debug("homeKit sn: %s", result["homKit"]["sn"])
    # # This seems more accurate than the Chart_sum
    # powerflow["all_time_generation"] = result["kpi"]["total_power"]

    #             data["homeKit"] = powerflow

    #         # _LOGGER.debug("Resulting data: %s", data)
    #         return data
    #     # except ApiError as err:
    #     except Exception as err:
    #         # logging.exception("Something awful happened!")
    #         raise UpdateFailed(f"Error communicating with API: {err}") from err

    # coordinator = DataUpdateCoordinator(
    #     hass,
    #     _LOGGER,
    #     # Name of the data. For logging purposes.
    #     name="SEMS API",
    #     update_method=async_update_data,
    #     # Polling interval. Will only be polled if there are subscribers.
    #     update_interval=update_interval,
    # )
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

    for _idx, ent in enumerate(coordinator.data):
        _migrate_to_new_unique_id(hass, ent)

    async_add_entities(
        SemsSensor(coordinator, ent)
        for idx, ent in enumerate(coordinator.data)
        # Don't make SemsSensor for homeKit, since it is not an inverter; unsure how this could work before...
        if ent != "homeKit"
    )
    async_add_entities(
        SemsStatisticsSensor(coordinator, ent)
        for idx, ent in enumerate(coordinator.data)
        # Don't make SemsStatisticsSensor for homeKit, since it is not an inverter; unsure how this could work before...
        if ent != "homeKit"
    )
    async_add_entities(
        SemsPowerflowSensor(coordinator, ent)
        for idx, ent in enumerate(coordinator.data)
        if ent == "homeKit"
    )
    async_add_entities(
        SemsTotalImportSensor(coordinator, ent)
        for idx, ent in enumerate(coordinator.data)
        if ent == "homeKit"
    )
    async_add_entities(
        SemsTotalExportSensor(coordinator, ent)
        for idx, ent in enumerate(coordinator.data)
        if ent == "homeKit"
    )


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


class SemsSensor(CoordinatorEntity, SensorEntity):
    """SemsSensor using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available
    """

    # Sensor has name determined by device class (e.g. Inverter 123456 Power)
    _attr_has_entity_name = True

    def __init__(self, coordinator, sn) -> None:
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.sn = sn
        self._attr_unique_id = f"{self.coordinator.data[self.sn]['sn']}-power"
        _LOGGER.debug("Creating SemsSensor with id %s", self.sn)
        self._attr_unique_id = f"{self.coordinator.data[self.sn]['sn']}-power"
        _LOGGER.debug(
            "Creating SemsSensor with id %s and data %s",
            self.sn,
            self.coordinator.data[self.sn],
        )

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    @property
    def native_value(self):
        """Return the value reported by the sensor."""
        data = self.coordinator.data[self.sn]
        return data["pac"] if data["status"] == 1 else 0

    def _statusText(self, status) -> str:
        labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
        return labels.get(status, "Unknown")

    # For backwards compatibility
    @property
    def extra_state_attributes(self):
        """Return the state attributes of the monitored installation."""
        data = self.coordinator.data[self.sn]
        attributes = {k: v for k, v in data.items() if k is not None and v is not None}
        attributes["statusText"] = self._statusText(data["status"])
        return attributes

    @property
    def is_on(self) -> bool:
        """Return entity status."""
        return self.coordinator.data[self.sn]["status"] == 1

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.sn)},
            name=f"Inverter {self.coordinator.data[self.sn]['name']}",
            manufacturer="GoodWe",
            model=self.extra_state_attributes.get("model_type", "unknown"),
            sw_version=self.extra_state_attributes.get("firmwareversion", "unknown"),
            configuration_url=f"https://semsportal.com/PowerStation/PowerStatusSnMin/{self.coordinator.data[self.sn]['powerstation_id']}",
        )

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self.coordinator.async_request_refresh()


class SemsStatisticsSensor(CoordinatorEntity, SensorEntity):
    """Sensor in kWh to enable HA statistics, in the end usable in the power component."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, sn) -> None:
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.sn = sn
        _LOGGER.debug("Creating SemsStatisticsSensor with id %s", self.sn)
        _LOGGER.debug(
            "Creating SemsSensor with id %s and data %s",
            self.sn,
            self.coordinator.data[self.sn],
        )

    @property
    def device_class(self):
        return SensorDeviceClass.ENERGY

    @property
    def unit_of_measurement(self):
        return UnitOfEnergy.KILO_WATT_HOUR

    # @property
    # def name(self) -> str:
    #     """Return the name of the sensor."""
    #     return f"Inverter {self.coordinator.data[self.sn]['name']} Energy"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.data[self.sn]['sn']}-energy"

    @property
    def state(self):
        """Return the state of the device."""
        _LOGGER.debug(
            "SemsStatisticsSensor state, coordinator data: %s", self.coordinator.data
        )
        _LOGGER.debug("SemsStatisticsSensor self.sn: %s", self.sn)
        _LOGGER.debug(
            "SemsStatisticsSensor state, self data: %s", self.coordinator.data[self.sn]
        )
        data = self.coordinator.data[self.sn]
        return data["etotal"]

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def device_info(self):
        # _LOGGER.debug("self.device_state_attributes: %s", self.device_state_attributes)
        data = self.coordinator.data[self.sn]
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.sn)
            },
            # "name": self.name,
            "manufacturer": "GoodWe",
            "model": data.get("model_type", "unknown"),
            "sw_version": data.get("firmwareversion", "unknown"),
            # "via_device": (DOMAIN, self.api.bridgeid),
        }

    @property
    def state_class(self):
        """used by Metered entities / Long Term Statistics"""
        return SensorStateClass.TOTAL_INCREASING

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self.coordinator.async_request_refresh()


class SemsTotalImportSensor(CoordinatorEntity, SensorEntity):
    """Sensor in kWh to enable HA statistics, in the end usable in the power component."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, sn):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.sn = sn
        _LOGGER.debug("Creating SemsStatisticsSensor with id %s", self.sn)

    @property
    def device_class(self):
        return SensorDeviceClass.ENERGY

    @property
    def unit_of_measurement(self):
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "HomeKit Import"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.data[self.sn]['sn']}-import-energy"

    @property
    def state(self):
        """Return the state of the device."""
        data = self.coordinator.data[self.sn]
        return data["Charts_buy"]

    def statusText(self, status) -> str:
        labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
        return labels[status] if status in labels else "Unknown"

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.sn)
            },
            "name": "Homekit",
            "manufacturer": "GoodWe",
        }

    @property
    def state_class(self):
        """used by Metered entities / Long Term Statistics"""
        return SensorStateClass.TOTAL_INCREASING

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self.coordinator.async_request_refresh()


class SemsTotalExportSensor(CoordinatorEntity, SensorEntity):
    """Sensor in kWh to enable HA statistics, in the end usable in the power component."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, sn):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.sn = sn
        _LOGGER.debug("Creating SemsStatisticsSensor with id %s", self.sn)

    @property
    def device_class(self):
        return SensorDeviceClass.ENERGY

    @property
    def unit_of_measurement(self):
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "HomeKit Export"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.data[self.sn]['sn']}-export-energy"

    @property
    def state(self):
        """Return the state of the device."""
        data = self.coordinator.data[self.sn]
        return data["Charts_sell"]

    def statusText(self, status) -> str:
        labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
        return labels[status] if status in labels else "Unknown"

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.sn)
            },
            "name": "Homekit",
            "manufacturer": "GoodWe",
        }

    @property
    def state_class(self):
        """used by Metered entities / Long Term Statistics"""
        return SensorStateClass.TOTAL_INCREASING

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self.coordinator.async_request_refresh()


class SemsPowerflowSensor(CoordinatorEntity, SensorEntity):
    """SemsPowerflowSensor using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, sn):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.sn = sn

    @property
    def device_class(self):
        return SensorDeviceClass.POWER_FACTOR

    @property
    def unit_of_measurement(self):
        return UnitOfPower.WATT

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"HomeKit {self.coordinator.data[self.sn]['sn']}"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.data[self.sn]['sn']}-homekit"

    @property
    def state(self):
        """Return the state of the device."""
        data = self.coordinator.data[self.sn]
        load = data["load"]

        if load:
            load = load.replace("(W)", "")

        return load if data["gridStatus"] == 1 else 0

    def statusText(self, status) -> str:
        labels = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
        return labels[status] if status in labels else "Unknown"

    # For backwards compatibility
    @property
    def extra_state_attributes(self):
        """Return the state attributes of the monitored installation."""
        data = self.coordinator.data[self.sn]

        attributes = {k: v for k, v in data.items() if k is not None and v is not None}

        attributes["pv"] = data["pv"].replace("(W)", "")
        attributes["bettery"] = data["bettery"].replace("(W)", "")
        attributes["load"] = data["load"].replace("(W)", "")
        attributes["grid"] = data["grid"].replace("(W)", "")

        attributes["statusText"] = self.statusText(data["gridStatus"])

        if data["loadStatus"] == -1:
            attributes["PowerFlowDirection"] = "Export %s" % data["grid"]
        if data["loadStatus"] == 1:
            attributes["PowerFlowDirection"] = "Import %s" % data["grid"]

        return attributes

    @property
    def is_on(self) -> bool:
        """Return entity status."""
        self.coordinator.data[self.sn]["gridStatus"] == 1

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.sn)
            },
            "name": "Homekit",
            "manufacturer": "GoodWe",
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self.coordinator.async_request_refresh()

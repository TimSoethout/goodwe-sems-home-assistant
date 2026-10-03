"""The sems integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
from typing import Any

import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_STATION_ID,
    DOMAIN,
    GOODWE_SPELLING,
    HOMEKIT_NO_SERIAL,
    LEGACY_HOMEKIT_DEVICE_ID,
    PLATFORMS,
    account_key,
    homekit_device_id,
    homekit_station_serial,
    redact_for_log,
    scan_interval_seconds,
)
from .sems_api import (
    OutOfRetries,
    SemsApi,
    SemsAuthError,
    SemsPermissionError,
    SemsRateLimitedError,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_IMMEDIATE_CHARGING_FUNCTION_KEYS = {
    "immediate_charge",
    "stop_charging",
    "end_charge_soc",
    "bat_immediate_charge_power",
}

# Unique ID suffixes only used by HomeKit/powerflow sensors (not inverter sensors).
_HOMEKIT_UNIQUE_ID_SUFFIXES = (
    "-import-energy-total",
    "-export-energy-total",
    "-import-energy",
    "-export-energy",
    "-load-status",
    "-homekit",
    "-grid",
)

_ENERGY_STATISTICS_CHART_KEYS = {
    "sum",
    "buy",
    "sell",
    "selfUseOfPv",
    "consumptionOfLoad",
    "charge",
    "disCharge",
    "gensetGen",
    "microGridGen",
}


@dataclass(slots=True)
class SemsRuntimeData:
    """Runtime data stored on the config entry."""

    api: SemsApi
    coordinator: SemsDataUpdateCoordinator


type SemsConfigEntry = ConfigEntry[SemsRuntimeData]


@dataclass(slots=True)
class _SharedApi:
    """An API client shared by the config entries of one account."""

    api: SemsApi
    entry_ids: set[str]


def _shared_clients(hass: HomeAssistant) -> dict[str, _SharedApi]:
    """Return the shared API clients, keyed by account."""
    return hass.data.setdefault(DOMAIN, {}).setdefault("clients", {})


def _acquire_api(hass: HomeAssistant, entry: ConfigEntry) -> SemsApi:
    """Return the account's shared API client, creating it if needed.

    SEMS+ keeps one web session per account, so the stations of an account
    must share one client and token instead of logging in against each other.
    """
    clients = _shared_clients(hass)
    key = account_key(entry.data[CONF_USERNAME])
    shared = clients.get(key)
    if shared is None:
        shared = clients[key] = _SharedApi(
            api=SemsApi(hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]),
            entry_ids=set(),
        )
    else:
        # The most recently set up entry carries the newest password.
        shared.api.update_credentials(entry.data[CONF_PASSWORD])
    shared.entry_ids.add(entry.entry_id)
    return shared.api


async def _async_release_api(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Release the entry's reference and close the client after the last one."""
    clients = _shared_clients(hass)
    key = account_key(entry.data[CONF_USERNAME])
    shared = clients.get(key)
    if shared is None:
        return
    shared.entry_ids.discard(entry.entry_id)
    if not shared.entry_ids:
        del clients[key]
        await hass.async_add_executor_job(shared.api.close)


def _normalize_energy_statistics_charts(
    charts: dict[str, Any], inverter_capacity_kw: float | None
) -> dict[str, Any]:
    """Convert daily chart fields from Wh when they exceed inverter capacity."""
    if not inverter_capacity_kw or inverter_capacity_kw <= 0:
        return charts.copy()

    max_daily_energy_kwh = inverter_capacity_kw * 24
    normalized = charts.copy()
    for key in _ENERGY_STATISTICS_CHART_KEYS:
        value = normalized.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > max_daily_energy_kwh
        ):
            normalized[key] = value / 1000
            _LOGGER.debug(
                "Normalized SEMS chart field %s from %s Wh to %s kWh",
                key,
                value,
                normalized[key],
            )
    return normalized


@dataclass(slots=True)
class SemsData:
    """Runtime SEMS data returned by the coordinator."""

    inverters: dict[str, dict[str, Any]]
    batteries: dict[str, dict[str, dict[str, Any]]] | None = None
    immediate_charging: dict[str, dict[str, Any]] | None = None
    homekit: dict[str, Any] | None = None
    currency: str | None = None
    ev_chargers: dict[str, dict[str, Any]] | None = None
    unavailable_inverter_sources: dict[str, set[str]] = field(default_factory=dict)
    unavailable_homekit_sources: set[str] = field(default_factory=set)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the sems component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SemsConfigEntry) -> bool:
    """Set up sems from a config entry."""
    _async_migrate_station_scoped_homekit(hass, entry)
    sems_api = _acquire_api(hass, entry)
    coordinator = SemsDataUpdateCoordinator(hass, sems_api, entry)
    entry.runtime_data = SemsRuntimeData(api=sems_api, coordinator=coordinator)

    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        # A failed setup is not unloaded, so release the client here. This
        # covers both the first refresh and forwarding to the platforms.
        await _async_release_api(hass, entry)
        raise

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: SemsConfigEntry) -> None:
    """Apply a changed update interval without reloading the entry.

    A reload would refetch every station of the account at once; the new
    interval instead takes effect from the next scheduled refresh.
    """
    coordinator = entry.runtime_data.coordinator
    update_interval = timedelta(
        seconds=scan_interval_seconds(entry.data, entry.options)
    )
    if coordinator.update_interval != update_interval:
        _LOGGER.debug(
            "SEMS - Update interval of %s changed to %s",
            redact_for_log(coordinator.station_id),
            update_interval,
        )
        coordinator.update_interval = update_interval


def _migrate_unique_ids(hass: HomeAssistant, migrations: dict[str, str]) -> None:
    """Migrate unique IDs based on the provided mapping."""
    ent_reg = er.async_get(hass)

    for old_unique_id, new_unique_id in migrations.items():
        entity_id = ent_reg.async_get_entity_id(Platform.SENSOR, DOMAIN, old_unique_id)
        _LOGGER.debug("Entity ID: %s", entity_id)
        if entity_id is None:
            continue
        try:
            ent_reg.async_update_entity(entity_id, new_unique_id=new_unique_id)
        except ValueError:
            # Unique IDs contain serials and station IDs, so log the entity ID.
            _LOGGER.warning(
                "Skip unique_id migration of %s because the new ID already exists",
                entity_id,
            )
        else:
            _LOGGER.info("Migrated unique_id of %s", entity_id)


def _async_migrate_station_scoped_homekit(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Move HomeKit/powerflow IDs shared by all stations to station-scoped IDs.

    Releases up to 11.12.0-beta.6 gave every station without a HomeKit serial
    the same `GW-HOMEKIT-NO-SERIAL-*` unique IDs and every station the same
    `homeKit` device, so only one station of an account kept those entities.
    The registry entries that belong to this entry move to IDs scoped to its
    station. Only unique IDs and device identifiers change: entity IDs, and
    with them the recorder and Energy dashboard history, are kept.
    """
    station_id = entry.data.get(CONF_STATION_ID)
    if not isinstance(station_id, str) or not station_id:
        return

    ent_reg = er.async_get(hass)
    legacy_prefix = f"{HOMEKIT_NO_SERIAL}-"
    station_serial = homekit_station_serial(station_id)
    _migrate_unique_ids(
        hass,
        {
            entity.unique_id: (
                f"{station_serial}-{entity.unique_id.removeprefix(legacy_prefix)}"
            )
            for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
            if entity.domain == Platform.SENSOR
            and entity.unique_id.startswith(legacy_prefix)
        },
    )

    dev_reg = dr.async_get(hass)
    legacy_identifier = (DOMAIN, LEGACY_HOMEKIT_DEVICE_ID)
    station_identifier = (DOMAIN, homekit_device_id(station_id))
    entry_devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    legacy_device = next(
        (device for device in entry_devices if legacy_identifier in device.identifiers),
        None,
    )
    if legacy_device is None:
        return
    owner_entry_ids = {
        entity.config_entry_id
        for entity in er.async_entries_for_device(
            ent_reg, legacy_device.id, include_disabled_entities=True
        )
    }
    if owner_entry_ids - {entry.entry_id} or any(
        station_identifier in device.identifiers for device in entry_devices
    ):
        # Another station still has entities on the shared device and takes it
        # over when it is set up. This entry's entities move to its station
        # device when the sensor platform adds them.
        if entry.entry_id not in owner_entry_ids:
            _async_detach_device(dev_reg, legacy_device, entry.entry_id)
        return
    # Keep the device, with its area and name, for this station.
    dev_reg.async_update_device(legacy_device.id, new_identifiers={station_identifier})
    # Older HA versions link one device to several config entries.
    for other_entry_id in _device_config_entry_ids(legacy_device) - {entry.entry_id}:
        dev_reg.async_update_device(
            legacy_device.id, remove_config_entry_id=other_entry_id
        )
    _LOGGER.info("Migrated the shared HomeKit device to a station-scoped device")


def _device_config_entry_ids(device: dr.DeviceEntry) -> set[str]:
    """Return the config entries of a device on old and new HA versions."""
    config_entry_id = getattr(device, "config_entry_id", None)
    if isinstance(config_entry_id, str):
        return {config_entry_id}
    return set(device.config_entries)


def _async_detach_device(
    dev_reg: dr.DeviceRegistry, device: dr.DeviceEntry, entry_id: str
) -> None:
    """Remove a config entry from a device, removing the device if it was the last."""
    if _device_config_entry_ids(device) - {entry_id}:
        dev_reg.async_update_device(device.id, remove_config_entry_id=entry_id)
    else:
        dev_reg.async_remove_device(device.id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 2:
        _LOGGER.error("Cannot migrate entry version %s", entry.version)
        return False

    if entry.version < 2:
        station_id = entry.data.get(CONF_STATION_ID)
        if entry.unique_id is None and isinstance(station_id, str) and station_id:
            hass.config_entries.async_update_entry(
                entry, version=2, unique_id=station_id
            )
        else:
            hass.config_entries.async_update_entry(entry, version=2)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SemsConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await _async_release_api(hass, entry)
    return unload_ok


class SemsDataUpdateCoordinator(DataUpdateCoordinator[SemsData]):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, sems_api: SemsApi, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        self.sems_api = sems_api
        self.station_id = entry.data[CONF_STATION_ID]

        update_interval = timedelta(
            seconds=scan_interval_seconds(entry.data, entry.options)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def async_control(self, method: Callable[..., Any], *args: Any) -> None:
        """Run a blocking control command of the API client.

        When SEMS rejects the credentials, ask for reauthentication right away
        instead of waiting for the next refresh to fail as well.
        """
        try:
            await self.hass.async_add_executor_job(method, *args)
        except SemsAuthError as err:
            if self.config_entry is not None:
                self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "SEMS rejected the account credentials; reauthenticate the "
                "integration and try again"
            ) from err

    def _registered_homekit_sn(self, current_sn: str | None) -> str | None:
        """Return the serial of earlier registered HomeKit sensors, if any.

        Serials other than `current_sn` win, so long-lived entities are kept
        over ones created after the SEMS+ migration changed the serial.
        """
        if self.config_entry is None:
            return None
        serials: dict[str, bool] = {}
        for entity in er.async_entries_for_config_entry(
            er.async_get(self.hass), self.config_entry.entry_id
        ):
            if entity.domain != "sensor":
                continue
            for suffix in _HOMEKIT_UNIQUE_ID_SUFFIXES:
                if not entity.unique_id.endswith(suffix):
                    continue
                serial = entity.unique_id.removesuffix(suffix)
                # 8.0.0 "powerflow-*" IDs are migrated by the sensor platform.
                if serial and serial != "powerflow":
                    serials[serial] = serials.get(serial, False) or (
                        suffix == "-import-energy-total"
                    )
                break
        earlier = {
            sn: has_total for sn, has_total in serials.items() if sn != current_sn
        }
        if not earlier:
            return None
        # Prefer the serial that carries the lifetime import counter.
        return max(earlier, key=lambda sn: earlier[sn])

    def _last_month_energy_requested(self) -> bool:
        """Return whether an enabled sensor needs the previous month's energy.

        The previous-month statistics cost an extra request per refresh, so
        they are only fetched once the user enabled the (disabled by default)
        "Energy Last Month" sensor.
        """
        if self.config_entry is None:
            return False
        suffix = f"-{GOODWE_SPELLING.lastMonthTotalE}"
        return any(
            entity.domain == "sensor"
            and entity.unique_id.endswith(suffix)
            and entity.disabled_by is None
            for entity in er.async_entries_for_config_entry(
                er.async_get(self.hass), self.config_entry.entry_id
            )
        )

    async def _async_get_energy_storage_cabinets(
        self, data_result: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch the energy storage cabinets when batteries are available."""
        if not data_result.get("info", {}).get("is_stored", False):
            return {}

        prefetched = data_result.get("_energy_storage_cabinets")
        if isinstance(prefetched, dict):
            return {
                serial_number: cabinets
                for serial_number, cabinets in prefetched.items()
                if isinstance(serial_number, str) and isinstance(cabinets, list)
            }

        _LOGGER.debug("Getting energy storage integrated cabinets")
        return {
            inverter.get("invert_full", {}).get(
                "sn"
            ): await self.hass.async_add_executor_job(
                self.sems_api.getEnergyStorageIntegratedCabinets,
                self.station_id,
                inverter.get("invert_full", {}).get("sn"),
            )
            for inverter in data_result.get("inverter", {})
        }

    async def _async_get_battery_functions(
        self, energy_storage_cabinets: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, dict[str, Any]]] | None:
        """Fetch and retain supported battery functions."""
        if energy_storage_cabinets:
            _LOGGER.debug("Getting battery general functions for each cabinet")
        battery_general_functions = {
            sn: {
                bat.get("translateCode"): await self.hass.async_add_executor_job(
                    self.sems_api.getBatteryGeneralFunctions, sn, bat.get("no", 0)
                )
                for bat in bats
                if isinstance(bat, dict) and bat.get("translateCode") is not None
            }
            for sn, bats in energy_storage_cabinets.items()
        }

        batteries: dict[str, dict[str, dict[str, Any]]] = {}
        for sn, bats in battery_general_functions.items():
            for bat_id, bat in bats.items():
                if not isinstance(bat_id, str):
                    continue
                for child in bat.get("functionMenus", {}).get("children", []):
                    for func in child.get("functions", []):
                        function_key = func.get("translateKey")
                        if not isinstance(function_key, str):
                            continue
                        if function_key not in _IMMEDIATE_CHARGING_FUNCTION_KEYS:
                            continue

                        if sn not in batteries:
                            batteries[sn] = {}
                        if bat_id not in batteries[sn]:
                            batteries[sn][bat_id] = {
                                "name": next(
                                    (
                                        cabinet.get("name", "")
                                        for cabinet in energy_storage_cabinets.get(
                                            sn, []
                                        )
                                        if cabinet.get("translateCode") == bat_id
                                    ),
                                    "",
                                ),
                                "functions": {},
                            }

                        batteries[sn][bat_id]["functions"][function_key] = {
                            "address": func.get("address"),
                            "id": func.get("id"),
                        }

        return batteries or None

    async def _async_get_immediate_charging(
        self, batteries: dict[str, dict[str, dict[str, Any]]] | None
    ) -> dict[str, dict[str, Any]] | None:
        """Fetch immediate-charging state for battery-equipped inverters."""
        if not batteries:
            return None

        immediate_charging: dict[str, dict[str, Any]] = {}
        for inverter_sn in batteries:
            try:
                immediate_charging_result = await self.hass.async_add_executor_job(
                    self.sems_api.getBatteryImmediateChargingStates, inverter_sn
                )
            except (OutOfRetries, SemsPermissionError) as err:
                immediate_charging_result = None
                _LOGGER.debug(
                    "Immediate-charging state request failed for %s: %s",
                    redact_for_log(inverter_sn),
                    err,
                )
            state_data = (
                immediate_charging_result.get("data")
                if isinstance(immediate_charging_result, dict)
                else None
            )
            if not isinstance(state_data, dict):
                # Leave the inverter out so its entities become unavailable
                # instead of reporting a disabled function.
                _LOGGER.debug(
                    "No immediate-charging state for %s",
                    redact_for_log(inverter_sn),
                )
                continue
            immediate_charging[inverter_sn] = {
                "enabled": bool(state_data.get("47545", 0)),
                "end_charge_soc": state_data.get("47546", 0),
                "charging_power": state_data.get("47603", 0),
            }

        return immediate_charging

    async def _async_update_data(self) -> SemsData:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        # async with async_timeout.timeout(10):
        try:
            data_result = await self.hass.async_add_executor_job(
                partial(
                    self.sems_api.getData,
                    self.station_id,
                    include_last_month=self._last_month_energy_requested(),
                )
            )

            energy_storage_cabinets = await self._async_get_energy_storage_cabinets(
                data_result
            )
            batteries = await self._async_get_battery_functions(energy_storage_cabinets)
            immediate_charging = await self._async_get_immediate_charging(batteries)

        except SemsAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SemsRateLimitedError as err:
            raise UpdateFailed(
                f"SEMS API rate limited (retry after {err.retry_after}s)",
                retry_after=err.retry_after,
            ) from err
        except (HomeAssistantError, requests.RequestException) as err:
            # SEMS API errors are HomeAssistantError subclasses. Anything else
            # is a bug: let the coordinator log it with a traceback instead of
            # reporting it as a communication error.
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        else:
            _LOGGER.debug("semsApi.getData result: %s", redact_for_log(data_result))

            inverters = data_result.get("inverter")
            inverters_by_sn: dict[str, dict[str, Any]] = {}
            if inverters is None:
                inverters = []
            elif not isinstance(inverters, list):
                raise UpdateFailed(
                    "Error communicating with API: invalid inverter data. See debug logs."
                )

            unavailable_data_sources = data_result.get("unavailable_data_sources", {})
            if not isinstance(unavailable_data_sources, dict):
                raise UpdateFailed(
                    "Error communicating with API: invalid source status."
                )
            raw_inverter_sources = unavailable_data_sources.get("inverters", {})
            raw_homekit_sources = unavailable_data_sources.get("homekit", set())
            if not isinstance(raw_inverter_sources, dict) or not isinstance(
                raw_homekit_sources, set
            ):
                raise UpdateFailed(
                    "Error communicating with API: invalid source status."
                )
            unavailable_inverter_sources: dict[str, set[str]] = {}
            for inverter_sn, sources in raw_inverter_sources.items():
                if (
                    not isinstance(inverter_sn, str)
                    or not isinstance(sources, set)
                    or any(not isinstance(source, str) for source in sources)
                ):
                    raise UpdateFailed(
                        "Error communicating with API: invalid source status."
                    )
                unavailable_inverter_sources[inverter_sn] = sources
            if any(not isinstance(source, str) for source in raw_homekit_sources):
                raise UpdateFailed(
                    "Error communicating with API: invalid source status."
                )

            # Get Inverter Data
            for inverter in inverters:
                inverter_full = inverter.get("invert_full")
                if not isinstance(inverter_full, dict):
                    continue

                name = inverter_full.get("name")
                sn = inverter_full.get("sn")
                if not isinstance(sn, str):
                    continue

                _LOGGER.debug(
                    "Found inverter attribute %s %s",
                    name,
                    redact_for_log(sn),
                )
                inverters_by_sn[sn] = inverter_full

            # Add currency
            kpi = data_result.get("kpi")
            if not isinstance(kpi, dict):
                kpi = {}
            currency = kpi.get("currency")

            has_powerflow = bool(data_result.get("hasPowerflow"))
            has_energy_statistics_charts = bool(
                data_result.get(GOODWE_SPELLING.hasEnergyStatisticsCharts)
            )

            homekit: dict[str, Any] | None = None

            if has_powerflow:
                _LOGGER.debug("Found powerflow data")
                powerflow = data_result.get("powerflow")
                if not isinstance(powerflow, dict):
                    powerflow = {}

                if has_energy_statistics_charts:
                    charts = data_result.get(GOODWE_SPELLING.energyStatisticsCharts)
                    if not isinstance(charts, dict):
                        charts = {}
                    else:
                        capacities: list[float] = []
                        for inverter in inverters_by_sn.values():
                            capacity = inverter.get("capacity")
                            if isinstance(capacity, (int, float)):
                                capacities.append(float(capacity))
                        inverter_capacity_kw = sum(capacities) if capacities else None
                        charts = _normalize_energy_statistics_charts(
                            charts, inverter_capacity_kw
                        )
                    totals = data_result.get(GOODWE_SPELLING.energyStatisticsTotals)
                    if not isinstance(totals, dict):
                        totals = {}

                    powerflow = {
                        **powerflow,
                        **{f"Charts_{key}": val for key, val in charts.items()},
                        **{f"Totals_{key}": val for key, val in totals.items()},
                    }

                # Add the flag so sensors can check if energy statistics are available
                powerflow[GOODWE_SPELLING.hasEnergyStatisticsCharts] = (
                    has_energy_statistics_charts
                )

                homekit_data = data_result.get(GOODWE_SPELLING.homeKit)
                if not isinstance(homekit_data, dict):
                    homekit_data = powerflow
                powerflow["sn"] = homekit_data.get("sn")
                if GOODWE_SPELLING.homeKit not in data_result:
                    # SEMS+ Web data has no HomeKit serial; keep the serial of
                    # previously registered HomeKit entities so their unique IDs
                    # (and Energy dashboard history) keep receiving data.
                    powerflow["sn"] = (
                        self._registered_homekit_sn(powerflow["sn"]) or powerflow["sn"]
                    )

                # Goodwe 'Power Meter' (not HomeKit) and SEMS+ stations
                # without a smart meter have no sn. Use a station-scoped one,
                # otherwise the unique IDs collide across stations.
                if powerflow["sn"] is None:
                    powerflow["sn"] = homekit_station_serial(self.station_id)

                # _LOGGER.debug("homeKit sn: %s", result["homKit"]["sn"])
                # This seems more accurate than the Chart_sum
                powerflow["all_time_generation"] = kpi.get("total_power")

                homekit = powerflow

            if not inverters_by_sn and homekit is None:
                raise UpdateFailed("No data available from API")

            data = SemsData(
                inverters=inverters_by_sn,
                batteries=batteries,
                homekit=homekit,
                currency=currency,
                ev_chargers=data_result.get("ev_chargers") or None,
                immediate_charging=immediate_charging,
                unavailable_inverter_sources=unavailable_inverter_sources,
                unavailable_homekit_sources=raw_homekit_sources,
            )
            _LOGGER.debug(
                "Resulting data: %s",
                redact_for_log(data),
            )
            return data


# Type alias to make type inference working for pylance
type SemsCoordinator = SemsDataUpdateCoordinator

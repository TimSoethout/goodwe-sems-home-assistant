"""The sems integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
from functools import partial
from typing import Any, TypeGuard

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
    redact_sensitive_text,
    redact_value,
    scan_interval_seconds,
)
from .models import BatteryCabinet, SemsData
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
    poll_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _is_shared_api_mapping(value: object) -> TypeGuard[dict[str, _SharedApi]]:
    """Return whether shared account data has its expected shape."""
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(shared, _SharedApi)
        for key, shared in value.items()
    )


def _shared_clients(hass: HomeAssistant) -> dict[str, _SharedApi]:
    """Return the shared API clients, keyed by account."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not isinstance(domain_data, dict):
        raise TypeError("SEMS integration data must be a mapping")
    clients = domain_data.setdefault("clients", {})
    if not _is_shared_api_mapping(clients):
        raise TypeError("SEMS shared clients must be a mapping of API clients")
    return clients


def _acquire_shared_api(hass: HomeAssistant, entry: ConfigEntry) -> _SharedApi:
    """Return the account's shared API state, creating it if needed.

    SEMS+ keeps one web session per account, so the stations of an account
    must share one client and token instead of logging in against each other.
    """
    clients = _shared_clients(hass)
    key = account_key(entry.data[CONF_USERNAME])
    shared = clients.get(key)
    if shared is None:
        shared = clients[key] = _SharedApi(
            api=SemsApi(
                hass,
                entry.data[CONF_USERNAME],
                entry.data[CONF_PASSWORD],
                use_async_transport=True,
            ),
            entry_ids=set(),
        )
    else:
        # The most recently set up entry carries the newest password.
        shared.api.update_credentials(entry.data[CONF_PASSWORD])
    shared.entry_ids.add(entry.entry_id)
    return shared


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


def _normalize_unavailable_sources(
    data_result: dict[str, Any],
) -> tuple[dict[str, set[str]], set[str]]:
    """Normalize and validate optional source availability."""
    unavailable = data_result.get("unavailable_data_sources", {})
    if not isinstance(unavailable, dict):
        raise UpdateFailed("Error communicating with API: invalid source status.")

    raw_inverter_sources = unavailable.get("inverters", {})
    raw_homekit_sources = unavailable.get("homekit", set())
    if not isinstance(raw_inverter_sources, dict) or not isinstance(
        raw_homekit_sources, set
    ):
        raise UpdateFailed("Error communicating with API: invalid source status.")

    inverter_sources: dict[str, set[str]] = {}
    for serial_number, sources in raw_inverter_sources.items():
        valid_sources = isinstance(sources, set) and all(
            isinstance(source, str) for source in sources
        )
        if not isinstance(serial_number, str) or not valid_sources:
            raise UpdateFailed("Error communicating with API: invalid source status.")
        inverter_sources[serial_number] = sources
    if any(not isinstance(source, str) for source in raw_homekit_sources):
        raise UpdateFailed("Error communicating with API: invalid source status.")
    return inverter_sources, raw_homekit_sources


def _normalize_inverters(data_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize valid inverter records and skip malformed optional entries."""
    raw_inverters = data_result.get("inverter")
    if raw_inverters is None:
        raw_inverters = []
    if not isinstance(raw_inverters, list):
        raise UpdateFailed(
            "Error communicating with API: invalid inverter data. See debug logs."
        )

    inverters: dict[str, dict[str, Any]] = {}
    for inverter in raw_inverters:
        if not isinstance(inverter, dict):
            continue
        invert_full = inverter.get("invert_full")
        if not isinstance(invert_full, dict):
            continue
        serial_number = invert_full.get("sn")
        if isinstance(serial_number, str):
            inverters[serial_number] = invert_full
    return inverters


def _normalize_cabinet_index(value: Any) -> int:
    """Normalize a cabinet index to the API method's integer contract."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    return 0


def _normalize_battery_cabinets(
    data_result: dict[str, Any],
) -> tuple[BatteryCabinet, ...]:
    """Normalize prefetched battery cabinet discovery data."""
    sources = data_result.get("_energy_storage_cabinets")
    if not isinstance(sources, dict):
        return ()

    cabinets: list[BatteryCabinet] = []
    for serial_number, records in sources.items():
        if not isinstance(serial_number, str) or not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            cabinet_id = record.get("translateCode")
            if not isinstance(cabinet_id, str):
                continue
            cabinet_name = record.get("name")
            is_connected = record.get("isConnected")
            cabinets.append(
                BatteryCabinet(
                    serial_number=serial_number,
                    index=_normalize_cabinet_index(record.get("no")),
                    cabinet_id=cabinet_id,
                    name=cabinet_name if isinstance(cabinet_name, str) else "",
                    is_connected=(
                        is_connected if isinstance(is_connected, bool) else None
                    ),
                )
            )
    return tuple(cabinets)


def _normalize_homekit(
    data_result: dict[str, Any],
    inverters: dict[str, dict[str, Any]],
    kpi: dict[str, Any],
    station_id: str,
    registered_homekit_sn: Callable[[str | None], str | None],
) -> dict[str, Any] | None:
    """Normalize optional HomeKit/power-flow data."""
    if not data_result.get("hasPowerflow"):
        return None

    powerflow = data_result.get("powerflow")
    powerflow = powerflow if isinstance(powerflow, dict) else {}
    has_energy_statistics = bool(
        data_result.get(GOODWE_SPELLING.hasEnergyStatisticsCharts)
    )
    if has_energy_statistics:
        charts = data_result.get(GOODWE_SPELLING.energyStatisticsCharts)
        charts = charts if isinstance(charts, dict) else {}
        capacities = [
            float(inverter["capacity"])
            for inverter in inverters.values()
            if isinstance(inverter.get("capacity"), (int, float))
            and not isinstance(inverter.get("capacity"), bool)
        ]
        charts = _normalize_energy_statistics_charts(
            charts,
            sum(capacities) if capacities else None,
        )
        totals = data_result.get(GOODWE_SPELLING.energyStatisticsTotals)
        totals = totals if isinstance(totals, dict) else {}
        powerflow = {
            **powerflow,
            **{f"Charts_{key}": value for key, value in charts.items()},
            **{f"Totals_{key}": value for key, value in totals.items()},
        }

    powerflow[GOODWE_SPELLING.hasEnergyStatisticsCharts] = has_energy_statistics
    homekit_data = data_result.get(GOODWE_SPELLING.homeKit)
    homekit_data = homekit_data if isinstance(homekit_data, dict) else powerflow
    homekit_serial = homekit_data.get("sn")
    if not isinstance(homekit_serial, str):
        homekit_serial = None
    if GOODWE_SPELLING.homeKit not in data_result:
        homekit_serial = registered_homekit_sn(homekit_serial) or homekit_serial
    if homekit_serial is None:
        homekit_serial = homekit_station_serial(station_id)
    powerflow["sn"] = homekit_serial
    powerflow["all_time_generation"] = kpi.get("total_power")
    return powerflow


def _normalize_station_data(
    data_result: Any,
    station_id: str,
    registered_homekit_sn: Callable[[str | None], str | None],
) -> SemsData:
    """Validate and normalize the API envelope at the coordinator boundary."""
    if not isinstance(data_result, dict):
        raise UpdateFailed("Error communicating with API: invalid station data.")

    inverters = _normalize_inverters(data_result)
    unavailable_inverters, unavailable_homekit = _normalize_unavailable_sources(
        data_result
    )
    kpi = data_result.get("kpi")
    kpi = kpi if isinstance(kpi, dict) else {}
    currency = kpi.get("currency")
    currency = currency if isinstance(currency, str) else None
    battery_cabinets = _normalize_battery_cabinets(data_result)
    info = data_result.get("info")
    battery_storage_supported = (
        isinstance(info, dict) and info.get("is_stored") is True
    ) or isinstance(data_result.get("_energy_storage_cabinets"), dict)
    ev_chargers = data_result.get("ev_chargers")
    homekit = _normalize_homekit(
        data_result,
        inverters,
        kpi,
        station_id,
        registered_homekit_sn,
    )
    if not inverters and homekit is None:
        raise UpdateFailed("No data available from API")

    return SemsData(
        inverters=inverters,
        battery_cabinets=battery_cabinets,
        battery_storage_supported=battery_storage_supported,
        homekit=homekit,
        currency=currency,
        ev_chargers=ev_chargers if isinstance(ev_chargers, dict) else None,
        unavailable_inverter_sources=unavailable_inverters,
        unavailable_homekit_sources=unavailable_homekit,
    )


def _parse_battery_menu(functions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract supported immediate-charging function metadata."""
    parsed: dict[str, dict[str, Any]] = {}
    function_menus = functions.get("functionMenus")
    if not isinstance(function_menus, dict):
        return parsed
    children = function_menus.get("children")
    if not isinstance(children, list):
        return parsed
    for child in children:
        if not isinstance(child, dict):
            continue
        menu_functions = child.get("functions")
        if not isinstance(menu_functions, list):
            continue
        for function in menu_functions:
            if not isinstance(function, dict):
                continue
            function_key = function.get("translateKey")
            if (
                isinstance(function_key, str)
                and function_key in _IMMEDIATE_CHARGING_FUNCTION_KEYS
            ):
                parsed[function_key] = {
                    "address": function.get("address"),
                    "id": function.get("id"),
                }
    return parsed


def _parse_battery_functions(
    function_responses: dict[str, dict[str, dict[str, Any]]],
    battery_cabinets: tuple[BatteryCabinet, ...],
) -> dict[str, dict[str, dict[str, Any]]] | None:
    """Build the typed battery capability shape from API function responses."""
    batteries: dict[str, dict[str, dict[str, Any]]] = {}
    for serial_number, cabinets in function_responses.items():
        for cabinet_id, functions in cabinets.items():
            supported = _parse_battery_menu(functions)
            if not supported:
                continue
            cabinet_name = next(
                (
                    cabinet.name
                    for cabinet in battery_cabinets
                    if cabinet.serial_number == serial_number
                    and cabinet.cabinet_id == cabinet_id
                ),
                "",
            )
            batteries.setdefault(serial_number, {})[cabinet_id] = {
                "name": cabinet_name,
                "functions": supported,
            }
    return batteries or None


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the sems component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SemsConfigEntry) -> bool:
    """Set up sems from a config entry."""
    _async_migrate_station_scoped_homekit(hass, entry)
    shared = _acquire_shared_api(hass, entry)
    sems_api = shared.api
    coordinator = SemsDataUpdateCoordinator(
        hass, sems_api, entry, poll_lock=shared.poll_lock
    )
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
            "SEMS - Update interval of station %s changed to %s",
            redact_value(coordinator.station_id),
            update_interval,
        )
        coordinator.update_interval = update_interval


def _migrate_unique_ids(hass: HomeAssistant, migrations: dict[str, str]) -> None:
    """Migrate unique IDs based on the provided mapping."""
    ent_reg = er.async_get(hass)

    for old_unique_id, new_unique_id in migrations.items():
        entity_id = ent_reg.async_get_entity_id(Platform.SENSOR, DOMAIN, old_unique_id)
        _LOGGER.debug(
            "Entity ID: %s", redact_sensitive_text(entity_id or "<not-found>")
        )
        if entity_id is None:
            continue
        try:
            ent_reg.async_update_entity(entity_id, new_unique_id=new_unique_id)
        except ValueError:
            _LOGGER.warning(
                "Skip unique_id migration of %s because the new ID already exists",
                redact_sensitive_text(entity_id),
            )
        else:
            _LOGGER.info(
                "Migrated unique_id of %s",
                redact_sensitive_text(entity_id),
            )


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
        self,
        hass: HomeAssistant,
        sems_api: SemsApi,
        entry: ConfigEntry,
        *,
        poll_lock: asyncio.Lock | None = None,
    ) -> None:
        """Initialize."""
        self.sems_api = sems_api
        self.station_id = entry.data[CONF_STATION_ID]
        self._poll_lock = poll_lock if poll_lock is not None else asyncio.Lock()

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

    async def async_control(self, method: Callable[..., Any], *args: Any) -> Any:
        """Run a blocking control command of the API client.

        When SEMS rejects the credentials, ask for reauthentication right away
        instead of waiting for the next refresh to fail as well.
        """
        try:
            result = await self.hass.async_add_executor_job(method, *args)
        except SemsAuthError as err:
            if self.config_entry is not None:
                self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "SEMS rejected the account credentials; reauthenticate the "
                "integration and try again"
            ) from err
        if result is False:
            raise HomeAssistantError("SEMS rejected the control command")
        return result

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

    async def _async_get_battery_cabinets(
        self, data: SemsData
    ) -> tuple[tuple[BatteryCabinet, ...], bool]:
        """Fetch and normalize cabinet records not prefetched by the API."""
        if data.battery_cabinets or not data.battery_storage_supported:
            return data.battery_cabinets, False

        _LOGGER.debug("Getting energy storage integrated cabinets")
        cabinet_records: list[BatteryCabinet] = []
        discovery_failed = False
        for serial_number in data.inverters:
            try:
                cabinets = await self.hass.async_add_executor_job(
                    self.sems_api.getEnergyStorageIntegratedCabinets,
                    self.station_id,
                    serial_number,
                )
            except (OutOfRetries, SemsPermissionError, SemsRateLimitedError) as err:
                _LOGGER.debug(
                    "Battery cabinet discovery failed for %s (%s)",
                    redact_value(serial_number),
                    type(err).__name__,
                )
                discovery_failed = True
                continue
            if not isinstance(cabinets, list):
                continue
            for cabinet in cabinets:
                if not isinstance(cabinet, dict):
                    continue
                cabinet_id = cabinet.get("translateCode")
                if not isinstance(cabinet_id, str):
                    continue
                cabinet_name = cabinet.get("name")
                is_connected = cabinet.get("isConnected")
                cabinet_records.append(
                    BatteryCabinet(
                        serial_number=serial_number,
                        index=_normalize_cabinet_index(cabinet.get("no")),
                        cabinet_id=cabinet_id,
                        name=cabinet_name if isinstance(cabinet_name, str) else "",
                        is_connected=(
                            is_connected if isinstance(is_connected, bool) else None
                        ),
                    )
                )
        return tuple(cabinet_records), discovery_failed

    async def _async_get_battery_functions(
        self, battery_cabinets: tuple[BatteryCabinet, ...]
    ) -> dict[str, dict[str, dict[str, Any]]] | None:
        """Fetch and retain supported battery functions."""
        if battery_cabinets:
            _LOGGER.debug("Getting battery general functions for each cabinet")
        battery_general_functions: dict[str, dict[Any, dict[str, Any]]] = {}
        for cabinet in battery_cabinets:
            if cabinet.is_connected is False:
                continue
            try:
                functions = await self.hass.async_add_executor_job(
                    self.sems_api.getBatteryGeneralFunctions,
                    cabinet.serial_number,
                    cabinet.index,
                )
            except SemsPermissionError as err:
                # Battery controls are optional; keep the station data.
                _LOGGER.debug(
                    "Battery functions request denied for %s (%s)",
                    redact_value(cabinet.serial_number),
                    type(err).__name__,
                )
                continue
            except OutOfRetries as err:
                _LOGGER.debug(
                    "Battery functions request exhausted retries for %s (%s)",
                    redact_value(cabinet.serial_number),
                    type(err).__name__,
                )
                return self.data.batteries if self.data is not None else None
            except SemsRateLimitedError as err:
                _LOGGER.debug(
                    "Battery functions request rate limited for %s (%s)",
                    redact_value(cabinet.serial_number),
                    type(err).__name__,
                )
                return self.data.batteries if self.data is not None else None
            battery_general_functions.setdefault(cabinet.serial_number, {})[
                cabinet.cabinet_id
            ] = functions

        return _parse_battery_functions(
            battery_general_functions,
            battery_cabinets,
        )

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
            except (OutOfRetries, SemsPermissionError, SemsRateLimitedError) as err:
                immediate_charging_result = None
                _LOGGER.debug(
                    "Immediate-charging state request failed for %s (%s)",
                    redact_value(inverter_sn),
                    type(err).__name__,
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
                    redact_value(inverter_sn),
                )
                continue
            immediate_charging[inverter_sn] = {
                "enabled": bool(state_data.get("47545", 0)),
                "end_charge_soc": state_data.get("47546", 0),
                "charging_power": state_data.get("47603", 0),
            }

        return immediate_charging

    async def _async_update_data(self) -> SemsData:
        """Serialize station refreshes that share one account client."""
        async with self._poll_lock:
            return await self._async_update_data_unlocked()

    async def _async_update_data_unlocked(self) -> SemsData:
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
            data = _normalize_station_data(
                data_result,
                self.station_id,
                self._registered_homekit_sn,
            )
            battery_cabinets, discovery_failed = await self._async_get_battery_cabinets(
                data
            )
            data = replace(data, battery_cabinets=battery_cabinets)

            cabinet_source_unavailable = any(
                "cabinets" in sources
                for sources in data.unavailable_inverter_sources.values()
            )
            if (
                (cabinet_source_unavailable or discovery_failed)
                and not battery_cabinets
                and self.data is not None
            ):
                batteries = self.data.batteries
            else:
                batteries = await self._async_get_battery_functions(battery_cabinets)
            immediate_charging = await self._async_get_immediate_charging(batteries)
            data = replace(
                data,
                batteries=batteries,
                immediate_charging=immediate_charging,
            )

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
            raise UpdateFailed(
                f"Error communicating with API: {redact_for_log(str(err))}"
            ) from err
        else:
            _LOGGER.debug("semsApi.getData result: %s", redact_for_log(data_result))
            _LOGGER.debug(
                "Resulting data: %s",
                redact_for_log(data),
            )
            return data


# Type alias to make type inference working for pylance
type SemsCoordinator = SemsDataUpdateCoordinator

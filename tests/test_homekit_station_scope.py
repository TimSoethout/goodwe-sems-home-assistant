"""Tests for station-scoped HomeKit/powerflow unique IDs and devices."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from custom_components.sems.sems_api import SemsApi

MOCK_STATION_ID_1 = "12345678-1234-5678-9abc-123456789abc"
MOCK_STATION_ID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
# IDs used by releases up to 11.12.0-beta.6.
LEGACY_SERIAL = "GW-HOMEKIT-NO-SERIAL"
LEGACY_DEVICE = (DOMAIN, "homeKit")


def _station_serial(station_id: str) -> str:
    return f"{station_id}-powerflow"


def _station_device(station_id: str) -> tuple[str, str]:
    return (DOMAIN, f"{station_id}-homekit")


def _get_data(station_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return SEMS+ data for a station without a smart meter."""
    return {
        "inverter": [
            {
                "invert_full": {
                    "name": f"Inverter {station_id[:4]}",
                    "sn": f"GW0000SN{station_id[:8]}",
                    "powerstation_id": station_id,
                    "status": 1,
                    "capacity": 3.0,
                    "pac": 589,
                }
            }
        ],
        "hasPowerflow": True,
        # SEMS+ Web data has no "homKit" key and no serial without a meter.
        "powerflow": SemsApi._normalize_web_homekit_data(
            {"pSystem": 3.0, "pGrid": 2.5, "pConsum": -0.5}
        ),
        "hasEnergeStatisticsCharts": True,
        "energeStatisticsCharts": {"buy": 1.5, "sell": 2.5},
        "energeStatisticsTotals": {"buy": 100.0, "sell": 200.0},
    }


@contextmanager
def _mock_api(get_data: Any = _get_data):
    with (
        patch.object(SemsApi, "getData", side_effect=get_data),
        patch.object(SemsApi, "getEnergyStorageIntegratedCabinets", return_value=[]),
        patch.object(SemsApi, "getBatteryGeneralFunctions", return_value={}),
    ):
        yield


def _entry(station_id: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=station_id,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "test_password",
            CONF_STATION_ID: station_id,
        },
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the integration, which sets up every added entry."""
    with _mock_api():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _reload(hass: HomeAssistant, *entries: MockConfigEntry) -> None:
    with _mock_api():
        for entry in entries:
            assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(Platform.SENSOR, DOMAIN, unique_id)


def _legacy_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    """Register the `homeKit` device of releases up to 11.12.0-beta.6.

    Older HA versions link every station to one shared device; newer ones keep
    one device per config entry with the same identifier.
    """
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={LEGACY_DEVICE},
        name="HomeKit",
        manufacturer="GoodWe",
    )


def _devices(
    hass: HomeAssistant, entry: MockConfigEntry, identifier: tuple[str, str]
) -> list[dr.DeviceEntry]:
    return [
        device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
        if identifier in device.identifiers
    ]


def _add_legacy_entities(
    hass: HomeAssistant, entry: MockConfigEntry, serial: str, device_id: str
) -> dict[str, str]:
    """Register HomeKit entities as releases up to 11.12.0-beta.6 did."""
    ent_reg = er.async_get(hass)
    return {
        suffix: ent_reg.async_get_or_create(
            Platform.SENSOR,
            DOMAIN,
            f"{serial}-{suffix}",
            config_entry=entry,
            device_id=device_id,
            suggested_object_id=f"legacy_{serial}_{suffix}",
        ).entity_id
        for suffix in ("load", "homekit", "import-energy-total")
    }


def _entity_snapshot(hass: HomeAssistant) -> dict[str, tuple[Any, ...]]:
    return {
        entity.entity_id: (entity.unique_id, entity.config_entry_id, entity.device_id)
        for entity in er.async_get(hass).entities.values()
    }


def _device_snapshot(
    hass: HomeAssistant, *entries: MockConfigEntry
) -> dict[str, frozenset[tuple[str, str]]]:
    return {
        device.id: frozenset(device.identifiers)
        for entry in entries
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
    }


async def test_two_stations_without_meter_get_distinct_ids_and_devices(
    hass: HomeAssistant,
) -> None:
    """Every station without a smart meter gets its own entities and device."""
    entry_1 = _entry(MOCK_STATION_ID_1)
    entry_2 = _entry(MOCK_STATION_ID_2)
    entry_1.add_to_hass(hass)
    entry_2.add_to_hass(hass)

    await _setup(hass, entry_1)

    ent_reg = er.async_get(hass)
    device_ids = set()
    for entry, station_id in (
        (entry_1, MOCK_STATION_ID_1),
        (entry_2, MOCK_STATION_ID_2),
    ):
        devices = _devices(hass, entry, _station_device(station_id))
        assert len(devices) == 1
        device_ids.add(devices[0].id)
        for suffix in ("load", "homekit", "import-energy-total"):
            entity_id = _entity_id(hass, f"{_station_serial(station_id)}-{suffix}")
            assert entity_id is not None
            registry_entry = ent_reg.async_get(entity_id)
            assert registry_entry is not None
            assert registry_entry.config_entry_id == entry.entry_id
            assert registry_entry.device_id == devices[0].id
            assert hass.states.get(entity_id) is not None
        assert _devices(hass, entry, LEGACY_DEVICE) == []

    assert len(device_ids) == 2
    assert _entity_id(hass, f"{LEGACY_SERIAL}-load") is None


@pytest.mark.parametrize("owner_first", [True, False])
async def test_migration_keeps_history_of_the_owning_station(
    hass: HomeAssistant, owner_first: bool
) -> None:
    """The station owning the shared IDs keeps its entity IDs and device."""
    owner = _entry(MOCK_STATION_ID_1)
    other = _entry(MOCK_STATION_ID_2)
    for entry in (owner, other) if owner_first else (other, owner):
        entry.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    legacy_device = _legacy_device(hass, owner)
    _legacy_device(hass, other)
    dev_reg.async_update_device(legacy_device.id, name_by_user="Home powerflow")
    legacy_entity_ids = _add_legacy_entities(
        hass, owner, LEGACY_SERIAL, legacy_device.id
    )

    await _setup(hass, owner)

    ent_reg = er.async_get(hass)
    owner_serial = _station_serial(MOCK_STATION_ID_1)
    for suffix, entity_id in legacy_entity_ids.items():
        registry_entry = ent_reg.async_get(entity_id)
        assert registry_entry is not None
        assert registry_entry.unique_id == f"{owner_serial}-{suffix}"
        assert registry_entry.config_entry_id == owner.entry_id
        assert registry_entry.device_id == legacy_device.id
        assert hass.states.get(entity_id) is not None
    # The lifetime counter keeps receiving data under its old entity ID.
    total_state = hass.states.get(legacy_entity_ids["import-energy-total"])
    assert total_state is not None
    assert float(total_state.state) == 100.0

    owner_device = dev_reg.async_get(legacy_device.id)
    assert owner_device is not None
    assert owner_device.identifiers == {_station_device(MOCK_STATION_ID_1)}
    assert owner_device.name_by_user == "Home powerflow"
    assert _devices(hass, owner, LEGACY_DEVICE) == []
    assert _devices(hass, other, LEGACY_DEVICE) == []
    assert _devices(hass, other, _station_device(MOCK_STATION_ID_1)) == []

    other_load = _entity_id(hass, f"{_station_serial(MOCK_STATION_ID_2)}-load")
    assert other_load is not None
    assert other_load not in legacy_entity_ids.values()
    other_entry = ent_reg.async_get(other_load)
    assert other_entry is not None
    assert other_entry.config_entry_id == other.entry_id
    other_devices = _devices(hass, other, _station_device(MOCK_STATION_ID_2))
    assert len(other_devices) == 1
    assert other_entry.device_id == other_devices[0].id != legacy_device.id
    assert _entity_id(hass, f"{LEGACY_SERIAL}-load") is None


async def test_migration_is_idempotent(hass: HomeAssistant) -> None:
    """Reloading after the migration changes nothing in the registries."""
    owner = _entry(MOCK_STATION_ID_1)
    other = _entry(MOCK_STATION_ID_2)
    owner.add_to_hass(hass)
    other.add_to_hass(hass)
    legacy_device = _legacy_device(hass, owner)
    _legacy_device(hass, other)
    _add_legacy_entities(hass, owner, LEGACY_SERIAL, legacy_device.id)

    await _setup(hass, owner)
    entities_before = _entity_snapshot(hass)
    devices_before = _device_snapshot(hass, owner, other)

    await _reload(hass, owner, other)

    assert _entity_snapshot(hass) == entities_before
    assert _device_snapshot(hass, owner, other) == devices_before


async def test_single_station_keeps_entity_ids_and_device(hass: HomeAssistant) -> None:
    """A single-station account keeps its entities, states and device."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    legacy_device = _legacy_device(hass, entry)
    legacy_entity_ids = _add_legacy_entities(
        hass, entry, LEGACY_SERIAL, legacy_device.id
    )

    await _setup(hass, entry)

    ent_reg = er.async_get(hass)
    homekit_entities = [
        entity
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        if entity.unique_id.startswith(_station_serial(MOCK_STATION_ID_1))
    ]
    # No duplicates: every HomeKit entity lives on the one (renamed) device.
    assert {entity.device_id for entity in homekit_entities} == {legacy_device.id}
    assert {entity.entity_id for entity in homekit_entities} >= set(
        legacy_entity_ids.values()
    )
    for entity_id in legacy_entity_ids.values():
        assert hass.states.get(entity_id) is not None
    device = dr.async_get(hass).async_get(legacy_device.id)
    assert device is not None
    assert device.identifiers == {_station_device(MOCK_STATION_ID_1)}


async def test_single_station_with_meter_serial_is_unchanged(
    hass: HomeAssistant,
) -> None:
    """A station with a smart meter keeps its serial-based unique IDs."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    legacy_device = _legacy_device(hass, entry)
    legacy_entity_ids = _add_legacy_entities(
        hass, entry, "METER-SN-1", legacy_device.id
    )

    def _meter_data(station_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        data = _get_data(station_id)
        data["powerflow"] = {**data["powerflow"], "sn": "METER-SN-1"}
        return data

    with _mock_api(_meter_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    for suffix, entity_id in legacy_entity_ids.items():
        registry_entry = ent_reg.async_get(entity_id)
        assert registry_entry is not None
        assert registry_entry.unique_id == f"METER-SN-1-{suffix}"
        assert registry_entry.device_id == legacy_device.id
        assert hass.states.get(entity_id) is not None
    assert _entity_id(hass, f"{_station_serial(MOCK_STATION_ID_1)}-load") is None


async def test_homekit_devices_of_two_stations_with_serials_are_split(
    hass: HomeAssistant,
) -> None:
    """Stations with HomeKit serials each end up with their own device."""
    entry_1 = _entry(MOCK_STATION_ID_1)
    entry_2 = _entry(MOCK_STATION_ID_2)
    entry_1.add_to_hass(hass)
    entry_2.add_to_hass(hass)
    device_1 = _legacy_device(hass, entry_1)
    device_2 = _legacy_device(hass, entry_2)
    entity_ids_1 = _add_legacy_entities(hass, entry_1, "HOMEKIT-SN-1", device_1.id)
    entity_ids_2 = _add_legacy_entities(hass, entry_2, "HOMEKIT-SN-2", device_2.id)

    await _setup(hass, entry_1)
    # Older HA versions share one device; its links are cleaned up on reload.
    await _reload(hass, entry_1, entry_2)

    ent_reg = er.async_get(hass)
    for entry, station_id, entity_ids in (
        (entry_1, MOCK_STATION_ID_1, entity_ids_1),
        (entry_2, MOCK_STATION_ID_2, entity_ids_2),
    ):
        assert _devices(hass, entry, LEGACY_DEVICE) == []
        devices = _devices(hass, entry, _station_device(station_id))
        assert len(devices) == 1
        for entity_id in entity_ids.values():
            registry_entry = ent_reg.async_get(entity_id)
            assert registry_entry is not None
            assert registry_entry.config_entry_id == entry.entry_id
            assert registry_entry.device_id == devices[0].id


async def test_migration_after_downgrade_keeps_the_station_entities(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Station-scoped IDs created earlier win over IDs of an older release."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    station_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={_station_device(MOCK_STATION_ID_1)},
    )
    station_entity_ids = _add_legacy_entities(
        hass, entry, _station_serial(MOCK_STATION_ID_1), station_device.id
    )
    # A downgrade re-created the old IDs on the old device, without entities.
    legacy_device = _legacy_device(hass, entry)
    legacy_entity_id = (
        er.async_get(hass)
        .async_get_or_create(
            Platform.SENSOR, DOMAIN, f"{LEGACY_SERIAL}-load", config_entry=entry
        )
        .entity_id
    )

    await _setup(hass, entry)

    ent_reg = er.async_get(hass)
    load_entry = ent_reg.async_get(station_entity_ids["load"])
    assert load_entry is not None
    assert load_entry.device_id == station_device.id
    assert ent_reg.async_get(legacy_entity_id).unique_id == f"{LEGACY_SERIAL}-load"
    assert "because the new ID already exists" in caplog.text
    assert dr.async_get(hass).async_get(legacy_device.id) is None
    # The migration logs entity IDs, never the station ID in the unique IDs.
    assert not [
        record
        for record in caplog.records
        if record.levelno >= logging.INFO and MOCK_STATION_ID_1 in record.getMessage()
    ]


async def test_migration_without_station_id_is_skipped(hass: HomeAssistant) -> None:
    """Entries without a station ID are left alone."""
    from custom_components.sems import (
        _async_migrate_station_scoped_homekit,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_USERNAME: "user"})
    entry.add_to_hass(hass)
    legacy_entity_ids = _add_legacy_entities(
        hass, entry, LEGACY_SERIAL, _legacy_device(hass, entry).id
    )

    _async_migrate_station_scoped_homekit(hass, entry)

    ent_reg = er.async_get(hass)
    for suffix, entity_id in legacy_entity_ids.items():
        assert ent_reg.async_get(entity_id).unique_id == f"{LEGACY_SERIAL}-{suffix}"
    assert len(_devices(hass, entry, LEGACY_DEVICE)) == 1


async def test_shared_device_with_entities_of_both_stations_is_kept(
    hass: HomeAssistant,
) -> None:
    """A device still used by another station is neither renamed nor detached."""
    from custom_components.sems import _async_migrate_station_scoped_homekit

    owner = _entry(MOCK_STATION_ID_1)
    other = _entry(MOCK_STATION_ID_2)
    owner.add_to_hass(hass)
    other.add_to_hass(hass)
    legacy_device = _legacy_device(hass, owner)
    _add_legacy_entities(hass, owner, LEGACY_SERIAL, legacy_device.id)
    _add_legacy_entities(hass, other, "OTHER-SERIAL", legacy_device.id)

    _async_migrate_station_scoped_homekit(hass, owner)

    device = dr.async_get(hass).async_get(legacy_device.id)
    assert device is not None
    assert device.identifiers == {LEGACY_DEVICE}
    assert device.config_entry_id == owner.entry_id


async def test_shared_device_of_older_ha_is_unlinked_from_other_stations(
    hass: HomeAssistant,
) -> None:
    """On HA versions with multi-entry devices, the other stations are unlinked."""
    import custom_components.sems as sems

    owner = _entry(MOCK_STATION_ID_1)
    owner.add_to_hass(hass)
    legacy_device = _legacy_device(hass, owner)
    _add_legacy_entities(hass, owner, LEGACY_SERIAL, legacy_device.id)
    dev_reg = dr.async_get(hass)
    update_device = dev_reg.async_update_device
    removed: list[str] = []

    def _update_device(device_id: str, **kwargs: Any) -> Any:
        if "remove_config_entry_id" in kwargs:
            removed.append(kwargs["remove_config_entry_id"])
            return None
        return update_device(device_id, **kwargs)

    with (
        patch.object(
            sems,
            "_device_config_entry_ids",
            return_value={owner.entry_id, "other-entry"},
        ),
        patch.object(dev_reg, "async_update_device", side_effect=_update_device),
    ):
        sems._async_migrate_station_scoped_homekit(hass, owner)

    assert removed == ["other-entry"]
    device = dev_reg.async_get(legacy_device.id)
    assert device is not None
    assert device.identifiers == {_station_device(MOCK_STATION_ID_1)}


def test_device_config_entry_ids_supports_multi_entry_devices() -> None:
    """Devices without a single config_entry_id report all their entries."""
    from types import SimpleNamespace

    from custom_components.sems import _device_config_entry_ids

    single = SimpleNamespace(config_entry_id="a", config_entries={"a"})
    multi = SimpleNamespace(config_entries={"a", "b"})
    assert _device_config_entry_ids(single) == {"a"}
    assert _device_config_entry_ids(multi) == {"a", "b"}


@pytest.mark.parametrize(
    ("config_entries", "removed"), [({"a", "b"}, False), ({"a"}, True)]
)
def test_detach_device_removes_only_unshared_devices(
    config_entries: set[str], removed: bool
) -> None:
    """Detaching unlinks a shared device and removes a device it alone used."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from custom_components.sems import _async_detach_device

    dev_reg = MagicMock()
    device = SimpleNamespace(id="device", config_entries=config_entries)

    _async_detach_device(dev_reg, device, "a")

    if removed:
        dev_reg.async_remove_device.assert_called_once_with("device")
        dev_reg.async_update_device.assert_not_called()
    else:
        dev_reg.async_update_device.assert_called_once_with(
            "device", remove_config_entry_id="a"
        )
        dev_reg.async_remove_device.assert_not_called()

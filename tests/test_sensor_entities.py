"""Tests for SEMS sensor entities (Home Assistant integration-style)."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems import SemsData
from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from custom_components.sems.sensor import sensor_options_for_data

from .fixtures import (
    MOCK_GET_DATA_ACTUAL_JSON,
    MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON,
)

MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"

# Coordinator-compatible getData() result (this corresponds to SemsApi.getData() return value)
MOCK_GET_DATA_RESULT_MINIMAL = {
    "inverter": [
        {
            "invert_full": {
                "name": "Test Inverter",
                "sn": "GW0000SN000TEST1",
                "powerstation_id": MOCK_POWER_STATION_ID,
                "status": 1,
                "capacity": 3.0,
                "pac": 589,
                "etotal": 18843.2,
                "hour_total": 1234,
                "tempperature": 32.0,
                "eday": 8.9,
                "thismonthetotle": 85.7,
                "lastmonthetotle": 76.8,
                "iday": 1.96,
                "itotal": 4145.5,
            }
        }
    ],
    "kpi": {
        "currency": "EUR",
        "total_power": 18843.2,
    },
    "hasPowerflow": False,
    "hasEnergeStatisticsCharts": False,
}


async def test_sensor_state_from_coordinator(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test that the power sensor is created and has the expected state."""
    del enable_custom_integrations
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=MOCK_GET_DATA_RESULT_MINIMAL,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "GW0000SN000TEST1-power"
    )
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "589"
    assert state.attributes.get("unit_of_measurement") == "W"
    assert state.attributes.get("statusText") == "Normal"
    assert state.attributes.get("pac") == 589

    # extra_state_attributes should only be exposed on the `-power` entity
    assert state.attributes.get("capacity") == 3.0
    assert state.attributes.get("status") == 1

    status_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "GW0000SN000TEST1-status"
    )
    assert status_entity_id is not None

    status_state = hass.states.get(status_entity_id)
    assert status_state is not None
    assert status_state.state == "Normal"
    assert "pac" not in status_state.attributes
    assert "statusText" not in status_state.attributes


async def test_unique_id_migration_sn_to_sn_power(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test migration from old unique_id `sn` to new `sn-power`."""
    del enable_custom_integrations
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    old_entity_id = ent_reg.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        "GW0000SN000TEST1",
        config_entry=entry,
    ).entity_id

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=MOCK_GET_DATA_RESULT_MINIMAL,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    migrated_entry = ent_reg.async_get(old_entity_id)
    assert migrated_entry is not None
    assert migrated_entry.unique_id == "GW0000SN000TEST1-power"


async def test_unique_id_migration_powerflow_to_homekit_sn(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test migration from legacy powerflow unique IDs to HomeKit SN-based IDs."""
    del enable_custom_integrations
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    legacy_unique_ids = [
        "powerflow-import-energy",
        "powerflow-export-energy",
        "powerflow-import-energy-total",
        "powerflow-export-energy-total",
    ]
    legacy_entity_ids = {
        legacy_unique_id: ent_reg.async_get_or_create(
            Platform.SENSOR,
            DOMAIN,
            legacy_unique_id,
            config_entry=entry,
        ).entity_id
        for legacy_unique_id in legacy_unique_ids
    }

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    homekit_sn = (
        MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON.get("homKit", {}).get("sn")
        or "GW-HOMEKIT-NO-SERIAL"
    )
    expected_migrations = {
        "powerflow-import-energy": f"{homekit_sn}-import-energy",
        "powerflow-export-energy": f"{homekit_sn}-export-energy",
        "powerflow-import-energy-total": f"{homekit_sn}-import-energy-total",
        "powerflow-export-energy-total": f"{homekit_sn}-export-energy-total",
    }

    for legacy_unique_id, expected_unique_id in expected_migrations.items():
        migrated_entry = ent_reg.async_get(legacy_entity_ids[legacy_unique_id])
        assert migrated_entry is not None
        assert migrated_entry.unique_id == expected_unique_id


async def test_all_entities_exist(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test that all expected entities are created for the given payload."""
    del enable_custom_integrations

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=MOCK_GET_DATA_ACTUAL_JSON["data"],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    inverter_data = MOCK_GET_DATA_ACTUAL_JSON["data"]["inverter"][0]["invert_full"]
    inverter_sn = inverter_data["sn"]
    data = SemsData(
        inverters={inverter_sn: inverter_data},
        currency=MOCK_GET_DATA_ACTUAL_JSON["data"]["kpi"]["currency"],
    )

    expected_sensor_unique_ids = {
        sensor.unique_id for sensor in sensor_options_for_data(data)
    }
    expected_switch_unique_ids = {f"{inverter_sn}-switch"}
    expected_unique_ids = expected_sensor_unique_ids | expected_switch_unique_ids

    ent_reg = er.async_get(hass)
    actual_unique_ids = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }

    assert actual_unique_ids == expected_unique_ids


async def test_exact_unique_ids_single_inverter_fixture(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test the exact set of unique IDs for the single-inverter fixture."""
    del enable_custom_integrations

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=MOCK_GET_DATA_ACTUAL_JSON["data"],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    sn = MOCK_GET_DATA_ACTUAL_JSON["data"]["inverter"][0]["invert_full"]["sn"]
    expected_unique_ids = {
        f"{sn}-capacity",
        f"{sn}-eday",
        f"{sn}-energy",
        f"{sn}-fac1",
        f"{sn}-fac2",
        f"{sn}-fac3",
        f"{sn}-hour-total",
        f"{sn}-iac1",
        f"{sn}-iac2",
        f"{sn}-iac3",
        f"{sn}-ibattery1",
        f"{sn}-iday",
        f"{sn}-ipv1",
        f"{sn}-ipv2",
        f"{sn}-ipv3",
        f"{sn}-ipv4",
        f"{sn}-itotal",
        f"{sn}-lastmonthetotle",
        f"{sn}-power",
        f"{sn}-status",
        f"{sn}-switch",
        f"{sn}-temperature",
        f"{sn}-thismonthetotle",
        f"{sn}-vac1",
        f"{sn}-vac2",
        f"{sn}-vac3",
        f"{sn}-vbattery1",
        f"{sn}-vpv1",
        f"{sn}-vpv2",
        f"{sn}-vpv3",
        f"{sn}-vpv4",
    }

    ent_reg = er.async_get(hass)
    actual_unique_ids = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }

    assert actual_unique_ids == expected_unique_ids


async def test_exact_unique_ids_homekit_powerflow_fixture(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test the exact set of unique IDs for a HomeKit/powerflow payload."""
    del enable_custom_integrations

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    sn = MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON["inverter"][0]["invert_full"]["sn"]
    homekit_sn = (
        MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON.get("homKit", {}).get("sn")
        or "GW-HOMEKIT-NO-SERIAL"
    )
    expected_unique_ids = {
        # Regular inverter sensors
        f"{sn}-capacity",
        f"{sn}-eday",
        f"{sn}-energy",
        f"{sn}-fac1",
        f"{sn}-fac2",
        f"{sn}-fac3",
        f"{sn}-hour-total",
        f"{sn}-iac1",
        f"{sn}-iac2",
        f"{sn}-iac3",
        f"{sn}-ibattery1",
        f"{sn}-iday",
        f"{sn}-ipv1",
        f"{sn}-ipv2",
        f"{sn}-ipv3",
        f"{sn}-ipv4",
        f"{sn}-itotal",
        f"{sn}-lastmonthetotle",
        f"{sn}-power",
        f"{sn}-status",
        f"{sn}-switch",
        f"{sn}-temperature",
        f"{sn}-thismonthetotle",
        f"{sn}-vac1",
        f"{sn}-vac2",
        f"{sn}-vac3",
        f"{sn}-vbattery1",
        f"{sn}-vpv1",
        f"{sn}-vpv2",
        f"{sn}-vpv3",
        f"{sn}-vpv4",
        # HomeKit/powerflow sensors
        f"{homekit_sn}-homekit",
        f"{homekit_sn}-battery",
        f"{homekit_sn}-genset",
        f"{homekit_sn}-grid",
        f"{homekit_sn}-load-status",
        f"{homekit_sn}-pv",
        f"{homekit_sn}-soc",
        # Import/Export sensors
        f"{homekit_sn}-import-energy",
        f"{homekit_sn}-export-energy",
        f"{homekit_sn}-import-energy-total",
        f"{homekit_sn}-export-energy-total",
    }

    ent_reg = er.async_get(hass)
    actual_unique_ids = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }

    assert actual_unique_ids == expected_unique_ids


async def test_homekit_powerflow_values_from_api_fixture(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test HomeKit/powerflow values extracted from the real API fixture."""
    del enable_custom_integrations

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    homekit_sn = (
        MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON.get("homKit", {}).get("sn")
        or "GW-HOMEKIT-NO-SERIAL"
    )

    load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-homekit"
    )
    assert load_entity_id is not None
    load_state = hass.states.get(load_entity_id)
    assert load_state is not None
    assert float(load_state.state) == 2337.0

    grid_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-grid"
    )
    assert grid_entity_id is not None
    grid_state = hass.states.get(grid_entity_id)
    assert grid_state is not None
    assert float(grid_state.state) == 2337.0

    pv_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-pv"
    )
    assert pv_entity_id is not None
    pv_state = hass.states.get(pv_entity_id)
    assert pv_state is not None
    assert float(pv_state.state) == 0.0

    battery_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-battery"
    )
    assert battery_entity_id is not None
    battery_state = hass.states.get(battery_entity_id)
    assert battery_state is not None
    assert float(battery_state.state) == 0.0

    genset_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-genset"
    )
    assert genset_entity_id is not None
    genset_state = hass.states.get(genset_entity_id)
    assert genset_state is not None
    assert float(genset_state.state) == 0.0

    soc_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-soc"
    )
    assert soc_entity_id is not None
    soc_state = hass.states.get(soc_entity_id)
    assert soc_state is not None
    assert float(soc_state.state) == 0.0

    load_status_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-load-status"
    )
    assert load_status_entity_id is not None
    load_status_state = hass.states.get(load_status_entity_id)
    assert load_status_state is not None
    assert int(float(load_status_state.state)) == -1

    # Verify the import sensor exists and has correct attributes
    import_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-import-energy"
    )
    assert import_entity_id is not None

    import_state = hass.states.get(import_entity_id)
    assert import_state is not None
    assert float(import_state.state) == 5.12
    assert import_state.attributes.get("unit_of_measurement") == "kWh"

    # Verify the export sensor exists and has correct attributes
    export_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-export-energy"
    )
    assert export_entity_id is not None

    export_state = hass.states.get(export_entity_id)
    assert export_state is not None
    assert float(export_state.state) == 23.22
    assert export_state.attributes.get("unit_of_measurement") == "kWh"

    # Verify the total import sensor
    total_import_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-import-energy-total"
    )
    assert total_import_entity_id is not None

    total_import_state = hass.states.get(total_import_entity_id)
    assert total_import_state is not None
    assert float(total_import_state.state) == 3977.33

    # Verify the total export sensor
    total_export_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-export-energy-total"
    )
    assert total_export_entity_id is not None

    total_export_state = hass.states.get(total_export_entity_id)
    assert total_export_state is not None
    assert float(total_export_state.state) == 12901.2


def _build_homekit_test_data(
    inverter_status: int = 1,
    inverter_pac: int = 500,
    inverter_temp: float = 32.0,
    inverter_eday: float = 8.9,
    inverter_iday: float = 1.96,
    total_power: float = 500.0,
    pv_value: str = "100(W)",
    pv_status: int = 1,
    load_value: str = "2337(W)",
    load_status: int = 1,
    grid_value: str = "2337(W)",
    grid_status: int = -1,
    battery_value: str = "0(W)",
    battery_status: int = 0,
    genset_value: str = "0(W)",
    soc: int = 50,
) -> dict:
    """Build test data for homekit sensors with configurable values."""
    return {
        "inverter": [
            {
                "invert_full": {
                    "name": "Test Inverter",
                    "sn": "GW0000SN000TEST1",
                    "powerstation_id": MOCK_POWER_STATION_ID,
                    "status": inverter_status,
                    "capacity": 3.0,
                    "pac": inverter_pac,
                    "etotal": 18843.2,
                    "hour_total": 1234,
                    "tempperature": inverter_temp,
                    "eday": inverter_eday,
                    "thismonthetotle": 85.7,
                    "lastmonthetotle": 76.8,
                    "iday": inverter_iday,
                    "itotal": 4145.5,
                }
            }
        ],
        "kpi": {
            "currency": "EUR",
            "total_power": total_power,
        },
        "hasPowerflow": True,
        "hasEnergeStatisticsCharts": False,
        "homKit": {
            "sn": None,  # Will use GW-HOMEKIT-NO-SERIAL as default
            "homeKitLimit": False,
        },
        "powerflow": {
            "pv": pv_value,
            "pvStatus": pv_status,
            "load": load_value,
            "loadStatus": load_status,
            "grid": grid_value,
            "gridStatus": grid_status,
            "bettery": battery_value,
            "betteryStatus": battery_status,
            "genset": genset_value,
            "soc": soc,
        },
    }


async def test_homekit_sensors_handle_empty_strings_at_night(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test that HomeKit sensors handle empty string values without crashing.

    This simulates the scenario where sensors are first created with valid values,
    then receive empty strings when the inverter goes offline at night.
    """
    del enable_custom_integrations

    # Set up with valid homekit data (daytime)
    initial_data = _build_homekit_test_data()

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=initial_data,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    homekit_sn = "GW-HOMEKIT-NO-SERIAL"  # Default when sn is None

    # Verify entities are created and have values
    load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-homekit"
    )
    assert load_entity_id is not None
    load_state = hass.states.get(load_entity_id)
    assert load_state is not None
    assert float(load_state.state) == 2337.0

    battery_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-battery"
    )
    assert battery_entity_id is not None
    battery_state = hass.states.get(battery_entity_id)
    assert battery_state is not None
    assert float(battery_state.state) == 0.0

    # Simulate nighttime with empty strings - this was causing the crash
    nighttime_data = _build_homekit_test_data(
        inverter_status=-1,  # Offline
        inverter_pac=0,
        inverter_temp=0.0,
        inverter_eday=0.0,
        inverter_iday=0.0,
        total_power=0.0,
        pv_value="",  # Empty string when offline
        pv_status=0,
        load_value="",  # Empty string when offline
        grid_value="-817(W)",
        battery_value="",  # Empty string when offline
        genset_value="",
        soc=0,
    )

    # Update coordinator data with nighttime empty strings
    coordinator = entry.runtime_data.coordinator
    with patch(
        "custom_components.sems.sems_api.SemsApi.getData",
        return_value=nighttime_data,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    # The sensors should now be unknown (not crash) when values are empty strings
    load_state = hass.states.get(load_entity_id)
    assert load_state is not None
    assert load_state.state == "unknown"

    battery_state = hass.states.get(battery_entity_id)
    assert battery_state is not None
    assert battery_state.state == "unknown"

    # Load status sensor still has valid status values (not empty strings)
    # so it should have a numeric value
    load_status_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-load-status"
    )
    assert load_status_entity_id is not None
    load_status_state = hass.states.get(load_status_entity_id)
    assert load_status_state is not None
    # loadStatus=1 * gridStatus=-1 = -1
    assert load_status_state.state == "-1"

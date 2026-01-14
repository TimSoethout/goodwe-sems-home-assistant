"""Tests for SEMS sensor entities (Home Assistant integration-style)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from custom_components.sems import SemsData
from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from custom_components.sems.sensor import sensor_options_for_data
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def _load_json_fixture(relative_path: str) -> dict[str, Any]:
    fixture_path = Path(__file__).resolve().parent / relative_path
    return json.loads(fixture_path.read_text(encoding="utf-8"))


MOCK_GET_DATA_ACTUAL_JSON: dict[str, Any] = _load_json_fixture(
    "test-data/20260110_singleInverter_getData.json"
)

# Coordinator-compatible getData() result that includes HomeKit/powerflow data.
MOCK_HOMEKIT_GET_DATA: dict[str, Any] = {
    "inverter": [
        {
            "invert_full": {
                "name": "Test Inverter",
                "sn": "GW0000SN000TEST1",
                "powerstation_id": "12345678-1234-5678-9abc-123456789abc",
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
    "homKit": {
        "homeKitLimit": False,
        "sn": None,
    },
    "hasPowerflow": True,
    "hasEnergeStatisticsCharts": False,
    "powerflow": {
        "pv": "0(W)",
        "pvStatus": 0,
        "load": "100(W)",
        "loadStatus": 1,
        "grid": "100(W)",
        "gridStatus": -1,
        "bettery": "0(W)",
        "betteryStatus": 0,
        "genset": "0(W)",
        "soc": 0,
    },
}

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
        return_value=MOCK_HOMEKIT_GET_DATA,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    sn = MOCK_HOMEKIT_GET_DATA["inverter"][0]["invert_full"]["sn"]
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
        # HomeKit/powerflow sensors (no HomeKit serial -> fallback to `powerflow`)
        "powerflow",
        "powerflow-battery",
        "powerflow-genset",
        "powerflow-grid",
        "powerflow-load-status",
        "powerflow-pv",
        "powerflow-soc",
    }

    ent_reg = er.async_get(hass)
    actual_unique_ids = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }

    assert actual_unique_ids == expected_unique_ids

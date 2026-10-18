"""Tests for SEMS sensor entities (Home Assistant integration-style)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems import (
    SemsData,
    SemsDataUpdateCoordinator,
    _normalize_energy_statistics_charts,
)
from custom_components.sems.const import (
    CONF_STATION_ID,
    DOMAIN,
    homekit_station_serial,
)
from custom_components.sems.sems_api import SemsApi
from custom_components.sems.sensor import (
    convert_status_to_label,
    sensor_options_for_data,
)

from .fixtures import (
    MOCK_GET_DATA_ACTUAL_JSON,
    MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON,
)

MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"
# Powerflow serial of a station without a HomeKit/smart meter serial.
MOCK_STATION_SERIAL = homekit_station_serial(MOCK_POWER_STATION_ID)


def test_status_code_5_is_normal() -> None:
    """Test that the SEMS+ active status code is mapped to Normal."""
    assert convert_status_to_label(5) == "Normal"


def test_status_code_3_is_waiting() -> None:
    """Test that the SEMS+ non-producing status code is mapped to Waiting."""
    assert convert_status_to_label(3) == "Waiting"


def test_normalize_energy_statistics_charts_wh_values() -> None:
    """Convert chart values returned in Wh to the kWh sensor unit."""
    charts = {
        "sum": 40633.4,
        "consumptionOfLoad": 40633.4,
        "buy": 0.27,
        "contributingRate": 0.5,
    }

    normalized = _normalize_energy_statistics_charts(charts, 3.0)

    assert normalized["sum"] == 40.6334
    assert normalized["consumptionOfLoad"] == 40.6334
    assert normalized["buy"] == 0.27
    assert normalized["contributingRate"] == 0.5
    assert charts["sum"] == 40633.4


def test_normalize_energy_statistics_charts_preserves_large_kwh_values() -> None:
    """Do not convert values that are plausible for the station capacity."""
    charts = {"sum": 40633.4}

    normalized = _normalize_energy_statistics_charts(charts, 2000.0)

    assert normalized == charts


@contextmanager
def _mock_no_battery_api(data: dict):
    """Mock coordinator API calls for payloads without battery controls."""
    with (
        patch("custom_components.sems.sems_api.SemsApi.getData", return_value=data),
        patch(
            "custom_components.sems.sems_api.SemsApi.getEnergyStorageIntegratedCabinets",
            return_value=[],
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryGeneralFunctions",
            return_value={},
        ),
    ):
        yield


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

    with _mock_no_battery_api(MOCK_GET_DATA_RESULT_MINIMAL):
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


@pytest.mark.parametrize("enabled", [True, False])
async def test_last_month_energy_is_requested_only_when_enabled(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    enabled: bool,
) -> None:
    """Fetch previous-month statistics once the user enabled that sensor."""
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
    registry_entry = ent_reg.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        "GW0000SN000TEST1-lastmonthetotle",
        config_entry=entry,
        disabled_by=None if enabled else er.RegistryEntryDisabler.INTEGRATION,
    )
    data_without_last_month = {
        **MOCK_GET_DATA_RESULT_MINIMAL,
        "inverter": [
            {
                "invert_full": {
                    key: value
                    for key, value in MOCK_GET_DATA_RESULT_MINIMAL["inverter"][0][
                        "invert_full"
                    ].items()
                    if key != "lastmonthetotle"
                }
            }
        ],
    }

    def get_data(*_args, include_last_month: bool = False, **_kwargs):
        return (
            MOCK_GET_DATA_RESULT_MINIMAL
            if include_last_month
            else data_without_last_month
        )

    with (
        _mock_no_battery_api(MOCK_GET_DATA_RESULT_MINIMAL),
        patch(
            "custom_components.sems.sems_api.SemsApi.getData",
            side_effect=get_data,
        ) as mock_get_data,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert mock_get_data.call_args.kwargs == {"include_last_month": enabled}
    if enabled:
        state = hass.states.get(registry_entry.entity_id)
        assert state is not None
        assert float(state.state) == pytest.approx(76.8)


async def test_last_month_energy_is_not_requested_without_config_entry(
    hass: HomeAssistant,
) -> None:
    """Without a config entry there is no registry to check, so skip the request."""
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
    coordinator = SemsDataUpdateCoordinator(hass, SemsApi(hass, "user", "pass"), entry)
    coordinator.config_entry = None

    assert coordinator._last_month_energy_requested() is False


async def test_failed_inverter_telemetry_marks_only_its_sensors_unavailable(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Mark telemetry sensors unavailable without hiding successful counters."""
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

    with _mock_no_battery_api(MOCK_GET_DATA_RESULT_MINIMAL):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    coordinator.async_set_updated_data(
        SemsData(
            inverters={
                "GW0000SN000TEST1": {
                    "etotal": 18843.2,
                }
            },
            unavailable_inverter_sources={
                "GW0000SN000TEST1": {"device_status", "telemetry"},
            },
        )
    )
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    power_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "GW0000SN000TEST1-power"
    )
    status_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "GW0000SN000TEST1-status"
    )
    energy_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "GW0000SN000TEST1-energy"
    )
    assert power_entity_id is not None
    assert status_entity_id is not None
    assert energy_entity_id is not None
    assert hass.states.get(power_entity_id).state == "unavailable"
    assert hass.states.get(status_entity_id).state == "unavailable"
    assert float(hass.states.get(energy_entity_id).state) == 18843.2

    coordinator.async_set_updated_data(
        SemsData(
            inverters={
                "GW0000SN000TEST1": {
                    "pac": 589,
                    "status": 1,
                }
            },
            unavailable_inverter_sources={
                "GW0000SN000TEST1": {"counters"},
            },
        )
    )
    await hass.async_block_till_done()

    assert hass.states.get(power_entity_id).state == "589"
    assert hass.states.get(status_entity_id).state == "Normal"
    assert hass.states.get(energy_entity_id).state == "unavailable"


@pytest.mark.parametrize(
    ("unavailable_data_sources", "expected_disabled_by"),
    [
        ({}, er.RegistryEntryDisabler.INTEGRATION),
        ({"inverters": {"GW0000SN000TEST1": {"counters"}}}, None),
    ],
)
async def test_sensor_not_disabled_when_its_source_failed_at_setup(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    unavailable_data_sources: dict[str, Any],
    expected_disabled_by: er.RegistryEntryDisabler | None,
) -> None:
    """Only disable a missing sensor by default when its source answered."""
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

    # The fixture has no `eyear`, so Energy This Year has no initial value.
    with _mock_no_battery_api(
        {
            **MOCK_GET_DATA_RESULT_MINIMAL,
            "unavailable_data_sources": unavailable_data_sources,
        }
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "GW0000SN000TEST1-eyear"
    )
    assert entity_id is not None
    entity_entry = ent_reg.async_get(entity_id)
    assert entity_entry is not None
    assert entity_entry.disabled_by is expected_disabled_by


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

    with _mock_no_battery_api(MOCK_GET_DATA_RESULT_MINIMAL):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    migrated_entry = ent_reg.async_get(old_entity_id)
    assert migrated_entry is not None
    assert migrated_entry.unique_id == "GW0000SN000TEST1-power"


async def test_web_meter_data_keeps_registered_homekit_serial(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test SEMS+ meter data updates earlier HomeKit entities, not duplicates."""
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
    existing_entity_id = ent_reg.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        "GW-HOMEKIT-NO-SERIAL-import-energy-total",
        config_entry=entry,
    ).entity_id

    # SEMS+ Web data: no "homKit" key and the smart meter SN on the powerflow.
    web_data = {
        "inverter": MOCK_GET_DATA_RESULT_MINIMAL["inverter"],
        "hasPowerflow": True,
        "powerflow": {"sn": "METER-SN-1", "grid": -1351.0, "load": 1351.0},
        "hasEnergeStatisticsCharts": True,
        "energeStatisticsCharts": {"buy": 12.84, "sell": 36.77},
        "energeStatisticsTotals": {"buy": 20314.77, "sell": 38846.49},
    }
    with _mock_no_battery_api(web_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(existing_entity_id)
    assert state is not None
    assert float(state.state) == 20314.77
    export_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{MOCK_STATION_SERIAL}-export-energy"
    )
    assert export_entity_id is not None
    assert float(hass.states.get(export_entity_id).state) == 36.77
    assert (
        ent_reg.async_get_entity_id(
            Platform.SENSOR, DOMAIN, "METER-SN-1-import-energy-total"
        )
        is None
    )


async def test_failed_smart_meter_telemetry_marks_only_meter_sensors_unavailable(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Keep station-flow sensors available when smart-meter telemetry fails."""
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

    web_data = {
        "inverter": MOCK_GET_DATA_RESULT_MINIMAL["inverter"],
        "hasPowerflow": True,
        "powerflow": {
            "sn": "METER-SN-1",
            "grid": -1351,
            "load": 1351,
            "meter_power": 1234,
        },
    }
    with _mock_no_battery_api(web_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    inverter = MOCK_GET_DATA_RESULT_MINIMAL["inverter"][0]["invert_full"]
    coordinator = entry.runtime_data.coordinator
    coordinator.async_set_updated_data(
        SemsData(
            inverters={inverter["sn"]: inverter},
            homekit={"sn": "METER-SN-1", "load": 1351},
            unavailable_homekit_sources={"telemetry"},
        )
    )
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    meter_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "METER-SN-1-meter_power"
    )
    load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "METER-SN-1-load"
    )
    assert meter_entity_id is not None
    assert load_entity_id is not None
    assert hass.states.get(meter_entity_id).state == "unavailable"
    assert hass.states.get(load_entity_id).state == "1351"


async def test_failed_refresh_marks_inverter_and_homekit_sensors_unavailable(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Mark sensors unavailable when the whole coordinator refresh failed."""
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

    web_data = {
        "inverter": MOCK_GET_DATA_RESULT_MINIMAL["inverter"],
        "hasPowerflow": True,
        "powerflow": {"sn": "METER-SN-1", "load": 1351},
    }
    with _mock_no_battery_api(web_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    power_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "GW0000SN000TEST1-power"
    )
    load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, "METER-SN-1-load"
    )
    assert power_entity_id is not None
    assert load_entity_id is not None
    assert hass.states.get(power_entity_id).state == "589"
    assert hass.states.get(load_entity_id).state == "1351"

    coordinator = entry.runtime_data.coordinator
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(power_entity_id).state == "unavailable"
    assert hass.states.get(load_entity_id).state == "unavailable"


async def test_registered_homekit_sn_prefers_earlier_lifetime_serial(
    hass: HomeAssistant,
) -> None:
    """Test the earlier HomeKit serial with a lifetime import counter is kept."""
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
    for platform, unique_id in (
        (Platform.SWITCH, "SWITCH-SN-import-energy-total"),
        (Platform.SENSOR, "unrelated-sensor"),
        (Platform.SENSOR, "powerflow-import-energy-total"),
        (Platform.SENSOR, "OLD-SN-export-energy"),
        (Platform.SENSOR, "LIFETIME-SN-import-energy-total"),
        (Platform.SENSOR, "METER-SN-import-energy-total"),
    ):
        ent_reg.async_get_or_create(platform, DOMAIN, unique_id, config_entry=entry)

    coordinator = SemsDataUpdateCoordinator(hass, SemsApi(hass, "user", "pass"), entry)

    assert coordinator._registered_homekit_sn("METER-SN") == "LIFETIME-SN"
    assert coordinator._registered_homekit_sn("LIFETIME-SN") == "METER-SN"

    coordinator.config_entry = None
    assert coordinator._registered_homekit_sn("METER-SN") is None


async def test_web_flow_load_sensors_report_consumption_while_exporting(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test SEMS+ load sensors stay positive and non-zero while exporting."""
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

    web_data = {
        "inverter": MOCK_GET_DATA_RESULT_MINIMAL["inverter"],
        "hasPowerflow": True,
        "powerflow": SemsApi._normalize_web_homekit_data(
            {"pSystem": 3.03, "pGrid": 2.53, "pConsum": -0.5}
        ),
    }
    with _mock_no_battery_api(web_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    for suffix in ("-load", "-homekit"):
        entity_id = ent_reg.async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{MOCK_STATION_SERIAL}{suffix}"
        )
        assert entity_id is not None
        assert float(hass.states.get(entity_id).state) == 500.0


async def test_web_flow_battery_and_grid_signs_from_captured_samples(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Check signed Home Assistant power states against captured SEMS+ flows."""
    del enable_custom_integrations

    fixture_path = (
        Path(__file__).parent.parent
        / "api_examples"
        / "station_flow_battery_directions.json"
    )
    with fixture_path.open(encoding="utf-8") as fixture:
        samples = json.load(fixture)["samples"]

    initial_homekit = SemsApi._normalize_web_homekit_data(samples[0]["flow"])
    web_data = {
        "inverter": MOCK_GET_DATA_RESULT_MINIMAL["inverter"],
        "hasPowerflow": True,
        "powerflow": initial_homekit,
    }
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

    with _mock_no_battery_api(web_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    battery_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{MOCK_STATION_SERIAL}-battery"
    )
    grid_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{MOCK_STATION_SERIAL}-grid"
    )
    assert battery_entity_id is not None
    assert grid_entity_id is not None

    coordinator = entry.runtime_data.coordinator
    for sample in samples:
        flow = sample["flow"]
        normalized_flow = SemsApi._normalize_web_homekit_data(flow)
        coordinator.async_set_updated_data(
            SemsData(inverters={}, homekit=normalized_flow)
        )
        await hass.async_block_till_done()

        battery_state = hass.states.get(battery_entity_id)
        grid_state = hass.states.get(grid_entity_id)
        assert battery_state is not None
        assert grid_state is not None
        assert float(battery_state.state) == pytest.approx(-float(flow["pBat"]) * 1000)
        assert float(grid_state.state) == pytest.approx(float(flow["pGrid"]) * 1000)
        if reported_values := sample.get("reported_local_sensor_values_w"):
            assert round(float(battery_state.state)) == reported_values["battery"]
            assert round(float(grid_state.state)) == reported_values["grid"]


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

    with _mock_no_battery_api(MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    homekit_sn = (
        MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON.get("homKit", {}).get("sn")
        or MOCK_STATION_SERIAL
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

    with _mock_no_battery_api(MOCK_GET_DATA_ACTUAL_JSON["data"]):
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

    with _mock_no_battery_api(MOCK_GET_DATA_ACTUAL_JSON["data"]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    sn = MOCK_GET_DATA_ACTUAL_JSON["data"]["inverter"][0]["invert_full"]["sn"]
    expected_unique_ids = {
        f"{sn}-capacity",
        f"{sn}-eday",
        f"{sn}-eweek",
        f"{sn}-eyear",
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
        f"{sn}-ppv1",
        f"{sn}-ppv2",
        f"{sn}-ppv3",
        f"{sn}-ppv4",
        # Per-inverter meter and energy data
        f"{sn}-pmeter",
        f"{sn}-eChargeDay",
        f"{sn}-eDischargeDay",
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

    with _mock_no_battery_api(MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    sn = MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON["inverter"][0]["invert_full"]["sn"]
    homekit_sn = (
        MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON.get("homKit", {}).get("sn")
        or MOCK_STATION_SERIAL
    )
    expected_unique_ids = {
        # Regular inverter sensors
        f"{sn}-capacity",
        f"{sn}-eday",
        f"{sn}-eweek",
        f"{sn}-eyear",
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
        f"{sn}-ppv1",
        f"{sn}-ppv2",
        f"{sn}-ppv3",
        f"{sn}-ppv4",
        # HomeKit/powerflow sensors
        f"{homekit_sn}-homekit",
        f"{homekit_sn}-load",
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
        # Daily energy statistics
        f"{homekit_sn}-daily-load-consumption",
        f"{homekit_sn}-daily-self-use",
        f"{homekit_sn}-daily-battery-charge",
        f"{homekit_sn}-daily-battery-discharge",
        f"{homekit_sn}-daily-self-sufficiency-rate",
        f"{homekit_sn}-daily-self-use-rate",
        # Total energy statistics
        f"{homekit_sn}-total-load-consumption",
        f"{homekit_sn}-total-self-use",
        f"{homekit_sn}-total-battery-charge",
        f"{homekit_sn}-total-battery-discharge",
        f"{homekit_sn}-total-self-sufficiency-rate",
        f"{homekit_sn}-total-self-use-rate",
        # Per-inverter meter and energy data
        f"{sn}-pmeter",
        f"{sn}-eChargeDay",
        f"{sn}-eDischargeDay",
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

    with _mock_no_battery_api(MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    homekit_sn = (
        MOCK_GET_DATA_HOMEKIT_ACTUAL_JSON.get("homKit", {}).get("sn")
        or MOCK_STATION_SERIAL
    )

    load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-homekit"
    )
    assert load_entity_id is not None
    load_state = hass.states.get(load_entity_id)
    assert load_state is not None
    # `-homekit` follows legacy powerflow behavior: return 0 unless gridStatus == 1
    assert float(load_state.state) == 0.0
    assert load_state.attributes.get("pv") == "0"
    assert load_state.attributes.get("bettery") == "0"
    assert load_state.attributes.get("load") == "2337"
    assert load_state.attributes.get("grid") == "2337"
    assert load_state.attributes.get("statusText") == "Offline"
    assert load_state.attributes.get("PowerFlowDirection") == "Import 2337(W)"

    load_alias_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-load"
    )
    assert load_alias_entity_id is not None
    load_alias_state = hass.states.get(load_alias_entity_id)
    assert load_alias_state is not None
    assert float(load_alias_state.state) == 2337.0

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

    # Verify daily load consumption sensor
    daily_load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-daily-load-consumption"
    )
    assert daily_load_entity_id is not None
    daily_load_state = hass.states.get(daily_load_entity_id)
    assert daily_load_state is not None
    assert float(daily_load_state.state) == 12.2
    assert daily_load_state.attributes.get("unit_of_measurement") == "kWh"

    # Verify daily self use sensor
    daily_self_use_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-daily-self-use"
    )
    assert daily_self_use_entity_id is not None
    daily_self_use_state = hass.states.get(daily_self_use_entity_id)
    assert daily_self_use_state is not None
    assert float(daily_self_use_state.state) == 7.08

    # Verify total load consumption sensor
    total_load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-total-load-consumption"
    )
    assert total_load_entity_id is not None
    total_load_state = hass.states.get(total_load_entity_id)
    assert total_load_state is not None
    assert float(total_load_state.state) == 7927.13

    # Verify daily self-sufficiency rate (0.5803 → 58.03%)
    daily_sufficiency_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-daily-self-sufficiency-rate"
    )
    assert daily_sufficiency_entity_id is not None
    daily_sufficiency_state = hass.states.get(daily_sufficiency_entity_id)
    assert daily_sufficiency_state is not None
    assert float(daily_sufficiency_state.state) == 58.03
    assert daily_sufficiency_state.attributes.get("unit_of_measurement") == "%"


@pytest.mark.parametrize(
    "inverter_data",
    [None, []],
    ids=["missing-inverter-list", "empty-inverter-list"],
)
async def test_homekit_only_station_without_inverters(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    inverter_data: list[dict[str, object]] | None,
) -> None:
    """Set up HomeKit sensors from captured SEMS+ flow without inverter data."""
    del enable_custom_integrations
    flow_fixture = Path(__file__).parent.parent / "api_examples" / "station_flow.json"
    with flow_fixture.open(encoding="utf-8") as fixture:
        flow = json.load(fixture)["data"]

    payload: dict[str, Any] = {
        "hasPowerflow": True,
        "hasEnergeStatisticsCharts": False,
        "powerflow": SemsApi._normalize_web_homekit_data(flow),
    }
    if inverter_data is not None:
        payload["inverter"] = inverter_data

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

    with _mock_no_battery_api(payload):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    pv_entity_id = er.async_get(hass).async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{MOCK_STATION_SERIAL}-pv"
    )
    assert pv_entity_id is not None
    pv_state = hass.states.get(pv_entity_id)
    assert pv_state is not None
    assert float(pv_state.state) == 2280
    coordinator_data = entry.runtime_data.coordinator.data
    assert coordinator_data is not None
    assert coordinator_data.inverters == {}
    assert entry.state is ConfigEntryState.LOADED


async def test_no_inverter_or_powerflow_data_fails_setup(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Do not treat a response with no inverter or powerflow data as success."""
    del enable_custom_integrations
    payload = {
        "inverter": [],
        "hasPowerflow": False,
        "hasEnergeStatisticsCharts": False,
    }

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

    with _mock_no_battery_api(payload):
        assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_invalid_inverter_data_fails_setup(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Reject malformed inverter data even when powerflow is available."""
    del enable_custom_integrations
    payload = {
        "inverter": "invalid",
        "hasPowerflow": True,
        "powerflow": {},
    }

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

    with _mock_no_battery_api(payload):
        assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_RETRY


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
            "sn": None,  # Falls back to the station-scoped serial
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

    with _mock_no_battery_api(initial_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    homekit_sn = MOCK_STATION_SERIAL  # Default when sn is None

    # Verify entities are created and have values
    load_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-homekit"
    )
    assert load_entity_id is not None
    load_state = hass.states.get(load_entity_id)
    assert load_state is not None
    assert float(load_state.state) == 0.0

    load_alias_entity_id = ent_reg.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{homekit_sn}-load"
    )
    assert load_alias_entity_id is not None
    load_alias_state = hass.states.get(load_alias_entity_id)
    assert load_alias_state is not None
    assert float(load_alias_state.state) == 2337.0

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
    with _mock_no_battery_api(nighttime_data):
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


@pytest.mark.parametrize(
    ("telemetry_capture", "counter_capture"),
    [
        ("telemetry.json", "telecounting.json"),
        (
            "semsplus_hybrid/inverter_telemetry.json",
            "semsplus_hybrid/inverter_telecounting.json",
        ),
    ],
)
def test_web_inverter_skips_sensors_without_sems_plus_source(
    telemetry_capture: str, counter_capture: str
) -> None:
    """Do not create legacy sensors that SEMS+ responses never fill."""
    api_examples = Path(__file__).parent.parent / "api_examples"

    def capture(name: str) -> object:
        return json.loads((api_examples / name).read_text(encoding="utf-8"))["data"]

    api = SemsApi(None, "user", "pass")  # type: ignore[arg-type]
    with patch.object(
        api,
        "_make_api_call",
        side_effect=[capture(telemetry_capture), capture(counter_capture)],
    ):
        inverter = {
            "sn": "INV1",
            "name": "Inverter",
            **api.getWebInverterTelemetry("station", "INV1"),
            **api.getWebInverterTelecounting("station", "INV1"),
        }

    unique_ids = {
        sensor.unique_id
        for sensor in sensor_options_for_data(SemsData(inverters={"INV1": inverter}))
    }

    for field in (
        "iday",
        "itotal",
        "vbattery1",
        "ibattery1",
        "iac2",
        "iac3",
        "fac2",
        "fac3",
    ):
        assert f"INV1-{field}" not in unique_ids
    # Fields with a SEMS+ mapping keep their entities even while a value is
    # missing, so IDs stay stable across night-time telemetry gaps.
    for field in ("iac1", "fac1", "vac1", "vac2", "vac3", "lastmonthetotle"):
        assert f"INV1-{field}" in unique_ids


def test_legacy_inverter_fields_keep_their_sensors() -> None:
    """Payloads that carry the legacy fields keep their sensors and IDs."""
    data = SemsData(
        inverters={
            "INV1": {
                "sn": "INV1",
                "iday": 1.5,
                "itotal": 842.5,
                "vbattery1": 0.0,
                "ibattery1": 0.0,
                "iac2": 0.0,
                "fac3": 50.01,
            }
        }
    )

    unique_ids = {sensor.unique_id for sensor in sensor_options_for_data(data)}

    assert {
        "INV1-iday",
        "INV1-itotal",
        "INV1-vbattery1",
        "INV1-ibattery1",
        "INV1-iac2",
        "INV1-fac3",
    } <= unique_ids

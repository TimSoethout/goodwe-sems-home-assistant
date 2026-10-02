"""Tests for GoodWe EV charger (HCA wallbox) support via SEMS+ Web."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from custom_components.sems.ev_charger import (
    EvChargeModeSelect,
    EvChargerChargingSwitch,
    EvChargerConfigNumber,
    EvChargerConfigSwitch,
    EvChargerFactorSensor,
    EvChargerPlugSensor,
    EvChargerSessionSensor,
    EvChargerStatusSensor,
    ev_charger_sensors,
)
from custom_components.sems.sems_api import (
    OutOfRetries,
    SemsApi,
    SemsPermissionError,
)

STATION_ID = "12345678-1234-5678-9abc-123456789abc"
CHARGER_SN = "EVC0000SN0TEST1"

ALL_STATUS = {
    "deviceDetailList": [
        {
            "deviceType": "EV_CHARGER",
            "statusDetailList": [
                {
                    "status": 1,
                    "snList": [CHARGER_SN],
                    "detailMap": {
                        CHARGER_SN: {
                            "sn": CHARGER_SN,
                            "name": "Wallbox",
                            "subtype": "GW11K-HCA-20",
                        }
                    },
                }
            ],
        }
    ]
}
TELEMETRY = [
    {
        "code": "runtime",
        "factors": [
            {
                "code": "Charging_Power",
                "data": "7.2",
                "unit": "kW",
                "alias": "charging_power",
            },
            {"code": "PHASE-A:voltage", "data": "231.5", "unit": "V"},
            {"code": "firmware", "data": "V1.2", "unit": ""},
        ],
    }
]
TELECOUNTING = [
    {
        "code": "telecounting_lifetime",
        "factors": [
            {
                "code": "sessionEnergy",
                "data": "12.5",
                "unit": "kWh",
                "alias": "session_energy",
            }
        ],
    }
]
MODE_INFO = {
    "productModel": "GW11K-HCA-20",
    "ratedPower": 11,
    "controlItemRanges": {"Buy_Pwr_Limit": {"min": 0, "max": 40}},
}
DETAIL = {
    "chargeMode": 1,
    "chargeMaxPower": 11,
    "ratedMaxiChargePower": 11,
    "buyPwrLimit": 0,
    "ensureMinimumChargingPower": 0,
    "gridControlLimitSwitch": 0,
    "dynamicLoad": 0,
    "phaseSwitch": 1,
    "chargedNow": 0,
}
LAST_CHARGE = {"chargeLog": {"workStu": 6, "status": 1}}


def _fake_api_call(url_part, *args, **kwargs):
    if "all-status" in url_part:
        return ALL_STATUS
    if f"{CHARGER_SN}/telemetry" in url_part:
        assert "deviceType=EV_CHARGER" in url_part
        return TELEMETRY
    if f"{CHARGER_SN}/telecounting" in url_part:
        return TELECOUNTING
    if "control-item-content-list" in url_part:
        return MODE_INFO
    if url_part == "/sems-remote/api/ev-charger/detail":
        assert json.loads(kwargs["data"]) == {
            "sn": CHARGER_SN,
            "productModel": "GW11K-HCA-20",
        }
        return DETAIL
    if "chargePile/getLastCharge" in url_part:
        assert f"chargeSn={CHARGER_SN}" in url_part
        return LAST_CHARGE
    return None


def _web_api() -> SemsApi:
    return SemsApi(Mock(), "user", "pass")


@patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
@patch.object(SemsApi, "getWebStationFlow", return_value={"pEvChar": 7.2})
def test_get_web_data_collects_ev_charger(mock_flow, mock_statistics):
    """Test an EV_CHARGER device is read separately from inverters."""
    with patch.object(SemsApi, "_make_api_call", side_effect=_fake_api_call):
        result = _web_api().getWebData(STATION_ID)

    assert result["inverter"] == []
    charger = result["ev_chargers"][CHARGER_SN]
    assert charger["name"] == "Wallbox"
    assert charger["mode_info"] == MODE_INFO
    assert charger["detail"] == DETAIL
    assert charger["charging_power"] == 7200
    assert charger["charge_log"] == {"workStu": 6, "status": 1}
    assert charger["factors"] == {
        "Charging_Power": {"value": 7.2, "unit": "kW", "alias": "charging_power"},
        "PHASE-A:voltage": {"value": 231.5, "unit": "V", "alias": "PHASE-A:voltage"},
        "sessionEnergy": {"value": 12.5, "unit": "kWh", "alias": "session_energy"},
    }


def test_ev_charger_commands_use_web_ui_payloads():
    """Test start/stop/mode commands match the SEMS+ Web UI requests."""
    api = _web_api()
    with patch.object(SemsApi, "_make_api_call", return_value={}) as mock_call:
        assert api.startEvCharging("plant", CHARGER_SN, "GW11K-HCA-20", 1)
        assert api.stopEvCharging("plant", CHARGER_SN, "GW11K-HCA-20", 1)
        assert api.setEvChargeMode("plant", CHARGER_SN, "GW11K-HCA-20", 2, DETAIL)
        assert api.setEvChargeMode("plant", CHARGER_SN, "GW11K-HCA-20", 0, DETAIL)
        assert api.setEvChargerConfig(
            "plant", CHARGER_SN, "GW11K-HCA-20", "buyPwrLimit", 5.5
        )

    calls = [
        (c.args[0], json.loads(c.kwargs["data"])) for c in mock_call.call_args_list
    ]
    base = {"sn": CHARGER_SN, "plantId": "plant", "productModel": "GW11K-HCA-20"}
    assert calls == [
        ("/sems-remote/api/ev-charger/startCharge", {**base, "mode": 1}),
        ("/sems-remote/api/ev-charger/stopCharge", {**base, "mode": 1}),
        ("/sems-remote/api/ev-charger/set-mode", {**base, "mode": 2}),
        (
            "/sems-remote/api/ev-charger/set-mode",
            {**base, "mode": 0, "chargeMaxPower": 11, "chargePowerSetted": 0},
        ),
        ("/sems-remote/api/ev-charger/set-config", {**base, "buyPwrLimit": 5.5}),
    ]
    assert all(c.kwargs["method"] == "POST" for c in mock_call.call_args_list)


def test_ev_charger_command_failure_returns_false():
    """Test a rejected command is reported to the caller."""
    with patch.object(SemsApi, "_make_api_call", return_value=None):
        assert not _web_api().startEvCharging("plant", CHARGER_SN, "m", 0)


async def test_ev_charger_entities(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Test charger sensors, charging switch, and charge mode select."""
    del enable_custom_integrations
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_STATION_ID: STATION_ID},
    )
    entry.add_to_hass(hass)
    data = {
        "inverter": [
            {"invert_full": {"sn": "INV1", "name": "Inverter", "status": 1, "pac": 100}}
        ],
        "ev_chargers": {
            CHARGER_SN: {
                "sn": CHARGER_SN,
                "name": "Wallbox",
                "factors": {
                    "Charging_Power": {
                        "value": 7.2,
                        "unit": "kW",
                        "alias": "charging_power",
                    },
                    "sessionEnergy": {
                        "value": 12.5,
                        "unit": "kWh",
                        "alias": "session_energy",
                    },
                },
                "mode_info": MODE_INFO,
                "detail": DETAIL,
                "charging_power": 7200.0,
                "charge_log": {
                    "workStu": 6,
                    "status": 1,
                    "currentChargeQuantity": 3.5,
                    "greenElec": 2.0,
                    "chargeTimeLength": 95,
                    "chargeEndCauseDetail": "user_stop",
                },
            }
        },
    }
    with (
        patch("custom_components.sems.sems_api.SemsApi.getData", return_value=data),
        patch(
            "custom_components.sems.sems_api.SemsApi.getEnergyStorageIntegratedCabinets",
            return_value=[],
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        ent_reg = er.async_get(hass)

        def state(platform, key):
            entity_id = ent_reg.async_get_entity_id(
                platform, DOMAIN, f"{CHARGER_SN}-ev-{key}"
            )
            assert entity_id is not None, key
            return hass.states.get(entity_id)

        assert state(Platform.SENSOR, "status").state == "Charging"
        assert (
            state(Platform.SENSOR, "status").attributes["last_session_end_reason"]
            == "user_stop"
        )
        assert state(Platform.SENSOR, "plug").state == "Connected"
        charging_power = state(Platform.SENSOR, "charging-power")
        assert float(charging_power.state) == 7200
        assert charging_power.attributes["unit_of_measurement"] == "W"
        assert (
            float(state(Platform.SENSOR, "session-currentChargeQuantity").state) == 3.5
        )
        assert float(state(Platform.SENSOR, "session-greenElec").state) == 2.0
        duration = state(Platform.SENSOR, "session-chargeTimeLength")
        assert duration.attributes["unit_of_measurement"] == "min"
        assert (
            ent_reg.async_get_entity_id(
                Platform.SENSOR, DOMAIN, f"{CHARGER_SN}-ev-session-purElec"
            )
            is None
        )
        power = state(Platform.SENSOR, "Charging_Power")
        assert float(power.state) == 7.2
        assert power.attributes["unit_of_measurement"] == "kW"
        assert power.attributes["friendly_name"] == "EV Charger Wallbox Charging Power"
        energy = state(Platform.SENSOR, "sessionEnergy")
        assert energy.attributes["device_class"] == "energy"
        assert state(Platform.SWITCH, "charging").state == "on"
        assert state(Platform.SWITCH, "charging").attributes["friendly_name"] == (
            "EV Charger Wallbox Start Charging"
        )
        mode = state(Platform.SELECT, "charge-mode")
        assert mode.state == "PV"
        assert mode.attributes["options"] == ["Fast", "PV", "PV + battery"]

        with patch.object(SemsApi, "stopEvCharging", return_value=True) as stop:
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": state(Platform.SWITCH, "charging").entity_id},
                blocking=True,
            )
        stop.assert_called_once_with(STATION_ID, CHARGER_SN, "GW11K-HCA-20", 1)

        with patch.object(SemsApi, "setEvChargeMode", return_value=True) as set_mode:
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": mode.entity_id, "option": "Fast"},
                blocking=True,
            )
        set_mode.assert_called_once_with(
            STATION_ID, CHARGER_SN, "GW11K-HCA-20", 0, DETAIL
        )

        # "More Control" settings reported by ev-charger/detail.
        assert state(Platform.SWITCH, "config-phaseSwitch").state == "on"
        assert state(Platform.SWITCH, "config-dynamicLoad").state == "off"
        plug_and_charge = state(Platform.SWITCH, "config-chargedNow")
        assert plug_and_charge.state == "off"
        assert plug_and_charge.attributes["friendly_name"] == (
            "EV Charger Wallbox Plug and Charge"
        )
        assert ent_reg.async_get(plug_and_charge.entity_id).entity_category is None
        assert (
            ent_reg.async_get_entity_id(
                Platform.SWITCH, DOMAIN, f"{CHARGER_SN}-ev-config-lockChargingPlug"
            )
            is None
        )
        output = state(Platform.NUMBER, "config-ratedMaxiChargePower")
        assert float(output.state) == 11
        assert output.attributes["min"] == 4.2
        assert output.attributes["max"] == 11
        import_limit = state(Platform.NUMBER, "config-buyPwrLimit")
        assert import_limit.attributes["max"] == 40

        with patch.object(SemsApi, "setEvChargerConfig", return_value=True) as cfg:
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": state(Platform.SWITCH, "config-dynamicLoad").entity_id},
                blocking=True,
            )
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": plug_and_charge.entity_id},
                blocking=True,
            )
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": import_limit.entity_id, "value": 5.5},
                blocking=True,
            )
        assert cfg.call_args_list[0].args == (
            STATION_ID,
            CHARGER_SN,
            "GW11K-HCA-20",
            "dynamicLoad",
            1,
        )
        assert cfg.call_args_list[1].args == (
            STATION_ID,
            CHARGER_SN,
            "GW11K-HCA-20",
            "chargedNow",
            1,
        )
        assert cfg.call_args_list[2].args == (
            STATION_ID,
            CHARGER_SN,
            "GW11K-HCA-20",
            "buyPwrLimit",
            5.5,
        )


@patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
@patch.object(SemsApi, "getWebStationFlow", return_value={"pEvChar": "n/a"})
def test_get_web_data_ignores_invalid_ev_charging_power(mock_flow, mock_statistics):
    """Test an invalid station-flow EV power does not break charger data."""
    with patch.object(SemsApi, "_make_api_call", side_effect=_fake_api_call):
        result = _web_api().getWebData(STATION_ID)

    assert "charging_power" not in result["ev_chargers"][CHARGER_SN]


def test_get_web_ev_charger_survives_failing_endpoints():
    """Test each unavailable charger endpoint is skipped independently."""

    def fake_api_call(url_part, *args, **kwargs):
        if "telemetry" in url_part or "ev-charger/detail" in url_part:
            raise OutOfRetries("unavailable")
        if "telecounting" in url_part:
            return {"not": "a list"}
        if "control-item-content-list" in url_part:
            return MODE_INFO
        if "getLastCharge" in url_part:
            return {"chargeLog": None}
        return None

    with patch.object(SemsApi, "_make_api_call", side_effect=fake_api_call):
        charger = _web_api().getWebEvCharger(STATION_ID, {"sn": CHARGER_SN})

    assert charger["factors"] == {}
    assert charger["mode_info"] == MODE_INFO
    assert charger["charge_log"] == {}
    assert charger["detail"] == {}


def test_get_web_ev_charger_without_model_skips_detail():
    """Test the detail request needs the charger model."""

    def fake_api_call(url_part, *args, **kwargs):
        if "control-item-content-list" in url_part:
            raise OutOfRetries("unavailable")
        if "getLastCharge" in url_part:
            return []
        assert "ev-charger/detail" not in url_part
        return []

    with patch.object(SemsApi, "_make_api_call", side_effect=fake_api_call):
        charger = _web_api().getWebEvCharger(STATION_ID, {"sn": CHARGER_SN})

    assert charger["mode_info"] == {}
    assert charger["charge_log"] == {}
    assert charger["detail"] == {}


def test_web_factors_with_units_skips_invalid_entries():
    """Test malformed groups and factors are ignored."""
    assert SemsApi._web_factors_with_units(
        [
            "not a group",
            {
                "factors": [
                    "not a factor",
                    {"code": "missing_data"},
                    {"code": "text", "data": "V1.2"},
                    {"code": 5, "data": "1"},
                    {"code": "power", "data": "1.5", "unit": "", "alias": ""},
                ]
            },
        ]
    ) == {"power": {"value": 1.5, "unit": None, "alias": "power"}}


def _coordinator(charger: dict) -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(ev_chargers={CHARGER_SN: charger}),
        station_id=STATION_ID,
        sems_api=Mock(),
        async_request_refresh=AsyncMock(),
    )


def test_ev_charger_entities_handle_missing_and_invalid_values():
    """Test entities report unknown instead of failing on bad SEMS+ data."""
    coordinator = _coordinator(
        {
            "factors": {},
            "mode_info": {"chargeMode": "?", "ratedPower": "?"},
            "detail": {"chargeMode": None},
            "charge_log": {"workStu": "?", "status": "?", "mileage": "?"},
        }
    )

    assert EvChargerStatusSensor(coordinator, CHARGER_SN).native_value is None
    assert EvChargerPlugSensor(coordinator, CHARGER_SN).native_value is None
    assert (
        EvChargerSessionSensor(coordinator, CHARGER_SN, "mileage").native_value is None
    )
    assert EvChargerChargingSwitch(coordinator, CHARGER_SN).is_on is None
    assert EvChargeModeSelect(coordinator, CHARGER_SN).current_option is None
    factor = EvChargerFactorSensor(coordinator, CHARGER_SN, "firmware", {"unit": "rpm"})
    assert factor.native_value is None
    assert factor.native_unit_of_measurement == "rpm"
    assert EvChargerConfigSwitch(coordinator, CHARGER_SN, "dynamicLoad").is_on is None
    number = EvChargerConfigNumber(coordinator, CHARGER_SN, "ratedMaxiChargePower")
    assert number.native_value is None
    # Unknown rated power falls back to a 22 kW charger.
    assert (number.native_min_value, number.native_max_value) == (4.2, 22.0)


def test_ev_charger_config_number_ranges():
    """Test number ranges follow the charger's rated power and SEMS ranges."""
    coordinator = _coordinator(
        {
            "mode_info": {
                "ratedPower": 7,
                "controlItemRanges": {"Buy_Pwr_Limit": {"min": "x"}},
            }
        }
    )

    output = EvChargerConfigNumber(coordinator, CHARGER_SN, "ratedMaxiChargePower")
    assert (output.native_min_value, output.native_max_value) == (1.4, 7.0)
    import_limit = EvChargerConfigNumber(coordinator, CHARGER_SN, "buyPwrLimit")
    assert (import_limit.native_min_value, import_limit.native_max_value) == (
        0.0,
        22.0,
    )
    current = EvChargerConfigNumber(coordinator, CHARGER_SN, "currentLimit")
    assert (current.native_min_value, current.native_max_value) == (0.0, 63.0)


async def test_ev_charger_commands_report_errors(hass: HomeAssistant) -> None:
    """Test unknown models and rejected commands raise service errors."""
    coordinator = _coordinator({"mode_info": {}, "detail": {}})
    switch = EvChargerChargingSwitch(coordinator, CHARGER_SN)
    switch.hass = hass
    switch.entity_id = "switch.wallbox_start_charging"

    with pytest.raises(HomeAssistantError, match="charger model is unknown"):
        await switch.async_turn_on()

    coordinator.data.ev_chargers[CHARGER_SN]["mode_info"] = MODE_INFO
    coordinator.sems_api.startEvCharging.return_value = False
    with pytest.raises(HomeAssistantError, match="SEMS rejected"):
        await switch.async_turn_on()
    coordinator.sems_api.startEvCharging.assert_called_once_with(
        STATION_ID, CHARGER_SN, "GW11K-HCA-20", 0
    )
    coordinator.async_request_refresh.assert_not_called()


async def test_ev_charger_config_commands(hass: HomeAssistant) -> None:
    """Test config switches turn off and whole-ampere numbers send integers."""
    coordinator = _coordinator({"mode_info": MODE_INFO, "detail": {"currentLimit": 16}})
    coordinator.sems_api.setEvChargerConfig.return_value = True
    config_switch = EvChargerConfigSwitch(coordinator, CHARGER_SN, "phaseSwitch")
    number = EvChargerConfigNumber(coordinator, CHARGER_SN, "currentLimit")
    for entity in (config_switch, number):
        entity.hass = hass
        entity.entity_id = "test.entity"

    await config_switch.async_turn_off()
    await number.async_set_native_value(20.0)

    assert [
        call.args[3:] for call in coordinator.sems_api.setEvChargerConfig.call_args_list
    ] == [
        ("phaseSwitch", 0),
        ("currentLimit", 20),
    ]
    assert coordinator.async_request_refresh.await_count == 2


def test_ev_charger_sensors_without_optional_values():
    """Test only always-present sensors are created for a bare charger."""
    coordinator = _coordinator({"charge_log": {}})

    sensors = ev_charger_sensors(coordinator)

    assert [type(sensor) for sensor in sensors] == [
        EvChargerStatusSensor,
        EvChargerPlugSensor,
    ]
    assert sensors[1].native_value is None
    factor = EvChargerFactorSensor(coordinator, CHARGER_SN, "count", {"unit": ""})
    assert factor.native_unit_of_measurement is None


def test_get_web_ev_charger_ignores_invalid_detail():
    """Test a non-object detail response leaves the settings empty."""

    def fake_api_call(url_part, *args, **kwargs):
        if "control-item-content-list" in url_part:
            return MODE_INFO
        if "ev-charger/detail" in url_part:
            return []
        return None

    with patch.object(SemsApi, "_make_api_call", side_effect=fake_api_call):
        charger = _web_api().getWebEvCharger(STATION_ID, {"sn": CHARGER_SN})

    assert charger["detail"] == {}


@pytest.mark.parametrize(
    "denied",
    [
        "telemetry",
        "telecounting",
        "control-item-content-list",
        "getLastCharge",
        "detail",
    ],
)
def test_get_web_ev_charger_survives_permission_denied(denied):
    """Test a denied optional charger request does not fail the refresh."""

    def fake_api_call(url_part, *args, **kwargs):
        if denied in url_part:
            raise SemsPermissionError("EV charger call", "denied")
        return _fake_api_call(url_part, *args, **kwargs)

    with patch.object(SemsApi, "_make_api_call", side_effect=fake_api_call):
        charger = _web_api().getWebEvCharger(STATION_ID, {"sn": CHARGER_SN})

    assert charger["sn"] == CHARGER_SN


def test_ev_charger_session_energy_has_no_state_class():
    """Test last-session energies don't build long-term counter statistics."""
    coordinator = _coordinator({"charge_log": {"currentChargeQuantity": 3.5}})

    for field in ("currentChargeQuantity", "greenElec", "purElec"):
        sensor = EvChargerSessionSensor(coordinator, CHARGER_SN, field)
        assert sensor.device_class == "energy"
        assert sensor.state_class is None

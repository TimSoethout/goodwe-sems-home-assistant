"""Tests for GoodWe EV charger (HCA wallbox) support via SEMS+ Web."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from custom_components.sems.sems_api import SemsApi

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
@patch.object(SemsApi, "getWebStationFlow", return_value={})
def test_get_web_data_collects_ev_charger(mock_flow, mock_statistics):
    """Test an EV_CHARGER device is read separately from inverters."""
    with patch.object(SemsApi, "_make_api_call", side_effect=_fake_api_call):
        result = _web_api().getWebData(STATION_ID)

    assert result["inverter"] == []
    charger = result["ev_chargers"][CHARGER_SN]
    assert charger["name"] == "Wallbox"
    assert charger["mode_info"] == MODE_INFO
    assert charger["detail"] == DETAIL
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
                "charge_log": {"workStu": 6, "status": 1},
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
        power = state(Platform.SENSOR, "Charging_Power")
        assert float(power.state) == 7.2
        assert power.attributes["unit_of_measurement"] == "kW"
        assert power.attributes["friendly_name"] == "EV Charger Wallbox Charging Power"
        energy = state(Platform.SENSOR, "sessionEnergy")
        assert energy.attributes["device_class"] == "energy"
        assert state(Platform.SWITCH, "charging").state == "on"
        mode = state(Platform.SELECT, "charge-mode")
        assert mode.state == "pv"
        assert mode.attributes["options"] == ["fast", "pv", "pv_battery"]

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
                {"entity_id": mode.entity_id, "option": "fast"},
                blocking=True,
            )
        set_mode.assert_called_once_with(
            STATION_ID, CHARGER_SN, "GW11K-HCA-20", 0, DETAIL
        )

        # "More Control" settings reported by ev-charger/detail.
        assert state(Platform.SWITCH, "config-phaseSwitch").state == "on"
        assert state(Platform.SWITCH, "config-dynamicLoad").state == "off"
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
            "buyPwrLimit",
            5.5,
        )

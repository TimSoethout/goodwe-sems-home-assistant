"""Tests for SEMS switch entities (Home Assistant integration-style)."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems.const import CONF_STATION_ID, DOMAIN

MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"

MOCK_GET_ENERGY_STORAGE_INTEGRATED_CABINETS_RESULT = [
    {
        "sn": "VD9878456151234NAH25BL5621",
        "no": "1",
        "name": "BAT1",
        "translateCode": "mppt1_battery",
        "type": "BAT_SYS",
        "status": 6,
        "soc": 82.0,
        "isConnected": True,
        "pbat": -10.902,
    }
]

MOCK_GET_BATTERY_GENERAL_FUNCTIONS = {
    "functionMenus": {
        "children": [
            {
                "children": [],
                "functions": [
                    {
                        "address": "47545",
                        "chineseName": "电池即充使能",
                        "control": 16,
                        "controlAttr": '[{"code":"开启","transKey":"on","value":"1"}]',
                        "cpuType": "ARM",
                        "distributeType": 0,
                        "functionName": "电池即充",
                        "gain": 1,
                        "id": "1991791639537946634",
                        "kafkaName": "Fast Charge Enable",
                        "note": "charge_now",
                        "preCommand": "F7",
                        "range": "[0,3]",
                        "rwType": "RW",
                        "size": 1,
                        "translateKey": "immediate_charge",
                        "type": "U16",
                        "unit": "N/A",
                    },
                    {
                        "address": "47545",
                        "chineseName": "电池即充使能",
                        "control": 16,
                        "controlAttr": '[{"code":"禁能","value":"0","transKey":"remote_Switch_off"}]',
                        "cpuType": "ARM",
                        "functionName": "停止即充",
                        "gain": 1,
                        "id": "2013217017330515970",
                        "kafkaName": "Fast Charge Enable",
                        "note": "",
                        "preCommand": "F7",
                        "range": "[0,3]",
                        "rwType": "RW",
                        "size": 1,
                        "translateKey": "stop_charging",
                        "type": "U16",
                        "unit": "1",
                    },
                    {
                        "address": "47546",
                        "chineseName": "停止的SOC",
                        "control": 3,
                        "controlAttr": "",
                        "cpuType": "ARM",
                        "extendAttr": {"3": {}},
                        "functionName": "充电截止SOC",
                        "gain": 1,
                        "id": "1991791639537946635",
                        "kafkaName": "Fast Charge Stop SOC",
                        "note": "",
                        "preCommand": "F7",
                        "range": "[1,100]",
                        "rwType": "RW",
                        "size": 1,
                        "translateKey": "end_charge_soc",
                        "type": "U16",
                        "unit": "%",
                    },
                    {
                        "address": "47603",
                        "chineseName": "快速充电功率（%）",
                        "control": 3,
                        "controlAttr": "",
                        "cpuType": "ARM",
                        "distributeType": 0,
                        "functionName": "电池即充功率",
                        "gain": 1,
                        "id": "1991791639537946636",
                        "kafkaName": "Fast Charge Power Percent",
                        "note": "",
                        "preCommand": "F7",
                        "range": "[0,100]",
                        "rwType": "RW",
                        "size": 1,
                        "translateKey": "bat_immediate_charge_power",
                        "type": "U16",
                        "unit": "%",
                    },
                ],
                "menuId": "1991767445274136578",
                "name": "电池即充",
                "note": "",
                "translateKey": "immediate_charge",
                "visible": 0,
                "funcKey": "immediate_charge",
                "quickTag": "3",
                "sortOrder": 1,
            },
            {
                "children": [],
                "functions": [
                    {
                        "address": "47942",
                        "chineseName": "时间段2开始时间",
                        "control": 24,
                        "controlAttr": "",
                        "cpuType": "ARM",
                        "dataFormat": "HHmm",
                        "distributeType": 0,
                        "extendAttr": {"24": {"highAddressFlag": False}},
                        "functionName": "BMS1加热起始时间",
                        "gain": 1,
                        "id": "1996092191767912449",
                        "preCommand": "F7",
                        "range": "[0,23],[0,59]",
                        "relationFuncs": [
                            {
                                "address": "47943",
                                "chineseName": "时间段2结束时间",
                                "control": 24,
                                "controlAttr": "",
                                "cpuType": "ARM",
                                "dataFormat": "HHmm",
                                "distributeType": 0,
                                "functionName": "结束时间",
                                "gain": 1,
                                "id": "1996092191767912450",
                                "preCommand": "F7",
                                "range": "[0,23],[0,59]",
                                "rwType": "RW",
                                "size": 1,
                                "translateKey": "end_t",
                                "type": "U16",
                                "unit": "N/A",
                            }
                        ],
                        "rwType": "RW",
                        "size": 1,
                        "translateKey": "bms1_heating_start_time",
                        "type": "U16",
                        "unit": "N/A",
                    }
                ],
                "menuId": "1991767498348859393",
                "name": "电池加热",
                "note": "",
                "translateKey": "bat_heat",
                "visible": 0,
                "funcKey": "bat_heat",
                "quickTag": "3",
                "sortOrder": 2,
            },
        ],
        "menuId": "1988896846228516866",
        "name": "电池",
        "note": "",
        "translateKey": "bat",
        "visible": 0,
        "funcKey": "bat",
    }
}

MOCK_GET_BATTERY_IMMEDIATE_CHARGING_STATES = {
    "sn": "GW0000SN000TEST1",
    "data": {"47545": 1, "47546": 75, "47603": 65},
    "resultValues": {
        "GW0000SN000TEST1": {
            "47545": [{"value": 1}],
            "47546": [{"value": 75}],
            "47603": [{"value": 65}],
        }
    },
}

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


async def test_immediate_charging_switch_state_from_coordinator(
        hass: HomeAssistant,
        enable_custom_integrations: None,
) -> None:
    """Test that the switches are created and have the expected state."""
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

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.getData",
            return_value=MOCK_GET_DATA_RESULT_MINIMAL,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getEnergyStorageIntegratedCabinets",
            return_value=MOCK_GET_ENERGY_STORAGE_INTEGRATED_CABINETS_RESULT,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryGeneralFunctions",
            return_value=MOCK_GET_BATTERY_GENERAL_FUNCTIONS,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryImmediateChargingStates",
            return_value=MOCK_GET_BATTERY_IMMEDIATE_CHARGING_STATES,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    entity_id = ent_reg.async_get_entity_id(
        Platform.SWITCH, DOMAIN, "GW0000SN000TEST1-mppt1_battery-battery_immediate_charging"
    )

    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"

async def test_flip_immediate_charging_switch(
        hass: HomeAssistant,
        enable_custom_integrations: None,
) -> None:
    """Test that the switch state updates correctly when flipping the switch."""
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

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.getData",
            return_value=MOCK_GET_DATA_RESULT_MINIMAL,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getEnergyStorageIntegratedCabinets",
            return_value=MOCK_GET_ENERGY_STORAGE_INTEGRATED_CABINETS_RESULT,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryGeneralFunctions",
            return_value=MOCK_GET_BATTERY_GENERAL_FUNCTIONS,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryImmediateChargingStates",
            return_value=MOCK_GET_BATTERY_IMMEDIATE_CHARGING_STATES,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    entity_id = ent_reg.async_get_entity_id(
        Platform.SWITCH, DOMAIN, "GW0000SN000TEST1-mppt1_battery-battery_immediate_charging"
    )

    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"

    hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"


async def test_immediate_charging_switch_not_created_if_immediate_charging_not_supported(
        hass: HomeAssistant,
        enable_custom_integrations: None,
) -> None:
    """Test that the numbers are not created if immediate charging is not supported."""
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

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.getData",
            return_value=MOCK_GET_DATA_RESULT_MINIMAL,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getEnergyStorageIntegratedCabinets",
            return_value=MOCK_GET_ENERGY_STORAGE_INTEGRATED_CABINETS_RESULT,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryGeneralFunctions",
            return_value={},
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryImmediateChargingStates",
            return_value=MOCK_GET_BATTERY_IMMEDIATE_CHARGING_STATES,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    entity_id = ent_reg.async_get_entity_id(
        Platform.SWITCH, DOMAIN, "GW0000SN000TEST1-mppt1_battery-battery_immediate_charging"
    )

    assert entity_id is None

    coordinator = entry.runtime_data.coordinator
    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.getData",
            return_value=MOCK_GET_DATA_RESULT_MINIMAL,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getEnergyStorageIntegratedCabinets",
            return_value=[],
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryGeneralFunctions",
            return_value=MOCK_GET_BATTERY_GENERAL_FUNCTIONS,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryImmediateChargingStates",
            return_value=MOCK_GET_BATTERY_IMMEDIATE_CHARGING_STATES,
        ),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    entity_id = ent_reg.async_get_entity_id(
        Platform.NUMBER, DOMAIN, "GW0000SN000TEST1-mppt1_battery-battery_immediate_charging"
    )

    assert entity_id is None

async def test_flip_inverter_switch(
        hass: HomeAssistant,
        enable_custom_integrations: None,
) -> None:
    """Test that the switch state updates correctly when flipping the switch."""
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

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.getData",
            return_value=MOCK_GET_DATA_RESULT_MINIMAL,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getEnergyStorageIntegratedCabinets",
            return_value=[],
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryGeneralFunctions",
            return_value={},
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryImmediateChargingStates",
            return_value={},
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    entity_id = ent_reg.async_get_entity_id(
        Platform.SWITCH, DOMAIN, "GW0000SN000TEST1-switch"
    )

    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"

    hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"
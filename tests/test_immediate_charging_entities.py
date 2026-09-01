"""Tests for SEMS immediate-charging entities."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from tests.fixtures import MOCK_GET_DATA_RESULT_MINIMAL

POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"
INVERTER_SERIAL = "GW0000SN000TEST1"
BATTERY_ID = "mppt1_battery"

CABINETS = [
    {"no": "1", "name": "BAT1", "translateCode": BATTERY_ID},
]

FUNCTIONS = {
    "functionMenus": {
        "children": [
            {
                "functions": [
                    {
                        "address": "47545",
                        "id": "1991791639537946634",
                        "translateKey": "immediate_charge",
                    },
                    {
                        "address": "47545",
                        "id": "2013217017330515970",
                        "translateKey": "stop_charging",
                    },
                    {
                        "address": "47546",
                        "id": "1991791639537946635",
                        "translateKey": "end_charge_soc",
                    },
                    {
                        "address": "47603",
                        "id": "1991791639537946636",
                        "translateKey": "bat_immediate_charge_power",
                    },
                    {
                        "address": "47942",
                        "id": "unused",
                        "translateKey": "bms1_heating_start_time",
                    },
                ]
            }
        ]
    }
}

STATES = {"sn": INVERTER_SERIAL, "data": {"47545": 1, "47546": 75, "47603": 65}}


async def _setup_entry(
    hass: HomeAssistant,
    *,
    cabinets: list[dict[str, str]] = CABINETS,
    functions: dict = FUNCTIONS,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_STATION_ID: POWER_STATION_ID,
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
            return_value=cabinets,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryGeneralFunctions",
            return_value=functions,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryImmediateChargingStates",
            return_value=STATES,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


def _entity_id(hass: HomeAssistant, platform: Platform, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{INVERTER_SERIAL}-{BATTERY_ID}-{key}"
    )
    assert entity_id is not None
    return entity_id


async def test_immediate_charging_entities(hass: HomeAssistant) -> None:
    """Create the switch and number entities from supported functions."""
    await _setup_entry(hass)

    assert (
        hass.states.get(
            _entity_id(hass, Platform.SWITCH, "battery_immediate_charging")
        ).state
        == "on"
    )
    assert (
        hass.states.get(_entity_id(hass, Platform.NUMBER, "end_charge_soc")).state
        == "75.0"
    )
    assert (
        hass.states.get(
            _entity_id(hass, Platform.NUMBER, "bat_immediate_charge_power")
        ).state
        == "65.0"
    )


async def test_immediate_charging_entity_commands(hass: HomeAssistant) -> None:
    """Update each immediate-charging control."""
    await _setup_entry(hass)

    for platform, key, value in (
        (Platform.SWITCH, "battery_immediate_charging", "off"),
        (Platform.NUMBER, "end_charge_soc", "70"),
        (Platform.NUMBER, "bat_immediate_charge_power", "60"),
    ):
        entity_id = _entity_id(hass, platform, key)
        hass.states.async_set(entity_id, value)
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == value


async def test_entities_require_supported_functions(hass: HomeAssistant) -> None:
    """Do not add controls when the API does not advertise their functions."""
    await _setup_entry(hass, functions={})

    ent_reg = er.async_get(hass)
    for platform, key in (
        (Platform.SWITCH, "battery_immediate_charging"),
        (Platform.NUMBER, "end_charge_soc"),
        (Platform.NUMBER, "bat_immediate_charge_power"),
    ):
        assert (
            ent_reg.async_get_entity_id(
                platform, DOMAIN, f"{INVERTER_SERIAL}-{BATTERY_ID}-{key}"
            )
            is None
        )


async def test_entities_are_not_added_after_discovery(hass: HomeAssistant) -> None:
    """Platforms only create entities during entry setup."""
    entry = await _setup_entry(hass, functions={})
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
            return_value=FUNCTIONS,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getBatteryImmediateChargingStates",
            return_value=STATES,
        ),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert (
        er.async_get(hass).async_get_entity_id(
            Platform.NUMBER,
            DOMAIN,
            f"{INVERTER_SERIAL}-{BATTERY_ID}-end_charge_soc",
        )
        is None
    )


async def test_inverter_switch_without_battery(hass: HomeAssistant) -> None:
    """Keep the existing inverter switch independent from battery discovery."""
    await _setup_entry(hass, cabinets=[], functions={})

    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.SWITCH, DOMAIN, f"{INVERTER_SERIAL}-switch"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "on"
    hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"

"""Tests for SEMS config entry diagnostics."""

from __future__ import annotations

import json
from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems import SemsData
from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from custom_components.sems.diagnostics import async_get_config_entry_diagnostics

from .test_sensor_entities import (
    MOCK_GET_DATA_RESULT_MINIMAL,
    MOCK_POWER_STATION_ID,
    _mock_no_battery_api,
)

INVERTER_SN = "GW0000SN000TEST1"
BATTERY_SN = "BATSYS0000TEST01"


async def test_diagnostics_redact_credentials_station_and_serials(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Diagnostics keep the data shape but no credentials or identifiers."""
    del enable_custom_integrations
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_USERNAME: "someone@example.com",
            CONF_PASSWORD: "secret-password",
            CONF_STATION_ID: MOCK_POWER_STATION_ID,
        },
    )
    entry.add_to_hass(hass)

    with _mock_no_battery_api(MOCK_GET_DATA_RESULT_MINIMAL):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    inverter = {
        **MOCK_GET_DATA_RESULT_MINIMAL["inverter"][0]["invert_full"],
        "battery_count": 1,
        "more_batterys": [{"sn": BATTERY_SN, "soc": 95}],
    }
    with patch.object(coordinator, "async_update_listeners"):
        coordinator.async_set_updated_data(
            SemsData(
                inverters={INVERTER_SN: inverter},
                batteries={INVERTER_SN: {"mppt1_battery": {"name": "BAT1"}}},
                unavailable_inverter_sources={INVERTER_SN: {"telemetry"}},
            )
        )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diagnostics)

    for secret in (
        "someone@example.com",
        "secret-password",
        MOCK_POWER_STATION_ID,
        INVERTER_SN,
        BATTERY_SN,
        "Test Inverter",
    ):
        assert secret not in dumped

    device = diagnostics["data"]["inverters"]["**REDACTED_DEVICE_2**"]
    assert device["pac"] == 589
    assert device["battery_count"] == 1
    assert device["more_batterys"][0]["soc"] == 95
    assert diagnostics["data"]["unavailable_inverter_sources"] == {
        "**REDACTED_DEVICE_2**": ["telemetry"]
    }

"""Tests for SEMS+ dongles and battery racks reported next to inverters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems.const import CONF_STATION_ID, DOMAIN

POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"
HYBRID_DIR = Path(__file__).parent.parent / "api_examples" / "semsplus_hybrid"

# Placeholder serials from the sanitized all-status capture.
INVERTER_SERIAL = "<inverter_serial>"
BATTERY_RACK_SERIAL = "<battery_rack_serial>"
DONGLE_SERIAL = "<dongle_serial>"


def _fake_api_call(url_part: str, *args: Any, **kwargs: Any) -> Any:
    """Serve the captured device list; other endpoints return no data."""
    if "all-status" in url_part:
        with open(HYBRID_DIR / "all_status.json", encoding="utf-8") as file:
            return json.load(file)["data"]
    return []


def _entry(hass: HomeAssistant) -> MockConfigEntry:
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
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    with (
        patch(
            "custom_components.sems.sems_api.SemsApi._make_api_call",
            side_effect=_fake_api_call,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi._get_web_energy_statistics",
            return_value=None,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _switch_entity_id(hass: HomeAssistant, serial_number: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        Platform.SWITCH, DOMAIN, f"{serial_number}-switch"
    )


async def test_inverter_control_only_for_inverters(hass: HomeAssistant) -> None:
    """Dongles and battery racks from SEMS+ get no inverter control switch."""
    await _setup(hass, _entry(hass))

    assert _switch_entity_id(hass, INVERTER_SERIAL) is not None
    assert _switch_entity_id(hass, BATTERY_RACK_SERIAL) is None
    assert _switch_entity_id(hass, DONGLE_SERIAL) is None

    # The devices and their status sensors are kept.
    ent_reg = er.async_get(hass)
    for serial_number in (INVERTER_SERIAL, BATTERY_RACK_SERIAL, DONGLE_SERIAL):
        assert (
            ent_reg.async_get_entity_id(
                Platform.SENSOR, DOMAIN, f"{serial_number}-status"
            )
            is not None
        )


async def test_non_inverter_device_names(hass: HomeAssistant) -> None:
    """Dongles and battery racks are named after their device type."""
    entry = _entry(hass)
    await _setup(hass, entry)

    dev_reg = dr.async_get(hass)
    inverter, rack, dongle = (
        dev_reg.async_get_device_by_identifier((DOMAIN, serial), entry.entry_id)
        for serial in (INVERTER_SERIAL, BATTERY_RACK_SERIAL, DONGLE_SERIAL)
    )
    assert inverter is not None and rack is not None and dongle is not None

    assert inverter.name == "Inverter Inverter"
    assert rack.name == f"Battery Rack {BATTERY_RACK_SERIAL}"
    assert rack.model == "Battery Rack"
    assert dongle.name == f"Dongle 1 ({DONGLE_SERIAL[-4:]})"
    assert dongle.model == "Dongle"
    for device in (inverter, rack, dongle):
        assert device.configuration_url == "https://semsplus.goodwe.com/"


async def test_stale_non_inverter_switches_are_removed(hass: HomeAssistant) -> None:
    """Switches created by earlier versions for non-inverters are removed."""
    entry = _entry(hass)
    other_entry = MockConfigEntry(
        domain=DOMAIN, title="Other", disabled_by=ConfigEntryDisabler.USER
    )
    other_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    for serial_number in (INVERTER_SERIAL, BATTERY_RACK_SERIAL):
        ent_reg.async_get_or_create(
            Platform.SWITCH, DOMAIN, f"{serial_number}-switch", config_entry=entry
        )
    # An entity owned by another config entry is left alone.
    ent_reg.async_get_or_create(
        Platform.SWITCH, DOMAIN, f"{DONGLE_SERIAL}-switch", config_entry=other_entry
    )

    await _setup(hass, entry)

    assert _switch_entity_id(hass, INVERTER_SERIAL) is not None
    assert _switch_entity_id(hass, BATTERY_RACK_SERIAL) is None
    assert _switch_entity_id(hass, DONGLE_SERIAL) is not None

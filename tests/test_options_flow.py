"""Tests for the update interval option and the reauthentication UI."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems import SemsDataUpdateCoordinator
from custom_components.sems.const import (
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    scan_interval_seconds,
)
from custom_components.sems.sems_api import SemsApi, SemsAuthError

MOCK_USERNAME = "user@example.com"
MOCK_PASSWORD = "test_password"
MOCK_STATION_ID_1 = "12345678-1234-5678-9abc-123456789abc"
MOCK_STATION_ID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MOCK_STATION_ID_3 = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "sems"


def _get_data(station_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return minimal coordinator data with a per-station inverter serial."""
    return {
        "inverter": [
            {
                "invert_full": {
                    "name": "Test Inverter",
                    "sn": f"GW0000SN{station_id[:8]}",
                    "powerstation_id": station_id,
                    "status": 1,
                    "capacity": 3.0,
                    "pac": 589,
                }
            }
        ],
        "hasPowerflow": False,
    }


def _entry(
    station_id: str,
    username: str = MOCK_USERNAME,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=station_id,
        data={
            CONF_USERNAME: username,
            CONF_PASSWORD: MOCK_PASSWORD,
            CONF_STATION_ID: station_id,
            **(data or {}),
        },
        options=options or {},
    )


@pytest.fixture
def mock_api():
    """Mock the SEMS requests made during a refresh."""
    with (
        patch.object(SemsApi, "getData", side_effect=_get_data) as mock_get_data,
        patch.object(SemsApi, "getEnergyStorageIntegratedCabinets", return_value=[]),
        patch.object(SemsApi, "getBatteryGeneralFunctions", return_value={}),
    ):
        yield mock_get_data


# ---------------------------------------------------------------------------
# scan_interval_seconds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "options", "expected"),
    [
        ({}, {}, DEFAULT_SCAN_INTERVAL),
        ({CONF_SCAN_INTERVAL: 120}, {}, 120),
        ({CONF_SCAN_INTERVAL: 120}, {CONF_SCAN_INTERVAL: 300}, 300),
        ({CONF_SCAN_INTERVAL: "180"}, {}, 180),
        # Values from before the minimum existed are limited to the range.
        ({CONF_SCAN_INTERVAL: 10}, {}, MIN_SCAN_INTERVAL),
        ({CONF_SCAN_INTERVAL: 86_400}, {}, MAX_SCAN_INTERVAL),
        ({CONF_SCAN_INTERVAL: None}, {}, DEFAULT_SCAN_INTERVAL),
        ({CONF_SCAN_INTERVAL: "fast"}, {}, DEFAULT_SCAN_INTERVAL),
    ],
)
def test_scan_interval_seconds(
    data: dict[str, Any], options: dict[str, Any], expected: int
) -> None:
    """Options win over data, and the result stays in the supported range."""
    assert scan_interval_seconds(data, options) == expected


async def test_coordinator_limits_legacy_interval(hass: HomeAssistant) -> None:
    """An interval below the minimum stored at setup is raised to the minimum."""
    entry = _entry(MOCK_STATION_ID_1, data={CONF_SCAN_INTERVAL: 5})
    entry.add_to_hass(hass)
    coordinator = SemsDataUpdateCoordinator(
        hass, SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD), entry
    )
    assert coordinator.update_interval == timedelta(seconds=MIN_SCAN_INTERVAL)


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_flow_shows_current_interval(hass: HomeAssistant) -> None:
    """The form defaults to the current interval and names the station count."""
    entry_1 = _entry(MOCK_STATION_ID_1, data={CONF_SCAN_INTERVAL: 90})
    entry_2 = _entry(MOCK_STATION_ID_2)
    other_account = _entry(MOCK_STATION_ID_3, username="other@x.test")
    for entry in (entry_1, entry_2, other_account):
        entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry_1.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["description_placeholders"] == {
        "station_count": "2",
        "min_interval": str(MIN_SCAN_INTERVAL),
    }
    schema = result["data_schema"].schema
    (key,) = schema
    assert key == CONF_SCAN_INTERVAL
    assert key.default() == 90


async def test_options_flow_updates_all_stations_of_the_account(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    """Saving the option applies it to every loaded station of the account."""
    entry_1 = _entry(MOCK_STATION_ID_1)
    entry_2 = _entry(MOCK_STATION_ID_2, options={"unrelated": True})
    other_account = _entry(MOCK_STATION_ID_3, username="other@x.test")
    for entry in (entry_1, entry_2, other_account):
        entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry_1.entry_id)
    await hass.async_block_till_done()
    coordinator_1 = entry_1.runtime_data.coordinator
    coordinator_2 = entry_2.runtime_data.coordinator
    refreshes = mock_api.call_count

    result = await hass.config_entries.options.async_init(entry_1.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 300}
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry_1.options == {CONF_SCAN_INTERVAL: 300}
    assert entry_2.options == {"unrelated": True, CONF_SCAN_INTERVAL: 300}
    assert other_account.options == {}

    # Applied in place: no reload, no extra refresh.
    for entry, coordinator in ((entry_1, coordinator_1), (entry_2, coordinator_2)):
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.coordinator is coordinator
        assert coordinator.update_interval == timedelta(seconds=300)
    assert other_account.runtime_data.coordinator.update_interval == timedelta(
        seconds=DEFAULT_SCAN_INTERVAL
    )
    assert mock_api.call_count == refreshes

    # Other entry updates keep the interval.
    hass.config_entries.async_update_entry(entry_1, title="Renamed")
    await hass.async_block_till_done()
    assert coordinator_1.update_interval == timedelta(seconds=300)

    for entry in (entry_1, entry_2, other_account):
        assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("value", [MIN_SCAN_INTERVAL - 1, MAX_SCAN_INTERVAL + 1])
async def test_options_flow_rejects_out_of_range_interval(
    hass: HomeAssistant, value: int
) -> None:
    """Intervals outside the supported range are rejected."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: value}
        )
    assert entry.options == {}


async def test_user_step_rejects_interval_below_minimum(hass: HomeAssistant) -> None:
    """The setup form applies the same minimum."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: MOCK_USERNAME,
                CONF_PASSWORD: MOCK_PASSWORD,
                CONF_SCAN_INTERVAL: MIN_SCAN_INTERVAL - 1,
            },
        )


# ---------------------------------------------------------------------------
# Control commands and reauthentication
# ---------------------------------------------------------------------------


async def test_control_command_runs_in_executor(hass: HomeAssistant) -> None:
    """A successful control command passes its arguments through."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    coordinator = SemsDataUpdateCoordinator(
        hass, SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD), entry
    )
    method = MagicMock()

    await coordinator.async_control(method, "a", 1)

    method.assert_called_once_with("a", 1)
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_control_command_starts_reauth_on_rejected_credentials(
    hass: HomeAssistant,
) -> None:
    """Rejected credentials during a command open the reauthentication flow."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    coordinator = SemsDataUpdateCoordinator(
        hass, SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD), entry
    )
    method = MagicMock(side_effect=SemsAuthError("rejected"))

    with pytest.raises(HomeAssistantError, match="reauthenticate"):
        await coordinator.async_control(method)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(
        DOMAIN, match_context={"source": SOURCE_REAUTH}
    )
    assert len(flows) == 1
    assert flows[0]["context"]["entry_id"] == entry.entry_id
    assert flows[0]["step_id"] == "reauth_confirm"


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


def _keys(node: Any, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return {prefix}
    keys: set[str] = set()
    for key, value in node.items():
        keys |= _keys(value, f"{prefix}.{key}" if prefix else key)
    return keys


@pytest.mark.parametrize("language", ["en", "es", "pt"])
def test_translations_cover_all_strings(language: str) -> None:
    """Every string in strings.json is translated."""
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text("utf-8"))
    translation = json.loads(
        (COMPONENT_DIR / "translations" / f"{language}.json").read_text("utf-8")
    )
    assert _keys(strings) <= _keys(translation)

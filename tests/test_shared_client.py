"""Tests for the SEMS+ client shared by the config entries of one account."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems import SemsDataUpdateCoordinator
from custom_components.sems.const import CONF_STATION_ID, DOMAIN
from custom_components.sems.sems_api import (
    SemsApi,
    SemsAuthError,
    SemsRateLimitedError,
)

MOCK_USERNAME = "user@example.com"
MOCK_PASSWORD = "test_password"
MOCK_STATION_ID_1 = "12345678-1234-5678-9abc-123456789abc"
MOCK_STATION_ID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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


def _entry(station_id: str, username: str = MOCK_USERNAME) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=station_id,
        data={
            CONF_USERNAME: username,
            CONF_PASSWORD: MOCK_PASSWORD,
            CONF_STATION_ID: station_id,
        },
    )


@contextmanager
def _mock_api(get_data: Any = None):
    with (
        patch.object(
            SemsApi,
            "getData",
            side_effect=get_data or _get_data,
        ) as mock_get_data,
        patch.object(SemsApi, "getEnergyStorageIntegratedCabinets", return_value=[]),
        patch.object(SemsApi, "getBatteryGeneralFunctions", return_value={}),
    ):
        yield mock_get_data


async def test_coordinator_passes_retry_after(hass: HomeAssistant) -> None:
    """A rate limit becomes UpdateFailed with the client's retry_after."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    api = SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD)
    coordinator = SemsDataUpdateCoordinator(hass, api, entry)

    with (
        _mock_api(get_data=SemsRateLimitedError(retry_after=240)),
        pytest.raises(UpdateFailed) as err,
    ):
        await coordinator._async_update_data()
    assert err.value.retry_after == 240


async def test_coordinator_requests_reauth(hass: HomeAssistant) -> None:
    """Rejected credentials raise ConfigEntryAuthFailed."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    api = SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD)
    coordinator = SemsDataUpdateCoordinator(hass, api, entry)

    with (
        _mock_api(get_data=SemsAuthError("rejected")),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coordinator._async_update_data()


async def test_entries_of_one_account_share_one_client(hass: HomeAssistant) -> None:
    """Stations of the same account share a client; the last unload closes it."""
    entry_1 = _entry(MOCK_STATION_ID_1)
    entry_2 = _entry(MOCK_STATION_ID_2, username=f"  {MOCK_USERNAME.upper()} ")
    other_account = _entry("bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee", "other@x.test")
    for entry in (entry_1, entry_2, other_account):
        entry.add_to_hass(hass)

    with _mock_api() as mock_get_data, patch.object(SemsApi, "close") as mock_close:
        # Setting up the integration sets up all of its entries.
        assert await hass.config_entries.async_setup(entry_1.entry_id)
        await hass.async_block_till_done()
        assert entry_2.state is ConfigEntryState.LOADED
        assert other_account.state is ConfigEntryState.LOADED

        shared = entry_1.runtime_data.api
        assert entry_2.runtime_data.api is shared
        assert other_account.runtime_data.api is not shared
        assert entry_1.runtime_data.coordinator is not (
            entry_2.runtime_data.coordinator
        )

        assert await hass.config_entries.async_unload(entry_1.entry_id)
        await hass.async_block_till_done()
        mock_close.assert_not_called()

        # The remaining entry keeps working with the shared client.
        calls = mock_get_data.call_count
        await entry_2.runtime_data.coordinator.async_refresh()
        assert entry_2.runtime_data.coordinator.last_update_success
        assert mock_get_data.call_count == calls + 1
        assert entry_2.state is ConfigEntryState.LOADED

        assert await hass.config_entries.async_unload(entry_2.entry_id)
        await hass.async_block_till_done()
        mock_close.assert_called_once()

        # A new setup of the account creates a new client.
        assert await hass.config_entries.async_setup(entry_1.entry_id)
        await hass.async_block_till_done()
        assert entry_1.runtime_data.api is not shared


async def test_failed_setup_releases_client(hass: HomeAssistant) -> None:
    """An entry that fails its first refresh does not keep the client open."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)

    with (
        _mock_api(get_data=SemsRateLimitedError(retry_after=60)),
        patch.object(SemsApi, "close") as mock_close,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_close.assert_called_once()
    assert not hass.data[DOMAIN]["clients"]
    # Cancel the scheduled setup retry.
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_updates_all_entries_of_the_account(
    hass: HomeAssistant,
) -> None:
    """Reauthentication stores the new password on every station entry."""
    entry_1 = _entry(MOCK_STATION_ID_1)
    entry_2 = _entry(MOCK_STATION_ID_2)
    other_account = _entry("bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee", "other@x.test")
    for entry in (entry_1, entry_2, other_account):
        entry.add_to_hass(hass)

    result = await entry_1.start_reauth_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch.object(SemsApi, "test_authentication", return_value=False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    with (
        patch.object(SemsApi, "test_authentication", return_value=True),
        patch("custom_components.sems.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new_password"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry_1.data[CONF_PASSWORD] == "new_password"
    assert entry_2.data[CONF_PASSWORD] == "new_password"
    assert other_account.data[CONF_PASSWORD] == MOCK_PASSWORD

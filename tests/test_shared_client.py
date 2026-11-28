"""Tests for the SEMS+ client shared by the config entries of one account."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import requests
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import MockConfigEntry

from custom_components.sems import (
    SemsDataUpdateCoordinator,
    _device_config_entry_ids,
    _normalize_battery_cabinets,
    _normalize_cabinet_index,
    _normalize_station_data,
    _parse_battery_menu,
    _shared_clients,
)
from custom_components.sems.const import CONF_STATION_ID, DOMAIN, GOODWE_SPELLING
from custom_components.sems.sems_api import (
    OutOfRetries,
    SemsApi,
    SemsAuthError,
    SemsPermissionError,
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


def test_device_config_entry_ids_supports_old_and_new_home_assistant_shapes() -> None:
    """Read both the singular and set-valued device registry fields."""
    assert _device_config_entry_ids(
        SimpleNamespace(config_entry_id="entry-1", config_entries=set())
    ) == {"entry-1"}
    assert _device_config_entry_ids(
        SimpleNamespace(config_entry_id=None, config_entries={"entry-1", "entry-2"})
    ) == {"entry-1", "entry-2"}


@pytest.mark.parametrize(
    ("integration_data", "message"),
    [
        ([], "integration data"),
        ({"clients": []}, "shared clients"),
    ],
)
def test_shared_clients_rejects_malformed_hass_data(
    hass: HomeAssistant, integration_data: Any, message: str
) -> None:
    """Reject malformed integration and shared-client data."""
    hass.data[DOMAIN] = integration_data

    with pytest.raises(TypeError, match=message):
        _shared_clients(hass)


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


@pytest.mark.parametrize(
    "error",
    [OutOfRetries("session rejected"), requests.ConnectionError("offline")],
    ids=["api-error", "network-error"],
)
async def test_coordinator_api_errors_become_update_failed(
    hass: HomeAssistant, error: Exception
) -> None:
    """API and network errors are reported as communication errors."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    api = SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD)
    coordinator = SemsDataUpdateCoordinator(hass, api, entry)

    with _mock_api(get_data=error), pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_coordinator_does_not_mask_programming_errors(
    hass: HomeAssistant,
) -> None:
    """Unexpected exceptions surface instead of posing as API errors."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    api = SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD)
    coordinator = SemsDataUpdateCoordinator(hass, api, entry)

    with (
        _mock_api(get_data=TypeError("bug")),
        pytest.raises(TypeError, match="bug"),
    ):
        await coordinator._async_update_data()


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


def test_normalize_cabinet_index() -> None:
    """Cabinet indices use an integer API contract."""
    assert _normalize_cabinet_index(3) == 3
    assert _normalize_cabinet_index("4") == 4
    assert _normalize_cabinet_index("not-a-number") == 0
    assert _normalize_cabinet_index(True) == 0


def test_normalize_prefetched_battery_cabinets() -> None:
    """Malformed cabinet records are skipped and valid records are typed."""
    data = {
        "_energy_storage_cabinets": {
            "INV1": [
                None,
                {},
                {"translateCode": "battery-1", "no": "2", "name": "Battery"},
            ],
            123: [{"translateCode": "ignored"}],
        }
    }

    cabinets = _normalize_battery_cabinets(data)

    assert len(cabinets) == 1
    assert cabinets[0].serial_number == "INV1"
    assert cabinets[0].cabinet_id == "battery-1"
    assert cabinets[0].index == 2
    assert cabinets[0].name == "Battery"


def test_parse_battery_menu() -> None:
    """Battery menu parsing ignores malformed and unsupported entries."""
    assert _parse_battery_menu({}) == {}
    assert _parse_battery_menu({"functionMenus": {"children": None}}) == {}
    assert (
        _parse_battery_menu(
            {"functionMenus": {"children": [None, {"functions": [None, {}]}]}}
        )
        == {}
    )

    parsed = _parse_battery_menu(
        {
            "functionMenus": {
                "children": [
                    {
                        "functions": [
                            {
                                "translateKey": "immediate_charge",
                                "address": "47545",
                                "id": "1",
                            },
                            {"translateKey": "unused", "address": "1"},
                        ]
                    }
                ]
            }
        }
    )
    assert parsed["immediate_charge"] == {"address": "47545", "id": "1"}


def test_normalize_station_data_keeps_optional_shapes_typed() -> None:
    """Station normalization retains valid EV, chart, and cabinet fields."""
    data = {
        "inverter": [
            {},
            {"invert_full": None},
            {"invert_full": {"sn": "INV1", "capacity": 5}},
        ],
        "kpi": {"currency": "EUR", "total_power": 12},
        "hasPowerflow": True,
        "powerflow": {"pGrid": -100},
        GOODWE_SPELLING.hasEnergyStatisticsCharts: True,
        GOODWE_SPELLING.energyStatisticsCharts: {"sum": 500},
        GOODWE_SPELLING.energyStatisticsTotals: {"buy": 42},
        "_energy_storage_cabinets": {
            "INV1": [{"translateCode": "battery-1", "no": "1"}]
        },
        "ev_chargers": {"CHG1": {"sn": "CHG1"}},
    }

    normalized = _normalize_station_data(
        data,
        MOCK_STATION_ID_1,
        lambda current_sn: current_sn,
    )

    assert normalized.inverters["INV1"]["sn"] == "INV1"
    assert normalized.currency == "EUR"
    assert normalized.battery_storage_supported
    assert normalized.battery_cabinets[0].index == 1
    assert normalized.ev_chargers == {"CHG1": {"sn": "CHG1"}}
    assert normalized.homekit is not None
    assert normalized.homekit["Charts_sum"] == 0.5
    assert normalized.homekit["Totals_buy"] == 42


@pytest.mark.parametrize(
    "data",
    [
        {"inverter": "not-a-list"},
        {"inverter": {}},
        {"inverter": [], "unavailable_data_sources": []},
        {"inverter": [], "unavailable_data_sources": {"inverters": []}},
        {"inverter": [], "unavailable_data_sources": {"homekit": []}},
        {
            "inverter": [],
            "unavailable_data_sources": {"inverters": {"INV1": ["telemetry"]}},
        },
        {
            "inverter": [],
            "unavailable_data_sources": {"inverters": {1: {"telemetry"}}},
        },
        {"inverter": [], "unavailable_data_sources": {"homekit": {1}}},
    ],
)
async def test_coordinator_rejects_malformed_normalized_data(
    hass: HomeAssistant, data: dict[str, Any]
) -> None:
    """Reject malformed normalized data rather than silently dropping status."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    coordinator = SemsDataUpdateCoordinator(
        hass, SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD), entry
    )

    with (
        patch.object(SemsApi, "getData", return_value=data),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()


@pytest.mark.parametrize(
    "error",
    [
        OutOfRetries("cabinet discovery exhausted"),
        SemsPermissionError("cabinet discovery", "denied"),
        SemsRateLimitedError(retry_after=60),
    ],
)
async def test_optional_cabinet_failure_keeps_station_data(
    hass: HomeAssistant, error: Exception
) -> None:
    """Cabinet discovery failures must not discard valid inverter data."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    coordinator = SemsDataUpdateCoordinator(
        hass, SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD), entry
    )
    data = {
        "info": {"is_stored": True},
        "inverter": [
            {
                "invert_full": {
                    "sn": "GW0000SN000TEST1",
                    "name": "Test Inverter",
                }
            }
        ],
        "kpi": {},
    }

    with (
        patch.object(SemsApi, "getData", return_value=data),
        patch.object(
            SemsApi,
            "getEnergyStorageIntegratedCabinets",
            side_effect=error,
        ),
    ):
        result = await coordinator._async_update_data()

    assert result.inverters["GW0000SN000TEST1"]["sn"] == "GW0000SN000TEST1"
    assert result.batteries is None


async def test_coordinator_normalizes_optional_powerflow_data(
    hass: HomeAssistant,
) -> None:
    """Keep the HomeKit station entity when optional payload sections are malformed."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)
    coordinator = SemsDataUpdateCoordinator(
        hass, SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD), entry
    )
    data = {
        "info": {"is_stored": True},
        "inverter": [
            {},
            {"invert_full": None},
            {"invert_full": {"sn": 123}},
        ],
        "kpi": [],
        "hasPowerflow": True,
        "powerflow": [],
        GOODWE_SPELLING.hasEnergyStatisticsCharts: True,
        GOODWE_SPELLING.energyStatisticsCharts: [],
        GOODWE_SPELLING.energyStatisticsTotals: [],
    }

    with (
        patch.object(SemsApi, "getData", return_value=data),
        patch.object(SemsApi, "getEnergyStorageIntegratedCabinets") as mock_cabinets,
    ):
        result = await coordinator._async_update_data()

    mock_cabinets.assert_not_called()
    assert result.inverters == {}
    assert result.homekit is not None
    assert result.homekit["all_time_generation"] is None
    assert result.homekit[GOODWE_SPELLING.hasEnergyStatisticsCharts] is True


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
        assert (
            entry_1.runtime_data.coordinator._poll_lock
            is entry_2.runtime_data.coordinator._poll_lock
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


async def test_shared_account_station_polls_are_serialized(
    hass: HomeAssistant,
) -> None:
    """Queued station refreshes run one at a time and all receive a turn."""
    entries = [_entry(MOCK_STATION_ID_1), _entry(MOCK_STATION_ID_2)]
    for entry in entries:
        entry.add_to_hass(hass)
    api = SemsApi(hass, MOCK_USERNAME, MOCK_PASSWORD)
    poll_lock = asyncio.Lock()
    coordinators = [
        SemsDataUpdateCoordinator(hass, api, entry, poll_lock=poll_lock)
        for entry in entries
    ]
    started = asyncio.Event()
    release = asyncio.Event()
    active_calls = 0
    maximum_active_calls = 0
    call_order: list[str] = []

    async def refresh(station_id: str) -> None:
        nonlocal active_calls, maximum_active_calls
        active_calls += 1
        maximum_active_calls = max(maximum_active_calls, active_calls)
        call_order.append(station_id)
        try:
            if station_id == MOCK_STATION_ID_1:
                started.set()
                await release.wait()
            await asyncio.sleep(0)
        finally:
            active_calls -= 1

    async def refresh_first() -> None:
        await refresh(MOCK_STATION_ID_1)

    async def refresh_second() -> None:
        await refresh(MOCK_STATION_ID_2)

    with (
        patch.object(
            coordinators[0],
            "_async_update_data_unlocked",
            side_effect=refresh_first,
        ),
        patch.object(
            coordinators[1],
            "_async_update_data_unlocked",
            side_effect=refresh_second,
        ),
    ):
        first = asyncio.create_task(coordinators[0]._async_update_data())
        await started.wait()
        second = asyncio.create_task(coordinators[1]._async_update_data())
        await asyncio.sleep(0)

        assert call_order == [MOCK_STATION_ID_1]
        release.set()
        await asyncio.gather(first, second)

    assert call_order == [MOCK_STATION_ID_1, MOCK_STATION_ID_2]
    assert maximum_active_calls == 1


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
        patch.object(SemsApi, "close") as mock_close,
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
    mock_close.assert_called_once()


async def test_failed_platform_forwarding_releases_client(
    hass: HomeAssistant,
) -> None:
    """An entry whose platform setup fails does not keep the client open."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)

    with (
        _mock_api(),
        patch.object(SemsApi, "close") as mock_close,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=RuntimeError("platform setup failed"),
        ),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    mock_close.assert_called_once()
    assert not hass.data[DOMAIN]["clients"]


async def test_reauth_shows_rate_limit_with_retry_after(
    hass: HomeAssistant,
) -> None:
    """A rate-limited reauthentication tells the user when to retry."""
    entry = _entry(MOCK_STATION_ID_1)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    with patch.object(
        SemsApi,
        "test_authentication",
        side_effect=SemsRateLimitedError(retry_after=120),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new_password"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "rate_limited"}
    assert result["description_placeholders"]["retry_after"] == "120"
    assert entry.data[CONF_PASSWORD] == MOCK_PASSWORD

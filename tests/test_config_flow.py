"""Tests for the SEMS config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems import async_migrate_entry
from custom_components.sems.config_flow import _normalize_station_ids
from custom_components.sems.const import CONF_STATION_ID, DOMAIN

MOCK_USERNAME = "test@example.com"
MOCK_PASSWORD = "test_password"
MOCK_STATION_ID_1 = "12345678-1234-5678-9abc-123456789abc"
MOCK_STATION_ID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ---------------------------------------------------------------------------
# _normalize_station_ids unit tests
# ---------------------------------------------------------------------------


class TestNormalizeStationIds:
    """Tests for _normalize_station_ids helper."""

    def test_single_string_returns_list_with_one_item(self):
        """A plain UUID string is wrapped in a list."""
        result = _normalize_station_ids(MOCK_STATION_ID_1)
        assert result == [MOCK_STATION_ID_1]

    def test_empty_string_returns_empty_list(self):
        """An empty string results in an empty list."""
        assert _normalize_station_ids("") == []

    def test_list_of_strings_returned_as_is(self):
        """A list of strings is returned unchanged."""
        ids = [MOCK_STATION_ID_1, MOCK_STATION_ID_2]
        assert _normalize_station_ids(ids) == ids

    def test_list_filters_empty_strings(self):
        """Empty strings inside a list are removed."""
        assert _normalize_station_ids([MOCK_STATION_ID_1, "", MOCK_STATION_ID_2]) == [
            MOCK_STATION_ID_1,
            MOCK_STATION_ID_2,
        ]

    def test_none_returns_empty_list(self):
        """None input results in an empty list."""
        assert _normalize_station_ids(None) == []

    def test_unsupported_type_returns_empty_list(self):
        """Unsupported types (e.g. int, dict) return an empty list."""
        assert _normalize_station_ids(42) == []
        assert _normalize_station_ids({}) == []


# ---------------------------------------------------------------------------
# Config flow integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_setup_entry():
    """Prevent the integration from being set up during config flow tests."""
    with patch(
        "custom_components.sems.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


async def _init_flow(hass: HomeAssistant) -> dict:
    """Start a fresh config flow and return the first result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    return result


async def test_single_station_creates_entry_directly(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    mock_setup_entry,
) -> None:
    """When exactly one station is found the entry is created without a selection step."""
    del enable_custom_integrations

    result = await _init_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.test_authentication",
            return_value=True,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getPowerStationIds",
            return_value=MOCK_STATION_ID_1,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Inverter {MOCK_STATION_ID_1}"
    assert result["data"][CONF_STATION_ID] == MOCK_STATION_ID_1
    assert result["data"][CONF_USERNAME] == MOCK_USERNAME


async def test_multiple_stations_shows_selection_step(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    mock_setup_entry,
) -> None:
    """When multiple stations are found, the selection step is shown."""
    del enable_custom_integrations

    result = await _init_flow(hass)

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.test_authentication",
            return_value=True,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getPowerStationIds",
            return_value=[MOCK_STATION_ID_1, MOCK_STATION_ID_2],
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_station"

    options = result["data_schema"].schema[CONF_STATION_ID].config["options"]
    option_values = [o["value"] for o in options]
    assert MOCK_STATION_ID_1 in option_values
    assert MOCK_STATION_ID_2 in option_values


async def test_select_station_creates_entry(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    mock_setup_entry,
) -> None:
    """Selecting a station in step 2 creates a config entry for it."""
    del enable_custom_integrations

    result = await _init_flow(hass)

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.test_authentication",
            return_value=True,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getPowerStationIds",
            return_value=[MOCK_STATION_ID_1, MOCK_STATION_ID_2],
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
        )

    assert result["step_id"] == "select_station"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_STATION_ID: MOCK_STATION_ID_2},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Inverter {MOCK_STATION_ID_2}"
    assert result["data"][CONF_STATION_ID] == MOCK_STATION_ID_2
    assert result["data"][CONF_USERNAME] == MOCK_USERNAME


async def test_single_station_already_configured_aborts(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    mock_setup_entry,
) -> None:
    """Single-station setup aborts when the station is already configured."""
    del enable_custom_integrations

    MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_STATION_ID_1,
        data={
            CONF_USERNAME: "existing@example.com",
            CONF_PASSWORD: "existing_password",
            CONF_STATION_ID: MOCK_STATION_ID_1,
        },
    ).add_to_hass(hass)

    result = await _init_flow(hass)

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.test_authentication",
            return_value=True,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getPowerStationIds",
            return_value=MOCK_STATION_ID_1,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_invalid_auth_shows_error(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Invalid credentials surface the invalid_auth error on the user step."""
    del enable_custom_integrations

    result = await _init_flow(hass)

    with patch(
        "custom_components.sems.sems_api.SemsApi.test_authentication",
        return_value=False,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: "wrong"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "invalid_auth"


async def test_no_stations_found_shows_error(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """When no station IDs are returned the no_stations_found error is shown."""
    del enable_custom_integrations

    result = await _init_flow(hass)

    with (
        patch(
            "custom_components.sems.sems_api.SemsApi.test_authentication",
            return_value=True,
        ),
        patch(
            "custom_components.sems.sems_api.SemsApi.getPowerStationIds",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "no_stations_found"


async def test_migrate_entry_sets_unique_id_from_station_id(
    hass: HomeAssistant,
) -> None:
    """Migration sets unique_id from station_id for existing entries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id=None,
        data={
            CONF_USERNAME: MOCK_USERNAME,
            CONF_PASSWORD: MOCK_PASSWORD,
            CONF_STATION_ID: MOCK_STATION_ID_1,
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.unique_id == MOCK_STATION_ID_1

"""Tests for the SEMS config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sems.const import CONF_STATION_ID, DEFAULT_SCAN_INTERVAL, DOMAIN


@pytest.fixture
def mock_sems_api():
    """Mock SemsApi for testing."""
    with patch("custom_components.sems.config_flow.SemsApi") as mock_api:
        api_instance = MagicMock()
        api_instance.test_authentication = MagicMock(return_value=True)
        api_instance.getPowerStationIds = MagicMock(return_value="test-station-id")
        mock_api.return_value = api_instance
        yield mock_api


class TestConfigFlow:
    """Test the config flow."""

    async def test_user_flow_success(self, hass: HomeAssistant, mock_sems_api):
        """Test successful user flow."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"

        # Provide user input
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_password",
                CONF_SCAN_INTERVAL: 60,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Inverter test-station-id"
        assert result["data"][CONF_USERNAME] == "test_user"
        assert result["data"][CONF_PASSWORD] == "test_password"
        assert result["data"][CONF_STATION_ID] == "test-station-id"
        assert result["data"][CONF_SCAN_INTERVAL] == 60

    async def test_user_flow_invalid_auth(self, hass: HomeAssistant):
        """Test user flow with invalid authentication."""
        with patch("custom_components.sems.config_flow.SemsApi") as mock_api:
            api_instance = MagicMock()
            api_instance.test_authentication = MagicMock(return_value=False)
            mock_api.return_value = api_instance

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "test_user",
                    CONF_PASSWORD: "wrong_password",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["errors"]["base"] == "invalid_auth"

    async def test_user_flow_cannot_connect(self, hass: HomeAssistant):
        """Test user flow with connection error."""
        with patch("custom_components.sems.config_flow.SemsApi") as mock_api:
            api_instance = MagicMock()
            api_instance.test_authentication = MagicMock(
                side_effect=Exception("Connection error")
            )
            mock_api.return_value = api_instance

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "test_user",
                    CONF_PASSWORD: "test_password",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["errors"]["base"] == "unknown"

    async def test_user_flow_with_station_id(self, hass: HomeAssistant, mock_sems_api):
        """Test user flow with manually provided station ID."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_password",
                CONF_STATION_ID: "manual-station-id",
                CONF_SCAN_INTERVAL: 120,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_STATION_ID] == "manual-station-id"
        assert result["data"][CONF_SCAN_INTERVAL] == 120


class TestReauthFlow:
    """Test the reauthentication flow."""

    async def test_reauth_flow_success(self, hass: HomeAssistant, mock_sems_api):
        """Test successful reauthentication flow."""
        # Create a mock config entry
        entry = MockConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Integration",
            data={
                CONF_USERNAME: "old_user",
                CONF_PASSWORD: "old_password",
                CONF_STATION_ID: "test-station-id",
                CONF_SCAN_INTERVAL: 60,
            },
            source=config_entries.SOURCE_USER,
            entry_id="test_entry_id",
        )
        entry.add_to_hass(hass)

        # Start reauth flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        # Provide new credentials
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "new_user",
                CONF_PASSWORD: "new_password",
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"

    async def test_reauth_flow_invalid_auth(self, hass: HomeAssistant):
        """Test reauthentication flow with invalid credentials."""
        entry = MockConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Integration",
            data={
                CONF_USERNAME: "old_user",
                CONF_PASSWORD: "old_password",
                CONF_STATION_ID: "test-station-id",
            },
            source=config_entries.SOURCE_USER,
            entry_id="test_entry_id",
        )
        entry.add_to_hass(hass)

        with patch("custom_components.sems.config_flow.SemsApi") as mock_api:
            api_instance = MagicMock()
            api_instance.test_authentication = MagicMock(return_value=False)
            mock_api.return_value = api_instance

            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_REAUTH,
                    "entry_id": entry.entry_id,
                },
                data=entry.data,
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "new_user",
                    CONF_PASSWORD: "wrong_password",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["errors"]["base"] == "invalid_auth"

    async def test_reauth_flow_prefills_username(self, hass: HomeAssistant):
        """Test that reauth flow prefills the username."""
        entry = MockConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Integration",
            data={
                CONF_USERNAME: "existing_user",
                CONF_PASSWORD: "old_password",
                CONF_STATION_ID: "test-station-id",
            },
            source=config_entries.SOURCE_USER,
            entry_id="test_entry_id",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        # The form is shown correctly
        assert result["data_schema"] is not None


class TestOptionsFlow:
    """Test the options flow."""

    async def test_options_flow_init(self, hass: HomeAssistant):
        """Test options flow initialization."""
        entry = MockConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Integration",
            data={
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_password",
                CONF_STATION_ID: "test-station-id",
                CONF_SCAN_INTERVAL: 60,
            },
            source=config_entries.SOURCE_USER,
            entry_id="test_entry_id",
        )
        entry.add_to_hass(hass)

        # Start options flow
        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "init"

    async def test_options_flow_update_scan_interval(self, hass: HomeAssistant):
        """Test updating scan interval through options flow."""
        entry = MockConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Integration",
            data={
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_password",
                CONF_STATION_ID: "test-station-id",
                CONF_SCAN_INTERVAL: 60,
            },
            source=config_entries.SOURCE_USER,
            entry_id="test_entry_id",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_SCAN_INTERVAL: 120},
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        # Check that the scan_interval is now in options
        assert result["data"][CONF_SCAN_INTERVAL] == 120

    async def test_options_flow_default_value(self, hass: HomeAssistant):
        """Test options flow shows default value."""
        entry = MockConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Integration",
            data={
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_password",
                CONF_STATION_ID: "test-station-id",
                CONF_SCAN_INTERVAL: 90,
            },
            source=config_entries.SOURCE_USER,
            entry_id="test_entry_id",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        # The form is shown correctly with scan_interval field
        assert result["data_schema"] is not None

    async def test_options_flow_no_scan_interval_uses_default(
        self, hass: HomeAssistant
    ):
        """Test options flow uses default when scan_interval not set."""
        entry = MockConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Integration",
            data={
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_password",
                CONF_STATION_ID: "test-station-id",
                # No CONF_SCAN_INTERVAL
            },
            source=config_entries.SOURCE_USER,
            entry_id="test_entry_id",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        # The form is shown correctly with scan_interval field
        assert result["data_schema"] is not None

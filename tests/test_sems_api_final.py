"""Tests for the SEMS API module."""

import pytest
import requests

from custom_components.sems.sems_api import OutOfRetries, SemsApi, AuthenticationError

# Test data constants - anonymized for privacy
MOCK_INVERTER_SN = "GW0000SN000TEST1"
MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"
SUCCESS_MESSAGE = "操作成功"


class TestSemsApi:
    """Test class for SemsApi."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = {}  # Mock hass object
        self.username = "test_user"
        self.password = "test_password"
        self.api = SemsApi(self.hass, self.username, self.password)

    def test_initialization(self):
        """Test SemsApi initialization."""
        api = SemsApi(self.hass, self.username, self.password)
        # Test that the object is created successfully
        assert api is not None

    def test_successful_login(self, requests_mock):
        """Test successful login token retrieval with real SEMS API response structure."""
        login_response = {
            "language": "en",
            "function": [
                "ADD",
                "VIEW",
                "EDIT",
                "DELETE",
                "INVERTER_A",
                "INVERTER_E",
                "INVERTER_D",
            ],
            "hasError": False,
            "msg": SUCCESS_MESSAGE,
            "code": "0",
            "data": {
                "uid": "test-uid-123",
                "timestamp": 1757355815062,
                "token": "test-token-abc123",
                "client": "ios",
                "version": "",
                "language": "en",
            },
            "api": "https://eu.semsportal.com/api/",
        }

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.getLoginToken(self.username, self.password)

        assert result is not None
        assert result["uid"] == "test-uid-123"
        assert result["token"] == "test-token-abc123"
        assert result["api"] == "https://eu.semsportal.com/api/"

    def test_failed_login_invalid_credentials(self, requests_mock):
        """Test failed login with invalid credentials."""
        login_response = {
            "hasError": True,
            "code": 1001,
            "msg": "Invalid credentials",
            "data": None,
        }

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.getLoginToken(self.username, self.password)

        assert result is None

    def test_login_network_error(self, requests_mock):
        """Test login with network error."""
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin",
            exc=requests.ConnectionError("Network error"),
        )

        result = self.api.getLoginToken(self.username, self.password)

        assert result is None

    def test_authentication_success(self, requests_mock):
        """Test successful authentication test."""
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.test_authentication()

        assert result is True

    def test_authentication_failure(self, requests_mock):
        """Test failed authentication test."""
        login_response = {"code": 1001, "msg": "Invalid credentials", "data": None}

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.test_authentication()

        assert result is False

    def test_get_power_station_ids_success(self, requests_mock):
        """Test successful power station IDs retrieval."""
        # Mock login
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        # Mock power station IDs response with realistic UUID
        station_response = {
            "code": 0,
            "data": MOCK_POWER_STATION_ID,
            "msg": SUCCESS_MESSAGE,
        }
        requests_mock.post(
            "https://eu.semsportal.com/api//PowerStation/GetPowerStationIdByOwner",
            json=station_response,
        )

        result = self.api.getPowerStationIds()

        assert result == MOCK_POWER_STATION_ID

    def test_get_data_success(self, requests_mock):
        """Test successful data retrieval with real SEMS API response structure."""
        # Mock login
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        # Mock data response using real SEMS API structure
        data_response = {
            "language": "en",
            "function": [
                "ADD",
                "VIEW",
                "EDIT",
                "DELETE",
                "INVERTER_A",
                "INVERTER_E",
                "INVERTER_D",
            ],
            "hasError": False,
            "msg": SUCCESS_MESSAGE,
            "code": "0",
            "data": {
                "info": {
                    "powerstation_id": MOCK_POWER_STATION_ID,
                    "time": "09/08/2025 16:48:27",
                    "stationname": "Impala",
                    "address": "Utrecht, Netherlands",
                    "capacity": 3.2,
                    "status": 1,
                },
                "kpi": {
                    "month_generation": 85.7,
                    "pac": 589.0,
                    "power": 8.9,
                    "total_power": 18843.2,
                    "day_income": 1.96,
                    "total_income": 4145.5,
                    "currency": "EUR",
                },
                "inverter": [
                    {
                        "sn": MOCK_INVERTER_SN,
                        "name": "Zolder",
                        "in_pac": 1.8,
                        "out_pac": 589.0,
                        "eday": 8.9,
                        "emonth": 76.8,
                        "etotal": 18843.2,
                        "status": 1,
                        "type": "GW3000-NS",
                        "capacity": 3.0,
                        "tempperature": 32.0,
                    }
                ],
            },
        }
        endpoint = "https://eu.semsportal.com/api//v3/PowerStation/GetMonitorDetailByPowerstationId"
        requests_mock.post(endpoint, json=data_response)

        result = self.api.getData(MOCK_POWER_STATION_ID)

        # Verify we get the actual data structure back
        assert result["info"]["powerstation_id"] == MOCK_POWER_STATION_ID
        assert result["info"]["stationname"] == "Impala"
        assert result["kpi"]["pac"] == 589.0
        assert result["kpi"]["total_power"] == 18843.2
        assert len(result["inverter"]) == 1
        assert result["inverter"][0]["sn"] == MOCK_INVERTER_SN
        assert result["inverter"][0]["out_pac"] == 589.0
        assert result["inverter"][0]["eday"] == 8.9

    def test_get_data_raises_authentication_error_on_failure(self, requests_mock):
        """Test getData raises AuthenticationError on login failure."""
        # Mock login failure
        login_response = {"code": 1001, "msg": "Invalid credentials", "data": None}
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        with pytest.raises(AuthenticationError, match="Authentication failed"):
            self.api.getData("station123")

    def test_change_status_success(self, requests_mock):
        """Test successful inverter status change."""
        # Mock login
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        # Mock control response (HTTP 200 indicates success for control API)
        endpoint = (
            "https://eu.semsportal.com/api//PowerStation/SaveRemoteControlInverter"
        )
        requests_mock.post(endpoint, json={"status": "success"}, status_code=200)

        # Should not raise exception
        self.api.change_status(MOCK_INVERTER_SN, 1)

    def test_change_status_http_error(self, requests_mock):
        """Test inverter status change with HTTP error."""
        # Mock login
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        # Mock control error response
        endpoint = (
            "https://eu.semsportal.com/api//PowerStation/SaveRemoteControlInverter"
        )
        requests_mock.post(endpoint, status_code=401)

        # Should raise OutOfRetries after exhausting retries
        with pytest.raises(OutOfRetries):
            self.api.change_status(MOCK_INVERTER_SN, 1)

    def test_api_call_with_token_retry(self, requests_mock):
        """Test API call that retries with new token on failure."""
        # Mock login responses (will be called twice)
        login_responses = [
            {
                "code": 0,
                "data": {"uid": "test-uid", "token": "old-token"},
                "api": "https://eu.semsportal.com/api/",
            },
            {
                "code": 0,
                "data": {"uid": "test-uid", "token": "new-token"},
                "api": "https://eu.semsportal.com/api/",
            },
        ]
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin",
            [{"json": resp} for resp in login_responses],
        )

        # Mock API call responses (failure then success)
        api_responses = [
            {"code": 1002, "msg": "Token expired", "data": None},
            {"code": 0, "data": MOCK_POWER_STATION_ID, "msg": SUCCESS_MESSAGE},
        ]
        endpoint = (
            "https://eu.semsportal.com/api//PowerStation/GetPowerStationIdByOwner"
        )
        requests_mock.post(endpoint, [{"json": resp} for resp in api_responses])

        result = self.api.getPowerStationIds()

        assert result == MOCK_POWER_STATION_ID

    def test_max_retries_exceeded(self):
        """Test that OutOfRetries is raised when max retries exceeded."""
        with pytest.raises(OutOfRetries):
            # This should raise OutOfRetries immediately since maxTokenRetries=0
            self.api.getPowerStationIds(maxTokenRetries=0)


class TestOutOfRetries:
    """Test OutOfRetries exception."""

    def test_out_of_retries_creation(self):
        """Test OutOfRetries exception creation."""
        exception = OutOfRetries("Test message")
        assert str(exception) == "Test message"
        assert isinstance(exception, Exception)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

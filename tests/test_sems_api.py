"""Tests for the SEMS API module."""

import json
from unittest.mock import Mock, patch, MagicMock
import pytest
import requests

from custom_components.sems.sems_api import OutOfRetries, SemsApi

# Test data constants - anonymized for privacy
MOCK_INVERTER_SN = "GW0000SN000TEST1"
MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"
SUCCESS_MESSAGE = "操作成功"


class TestSemsApi:
    """Test class for SemsApi."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = Mock()
        self.username = "test_user"
        self.password = "test_password"
        self.api = SemsApi(self.hass, self.username, self.password)

    def test_init(self):
        """Test SemsApi initialization."""
        assert self.api._hass == self.hass
        assert self.api._username == self.username
        assert self.api._password == self.password
        assert self.api._token is None

    @patch("custom_components.sems.sems_api.requests.post")
    def test_make_http_request_success(self, mock_post):
        """Test successful HTTP request."""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": 0, "data": {"test": "value"}}'
        mock_response.json.return_value = {"code": 0, "data": {"test": "value"}}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.api._make_http_request(
            "http://test.com",
            {"Content-Type": "application/json"},
            data='{"test": "data"}',
            operation_name="test operation",
        )

        assert result == {"code": 0, "data": {"test": "value"}}
        mock_post.assert_called_once_with(
            "http://test.com",
            headers={"Content-Type": "application/json"},
            data='{"test": "data"}',
            json=None,
            timeout=30,
        )

    @patch("custom_components.sems.sems_api.requests.post")
    def test_make_http_request_validation_failure(self, mock_post):
        """Test HTTP request with validation failure."""
        # Mock response with error code
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": 1001, "msg": "Invalid credentials"}'
        mock_response.json.return_value = {"code": 1001, "msg": "Invalid credentials"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.api._make_http_request(
            "http://test.com",
            {"Content-Type": "application/json"},
            operation_name="test operation",
            validate_code=True,
        )

        assert result is None

    @patch("custom_components.sems.sems_api.requests.post")
    def test_make_http_request_missing_data(self, mock_post):
        """Test HTTP request with missing data field."""
        # Mock response with missing data
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": 0, "data": null}'
        mock_response.json.return_value = {"code": 0, "data": None}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.api._make_http_request(
            "http://test.com",
            {"Content-Type": "application/json"},
            operation_name="test operation",
            validate_code=True,
        )

        assert result is None

    @patch("custom_components.sems.sems_api.requests.post")
    def test_make_http_request_no_validation(self, mock_post):
        """Test HTTP request without validation."""
        # Mock response with error code but validation disabled
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": 1001, "msg": "Error"}'
        mock_response.json.return_value = {"code": 1001, "msg": "Error"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.api._make_http_request(
            "http://test.com",
            {"Content-Type": "application/json"},
            operation_name="test operation",
            validate_code=False,
        )

        assert result == {"code": 1001, "msg": "Error"}

    @patch("custom_components.sems.sems_api.requests.post")
    def test_make_http_request_network_error(self, mock_post):
        """Test HTTP request with network error."""
        mock_post.side_effect = requests.ConnectionError("Network error")

        with pytest.raises(requests.ConnectionError):
            self.api._make_http_request(
                "http://test.com",
                {"Content-Type": "application/json"},
                operation_name="test operation",
            )

    @patch.object(SemsApi, "_make_http_request")
    def test_get_login_token_success(self, mock_http_request):
        """Test successful login token retrieval."""
        mock_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token", "timestamp": 1234567890},
            "api": "https://api.test.com/",
        }
        mock_http_request.return_value = mock_response

        result = self.api.getLoginToken("test_user", "test_pass")

        expected_token = {
            "uid": "test-uid",
            "token": "test-token",
            "timestamp": 1234567890,
            "api": "https://api.test.com/",
        }
        assert result == expected_token
        mock_http_request.assert_called_once()

    @patch.object(SemsApi, "_make_http_request")
    def test_get_login_token_failure(self, mock_http_request):
        """Test failed login token retrieval."""
        mock_http_request.return_value = None

        result = self.api.getLoginToken("test_user", "test_pass")

        assert result is None

    @patch.object(SemsApi, "_make_http_request")
    def test_get_login_token_exception(self, mock_http_request):
        """Test login token retrieval with exception."""
        mock_http_request.side_effect = requests.RequestException("Network error")

        result = self.api.getLoginToken("test_user", "test_pass")

        assert result is None

    def test_test_authentication_success(self):
        """Test successful authentication test."""
        with patch.object(self.api, "getLoginToken") as mock_login:
            mock_login.return_value = {"token": "test-token"}

            result = self.api.test_authentication()

            assert result is True
            assert self.api._token == {"token": "test-token"}

    def test_test_authentication_failure(self):
        """Test failed authentication test."""
        with patch.object(self.api, "getLoginToken") as mock_login:
            mock_login.return_value = None

            result = self.api.test_authentication()

            assert result is False

    def test_test_authentication_exception(self):
        """Test authentication test with exception."""
        with patch.object(self.api, "getLoginToken") as mock_login:
            mock_login.side_effect = Exception("Test error")

            result = self.api.test_authentication()

            assert result is False

    def test_successful_login_real_structure(self, requests_mock):
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

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_success(self, mock_http_request, mock_login):
        """Test successful API call."""
        # Set up token
        self.api._token = {"token": "test-token", "api": "https://api.test.com"}

        mock_response = {"code": 0, "data": {"result": "success"}}
        mock_http_request.return_value = mock_response

        result = self.api._make_api_call(
            "/test/endpoint", data='{"test": "data"}', operation_name="test API call"
        )

        assert result == {"result": "success"}
        mock_http_request.assert_called_once()

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_token_renewal(self, mock_http_request, mock_login):
        """Test API call with token renewal."""
        # No initial token
        self.api._token = None

        mock_login.return_value = {"token": "new-token", "api": "https://api.test.com"}

        mock_response = {"code": 0, "data": {"result": "success"}}
        mock_http_request.return_value = mock_response

        result = self.api._make_api_call(
            "/test/endpoint", operation_name="test API call"
        )

        assert result == {"result": "success"}
        mock_login.assert_called_once_with(self.username, self.password)

    @patch.object(SemsApi, "getLoginToken")
    def test_make_api_call_login_failure(self, mock_login):
        """Test API call with login failure."""
        self.api._token = None
        mock_login.return_value = None

        result = self.api._make_api_call(
            "/test/endpoint", operation_name="test API call"
        )

        assert result is None

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_retry_on_failure(self, mock_http_request, mock_login):
        """Test API call retry on validation failure."""
        # Set up token
        self.api._token = {"token": "test-token", "api": "https://api.test.com"}

        # First call fails validation, second succeeds
        mock_http_request.side_effect = [
            None,  # First call fails validation
            {"code": 0, "data": {"result": "success"}},  # Second call succeeds
        ]

        mock_login.return_value = {"token": "new-token", "api": "https://api.test.com"}

        result = self.api._make_api_call(
            "/test/endpoint", operation_name="test API call", maxTokenRetries=2
        )

        assert result == {"result": "success"}
        assert mock_http_request.call_count == 2
        mock_login.assert_called_once()

    @patch.object(SemsApi, "getLoginToken")
    def test_make_api_call_max_retries_exceeded(self, mock_login):
        """Test API call with max retries exceeded."""
        self.api._token = None

        with pytest.raises(OutOfRetries):
            self.api._make_api_call(
                "/test/endpoint", maxTokenRetries=0, operation_name="test API call"
            )

    @patch.object(SemsApi, "_make_api_call")
    def test_get_power_station_ids(self, mock_api_call):
        """Test getPowerStationIds method."""
        mock_api_call.return_value = "station123"

        result = self.api.getPowerStationIds()

        assert result == "station123"
        mock_api_call.assert_called_once_with(
            "/PowerStation/GetPowerStationIdByOwner",
            data=None,
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getPowerStationIds API call",
        )

    def test_get_power_station_ids_success_real_structure(self, requests_mock):
        """Test successful power station IDs retrieval with realistic response structure."""
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

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

    @patch.object(SemsApi, "_make_api_call")
    def test_get_data(self, mock_api_call):
        """Test getData method."""
        mock_api_call.return_value = {"power": 1500, "energy": 25.5}

        result = self.api.getData("station123")

        assert result == {"power": 1500, "energy": 25.5}
        mock_api_call.assert_called_once_with(
            "/v3/PowerStation/GetMonitorDetailByPowerstationId",
            data='{"powerStationId":"station123"}',
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getData API call",
        )

    def test_get_data_success_real_structure(self, requests_mock):
        """Test successful data retrieval with real SEMS API response structure."""
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

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

        assert result["info"]["powerstation_id"] == MOCK_POWER_STATION_ID
        assert result["info"]["stationname"] == "Impala"
        assert result["kpi"]["pac"] == 589.0
        assert result["kpi"]["total_power"] == 18843.2
        assert len(result["inverter"]) == 1
        assert result["inverter"][0]["sn"] == MOCK_INVERTER_SN
        assert result["inverter"][0]["out_pac"] == 589.0
        assert result["inverter"][0]["eday"] == 8.9

    @patch.object(SemsApi, "_make_api_call")
    def test_get_data_returns_empty_dict_on_none(self, mock_api_call):
        """Test getData method returns empty dict when API call returns None."""
        mock_api_call.return_value = None

        result = self.api.getData("station123")

        assert result == {}

    def test_get_data_returns_empty_on_failure(self, requests_mock):
        """Test getData returns empty dict on login failure."""
        login_response = {"code": 1001, "msg": "Invalid credentials", "data": None}
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.getData("station123")

        assert result == {}

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_control_api_call_success(self, mock_http_request, mock_login):
        """Test successful control API call."""
        # Set up token
        self.api._token = {"token": "test-token", "api": "https://api.test.com"}

        # Control API doesn't validate response code, just HTTP status
        mock_http_request.return_value = {"status": "success"}

        result = self.api._make_control_api_call(
            {"command": "start"}, operation_name="test control call"
        )

        assert result is True
        mock_http_request.assert_called_once()

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_control_api_call_http_error(self, mock_http_request, mock_login):
        """Test control API call with HTTP error."""
        # Set up token
        self.api._token = {"token": "test-token", "api": "https://api.test.com"}

        # Mock HTTP error
        mock_response = Mock()
        mock_response.status_code = 401
        http_error = requests.HTTPError("Unauthorized")
        http_error.response = mock_response
        mock_http_request.side_effect = http_error

        mock_login.return_value = {"token": "new-token", "api": "https://api.test.com"}

        # Should retry once and then raise OutOfRetries
        with pytest.raises(OutOfRetries):
            self.api._make_control_api_call(
                {"command": "start"},
                operation_name="test control call",
                maxTokenRetries=1,
            )

    @patch.object(SemsApi, "_make_control_api_call")
    def test_change_status(self, mock_control_call):
        """Test change_status method."""
        mock_control_call.return_value = True

        self.api.change_status("inverter123", 1)

        expected_data = {
            "InverterSN": "inverter123",
            "InverterStatusSettingMark": "1",
            "InverterStatus": "1",
        }
        mock_control_call.assert_called_once_with(
            expected_data,
            renewToken=False,
            maxTokenRetries=2,
            operation_name="power control command for inverter inverter123",
        )

    def test_change_status_success_real_structure(self, requests_mock):
        """Test successful inverter status change."""
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        endpoint = (
            "https://eu.semsportal.com/api//PowerStation/SaveRemoteControlInverter"
        )
        requests_mock.post(endpoint, json={"status": "success"}, status_code=200)

        self.api.change_status(MOCK_INVERTER_SN, 1)

    @patch.object(SemsApi, "_make_control_api_call")
    def test_change_status_failure(self, mock_control_call):
        """Test change_status method with failure."""
        mock_control_call.return_value = False

        # Should not raise exception, just log error
        self.api.change_status("inverter123", 1)

        mock_control_call.assert_called_once()


class TestOutOfRetries:
    """Test OutOfRetries exception."""

    def test_out_of_retries_exception(self):
        """Test OutOfRetries exception creation."""
        exception = OutOfRetries("Test message")
        assert str(exception) == "Test message"
        assert isinstance(exception, Exception)


if __name__ == "__main__":
    pytest.main([__file__])

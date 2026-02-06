"""Tests for the SEMS API module."""

import json
from unittest.mock import Mock, patch, MagicMock
import pytest
import requests

from custom_components.sems.sems_api import SemsApi, OutOfRetries


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
        """Test getPowerStationId method."""
        mock_api_call.return_value = "station123"

        result = self.api.getPowerStationId()

        assert result == "station123"
        mock_api_call.assert_called_once_with(
            "/PowerStation/GetPowerStationIdByOwner",
            data=None,
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getPowerStationId API call",
        )

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

    @patch.object(SemsApi, "_make_api_call")
    def test_get_data_returns_empty_dict_on_none(self, mock_api_call):
        """Test getData method returns empty dict when API call returns None."""
        mock_api_call.return_value = None

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

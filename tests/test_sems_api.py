"""Tests for the SEMS API module."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock, call, patch

import pytest
import requests
from homeassistant.exceptions import HomeAssistantError

from custom_components.sems.const import redact_for_log
from custom_components.sems.sems_api import (
    NEW_LOGIN_URL,
    OLD_LOGIN_URL,
    OutOfRetries,
    SemsApi,
    SemsAuthExpiredError,
    SemsPermissionError,
    SemsRateLimitedError,
)

# Test data constants - anonymized for privacy
MOCK_INVERTER_SN = "GW0000SN000TEST1"
MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"
SUCCESS_MESSAGE = "操作成功"
API_EXAMPLES_DIR = Path(__file__).parent.parent / "api_examples"


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

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_get_web_login_token")
    def test_authentication_reuses_web_token(
        self, mock_web_login, mock_get_login_token
    ):
        """Test Web authentication is reused for station discovery."""
        web_token = {"client": "semsPlusWeb", "api": "https://api.test.com"}
        mock_web_login.return_value = web_token

        assert self.api.test_authentication() is True

        assert self.api._web_token == web_token
        mock_web_login.assert_called_once_with(self.username, self.password)
        mock_get_login_token.assert_not_called()

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_get_web_login_token")
    def test_authentication_falls_back_when_web_login_fails(
        self, mock_web_login, mock_get_login_token
    ):
        """Test legacy authentication remains available as a fallback."""
        mock_web_login.return_value = None
        mock_get_login_token.return_value = {"token": "legacy-token"}

        assert self.api.test_authentication() is True

        mock_get_login_token.assert_called_once_with(self.username, self.password)

    def test_web_station_statistics_parses_only_finite_values(self):
        """Test station statistics parsing ignores malformed values."""
        with patch.object(
            self.api,
            "_make_api_call",
            return_value={
                "proSelfConsumRate": 63.85,
                "contributionRate": 59.43,
                "dataList": [
                    {
                        "item": "proSystemTotalStats",
                        "statisticsList": [
                            {"val": "1.25"},
                            {"val": "not-a-number"},
                            {"val": "Infinity"},
                        ],
                    }
                ],
            },
        ) as mock_call:
            result = self.api._get_web_statistics(
                MOCK_POWER_STATION_ID,
                "day",
                datetime(2026, 1, 1),
                datetime(2026, 1, 2),
            )

        assert result == {
            "proSystemTotalStats": [1.25],
            "proSelfConsumRate": [63.85],
            "contributionRate": [59.43],
        }
        request = json.loads(mock_call.call_args.kwargs["data"])
        assert request["stationId"] == MOCK_POWER_STATION_ID
        assert request["dimension"] == "day"
        assert request["items"]
        assert request["isReport"] is False
        assert request["startTime"] == "2026-01-01 00:00:00"
        assert request["endTime"] == "2026-01-02 00:00:00"

    @patch.object(
        SemsApi,
        "_get_web_statistics",
        return_value={"proSystemTotalStats": [1.0]},
    )
    @patch.object(
        SemsApi,
        "_get_web_production",
        return_value={"currency": "EUR"},
    )
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_web_energy_statistics_batches_historic_years(
        self, mock_now, mock_production, mock_statistics
    ):
        """Test historical years are requested in one range."""
        mock_now.return_value = datetime(2026, 9, 25)
        inverters = [{"invert_full": {"addTime": "1545351495000"}}]

        result = self.api._get_web_energy_statistics("station", inverters)

        assert result is not None
        assert mock_production.called
        assert mock_statistics.call_count == 3
        assert any(
            call_args.args[1:]
            == (
                "year",
                datetime(2018, 1, 1),
                datetime(2027, 1, 1) - timedelta(seconds=1),
            )
            for call_args in mock_statistics.call_args_list
        )
        assert not any(
            call_args.args[1:]
            == (
                "day",
                datetime(2026, 8, 1),
                datetime(2026, 8, 31, 23, 59, 59),
            )
            for call_args in mock_statistics.call_args_list
        )

    @patch.object(
        SemsApi,
        "_get_web_statistics",
        return_value={"proSystemTotalStats": [1.0, 2.0]},
    )
    @patch.object(SemsApi, "_get_web_production", return_value=None)
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_web_energy_statistics_skips_missing_series(
        self, mock_now, mock_production, mock_statistics
    ):
        """Test series missing from station statistics are not reported as 0."""
        mock_now.return_value = datetime(2026, 9, 25)

        result = self.api._get_web_energy_statistics("station", [])

        assert result is not None
        charts, _totals, _currency, _last_month = result
        assert charts == {"sum": 3.0}

    @patch.object(
        SemsApi,
        "_get_web_energy_statistics",
        return_value=({"sum": 5.0, "buy": 0, "sell": 0}, {"sum": 100.0}, "EUR", 42.0),
    )
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_get_web_data_prefers_smart_meter_counters(self, mock_now, mock_statistics):
        """Test captured smart-meter counters override station statistics."""
        mock_now.return_value = datetime(2026, 9, 25, 12)

        def load(name):
            with open(API_EXAMPLES_DIR / name, encoding="utf-8") as file:
                return json.load(file)["data"]

        def fake_api_call(url_part, *args, **kwargs):
            if "all-status" in url_part:
                return load("smart_meter_all_status.json")
            if "stations/flow" in url_part:
                return load("station_flow_import.json")
            if "SMART_METER" in url_part and "telecounting" in url_part:
                return load("smart_meter_telecounting.json")
            if "SMART_METER" in url_part and "telemetry" in url_part:
                return load("smart_meter_telemetry.json")
            return []

        with patch.object(SemsApi, "_make_api_call", side_effect=fake_api_call):
            result = self.api.getWebData("station")

        assert result["hasEnergeStatisticsCharts"] is True
        assert result["energeStatisticsCharts"] == {
            "sum": 5.0,
            "buy": 12.84,
            "sell": 36.77,
        }
        assert result["energeStatisticsTotals"] == {
            "sum": 100.0,
            "buy": 20314.77,
            "sell": 38846.49,
        }
        assert result["kpi"] == {"currency": "EUR"}
        # Last month's PV is set when the station has a single real inverter.
        assert [
            inverter["invert_full"].get("lastmonthetotle")
            for inverter in result["inverter"]
        ] == [42.0]

    @patch.object(
        SemsApi,
        "_get_web_statistics",
        return_value={"proSystemTotalStats": [1.0]},
    )
    @patch.object(
        SemsApi,
        "_get_web_production",
        return_value={"currency": 123},
    )
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_web_energy_statistics_ignores_non_string_currency(
        self, mock_now, _mock_production, _mock_statistics
    ):
        """Test non-string currency values are ignored."""
        mock_now.return_value = datetime(2026, 9, 25)

        result = self.api._get_web_energy_statistics("station", [])

        assert result is not None
        _charts, _totals, currency, _last_month_pv = result
        assert currency is None

    @patch.object(SemsApi, "_make_api_call")
    def test_web_station_production_uses_web_request_contract(self, mock_api_call):
        """Test optional station production totals and currency request."""
        mock_api_call.return_value = {
            "proSystemTotalStats": 31.4,
            "currency": "EUR",
        }

        result = self.api._get_web_production(
            "station",
            datetime(2026, 1, 1),
            datetime(2026, 1, 1, 23, 59, 59),
        )

        assert result == {"proSystemTotalStats": 31.4, "currency": "EUR"}
        mock_api_call.assert_called_once()
        request = json.loads(mock_api_call.call_args.kwargs["data"])
        assert request["items"]
        assert request["isReport"] is False
        assert request["startTime"] == "2026-01-01 00:00:00"
        assert request["endTime"] == "2026-01-01 23:59:59"

    @patch("custom_components.sems.sems_api.requests.Session.request")
    def test_make_http_request_success(self, mock_request):
        """Test successful HTTP request."""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": 0, "data": {"test": "value"}}'
        mock_response.json.return_value = {"code": 0, "data": {"test": "value"}}
        mock_response.raise_for_status.return_value = None
        mock_request.return_value = mock_response

        result = self.api._make_http_request(
            "http://test.com",
            {"Content-Type": "application/json"},
            data='{"test": "data"}',
            operation_name="test operation",
        )

        assert result == {"code": 0, "data": {"test": "value"}}
        mock_request.assert_called_once_with(
            "POST",
            "http://test.com",
            headers={
                "User-Agent": "Home Assistant GoodWe SEMS API Integration",
                "Content-Type": "application/json",
            },
            data='{"test": "data"}',
            json=None,
            timeout=30,
        )

    @patch("custom_components.sems.sems_api.requests.Session.request")
    def test_make_http_request_validation_failure(self, mock_request):
        """Test HTTP request with validation failure."""
        # Mock response with error code
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": 1001, "msg": "Invalid credentials"}'
        mock_response.json.return_value = {"code": 1001, "msg": "Invalid credentials"}
        mock_response.raise_for_status.return_value = None
        mock_request.return_value = mock_response

        result = self.api._make_http_request(
            "http://test.com",
            {"Content-Type": "application/json"},
            operation_name="test operation",
            validate_code=True,
        )

        assert result is None

    @patch("custom_components.sems.sems_api.requests.Session.request")
    def test_make_http_request_no_validation(self, mock_request):
        """Test HTTP request without validation."""
        # Mock response with error code but validation disabled
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": 1001, "msg": "Error"}'
        mock_response.json.return_value = {"code": 1001, "msg": "Error"}
        mock_response.raise_for_status.return_value = None
        mock_request.return_value = mock_response

        result = self.api._make_http_request(
            "http://test.com",
            {"Content-Type": "application/json"},
            operation_name="test operation",
            validate_code=False,
        )

        assert result == {"code": 1001, "msg": "Error"}

    @patch("custom_components.sems.sems_api.requests.Session.request")
    def test_make_http_request_network_error(self, mock_request):
        """Test HTTP request with network error."""
        mock_request.side_effect = requests.ConnectionError("Network error")

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

    def test_hash_password_for_new_login(self):
        """Test SEMS+ password encoding."""
        assert self.api._hash_password_for_new_login("sems_test_password") == (
            "ZTJmYTRkNDJhZTk4Y2NiMTFkYzg0NWJhYWY1YWUxYzc="
        )

    def test_get_login_token_new_success_skips_legacy(self):
        """Test new login success without calling the legacy fallback."""
        new_token = {
            "uid": "legacy-uid",
            "token": "legacy-token",
            "api": "https://api.test.com/",
        }

        with (
            patch.object(self.api, "_get_legacy_login_token") as mock_legacy,
            patch.object(self.api, "_get_new_login_token") as mock_new,
        ):
            mock_new.return_value = new_token

            result = self.api.getLoginToken("test_user", "test_pass")

            assert result == new_token
            mock_new.assert_called_once_with("test_user", "test_pass")
            mock_legacy.assert_not_called()
            assert self.api._preferred_login_mode == "new"

    def test_get_login_token_new_failure_legacy_success(self):
        """Test fallback from new login to legacy login."""
        legacy_token = {
            "uid": "new-uid",
            "token": "new-token",
            "api": "https://api.test.com/",
        }

        with (
            patch.object(self.api, "_get_legacy_login_token") as mock_legacy,
            patch.object(self.api, "_get_new_login_token") as mock_new,
        ):
            mock_new.return_value = None
            mock_legacy.return_value = legacy_token

            result = self.api.getLoginToken("test_user", "test_pass")

            assert result == legacy_token
            mock_new.assert_called_once_with("test_user", "test_pass")
            mock_legacy.assert_called_once_with("test_user", "test_pass")
            assert self.api._preferred_login_mode == "legacy"

    def test_get_login_token_both_fail(self):
        """Test login failure when all login modes fail."""
        with (
            patch.object(self.api, "_get_legacy_login_token") as mock_legacy,
            patch.object(self.api, "_get_new_login_token") as mock_new,
        ):
            mock_legacy.return_value = None
            mock_new.return_value = None

            result = self.api.getLoginToken("test_user", "test_pass")

            assert result is None
            mock_legacy.assert_called_once_with("test_user", "test_pass")
            assert mock_new.call_count == 2
            mock_new.assert_has_calls(
                [
                    call("test_user", "test_pass"),
                    call("test_user", "test_pass", is_web=True),
                ]
            )

    def test_get_login_token_web_fallback(self):
        """Test fallback to SEMS+ web login when other login modes fail."""
        web_token = {
            "uid": "web-uid",
            "token": "web-token",
            "api": "https://api.test.com/",
        }

        with (
            patch.object(self.api, "_get_legacy_login_token") as mock_legacy,
            patch.object(
                self.api,
                "_get_new_login_token",
                side_effect=[None, web_token],
            ) as mock_new,
        ):
            mock_legacy.return_value = None
            result = self.api.getLoginToken("test_user", "test_pass")

            assert result == web_token
            mock_legacy.assert_called_once_with("test_user", "test_pass")
            assert mock_new.call_count == 2
            mock_new.assert_has_calls(
                [
                    call("test_user", "test_pass"),
                    call("test_user", "test_pass", is_web=True),
                ]
            )

    def test_get_login_token_exception_falls_back(self):
        """Test fallback when the preferred login raises an exception."""
        legacy_token = {
            "uid": "legacy-uid",
            "token": "legacy-token",
            "api": "https://api.test.com/",
        }

        with (
            patch.object(self.api, "_get_new_login_token") as mock_new,
            patch.object(self.api, "_get_legacy_login_token") as mock_legacy,
        ):
            mock_new.side_effect = requests.RequestException("network error")
            mock_legacy.return_value = legacy_token

            result = self.api.getLoginToken("test_user", "test_pass")

        assert result == legacy_token
        mock_new.assert_called_once_with("test_user", "test_pass")
        mock_legacy.assert_called_once_with("test_user", "test_pass")

    def test_get_login_token_prefers_web_after_web_fallback(self):
        """Test web login remains preferred after recovering authentication."""
        web_token = {
            "uid": "web-uid",
            "token": "web-token",
            "api": "https://api.test.com/",
        }
        self.api._preferred_login_mode = "web"

        with (
            patch.object(self.api, "_get_legacy_login_token") as mock_legacy,
            patch.object(
                self.api,
                "_get_new_login_token",
                return_value=web_token,
            ) as mock_new,
        ):
            result = self.api.getLoginToken("test_user", "test_pass")

            assert result == web_token
            mock_new.assert_called_once_with("test_user", "test_pass", is_web=True)
            mock_legacy.assert_not_called()

    def test_get_login_token_rate_limit_backoff(self):
        """Test rate-limit handling is propagated for coordinator retry scheduling."""
        with (
            patch.object(self.api, "_get_legacy_login_token") as mock_legacy,
            patch.object(self.api, "_get_new_login_token") as mock_new,
        ):
            mock_new.side_effect = SemsRateLimitedError(retry_after=300)

            with pytest.raises(SemsRateLimitedError):
                self.api.getLoginToken("test_user", "test_pass")

            mock_legacy.assert_not_called()

    @patch("custom_components.sems.sems_api.requests.Session.request")
    def test_make_http_request_rate_limit_raises(self, mock_request):
        """Test HTTP request raises SemsRateLimitedError on rate-limit code."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"code": "GY0429", "msg": "Too many requests"}'
        mock_response.json.return_value = {"code": "GY0429", "msg": "Too many requests"}
        mock_response.raise_for_status.return_value = None
        mock_request.return_value = mock_response

        with pytest.raises(SemsRateLimitedError):
            self.api._make_http_request(
                "http://test.com",
                {"Content-Type": "application/json"},
                operation_name="test operation",
                validate_code=False,
            )

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

    @patch.object(SemsApi, "_get_web_login_token", return_value=None)
    def test_test_authentication_success(self, mock_web_login):
        """Test successful authentication test."""
        with patch.object(self.api, "getLoginToken") as mock_login:
            mock_login.return_value = {"token": "test-token"}

            result = self.api.test_authentication()

            assert result is True
            assert self.api._token == {"token": "test-token"}
            mock_web_login.assert_called_once()

    @patch.object(SemsApi, "_get_web_login_token", return_value=None)
    def test_test_authentication_failure(self, mock_web_login):
        """Test failed authentication test."""
        with patch.object(self.api, "getLoginToken") as mock_login:
            mock_login.return_value = None

            result = self.api.test_authentication()

            assert result is False
            mock_web_login.assert_called_once()

    @patch.object(SemsApi, "_get_web_login_token", return_value=None)
    def test_test_authentication_exception(self, mock_web_login):
        """Test authentication test with exception."""
        with patch.object(self.api, "getLoginToken") as mock_login:
            mock_login.side_effect = TypeError("Test error")

            result = self.api.test_authentication()

            assert result is False
            mock_web_login.assert_called_once()

    def test_successful_login_real_structure(self, requests_mock):
        """Test successful login token retrieval with real SEMS API response structure."""
        self.api._preferred_login_mode = "legacy"
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

        requests_mock.post(OLD_LOGIN_URL, json=login_response)

        result = self.api.getLoginToken(self.username, self.password)

        assert result is not None
        assert result["uid"] == "test-uid-123"
        assert result["token"] == "test-token-abc123"
        assert result["api"] == "https://eu.semsportal.com/api/"

    def test_new_login_real_structure(self, requests_mock):
        """Test successful SEMS+ login token retrieval with real response structure."""
        legacy_response = {"code": 1001, "msg": "Invalid credentials", "data": None}
        new_login_response = {
            "code": "00000",
            "description": "成功",
            "data": {
                "uid": "new-uid-123",
                "timestamp": "1777037615323",
                "token": "new-token-abc123",
                "client": "semsPlusWeb",
                "version": "",
                "language": "en",
                "api": "https://eu-gateway.semsportal.com/web/sems",
                "region": "eu",
            },
            "api": "https://eu-gateway.semsportal.com/web/sems",
        }

        requests_mock.post(OLD_LOGIN_URL, json=legacy_response)
        requests_mock.post(NEW_LOGIN_URL, json=new_login_response)

        result = self.api.getLoginToken(self.username, self.password)

        assert result is not None
        assert result["uid"] == "new-uid-123"
        assert result["token"] == "new-token-abc123"
        assert result["api"] == "https://eu-gateway.semsportal.com/web/sems"

    def test_new_login_missing_api_uses_fallback(self, requests_mock):
        """Test SEMS+ login still succeeds when the response omits api."""
        legacy_response = {"code": 1001, "msg": "Invalid credentials", "data": None}
        new_login_response = {
            "code": "00000",
            "description": "成功",
            "data": {
                "uid": "new-uid-123",
                "timestamp": "1777037615323",
                "token": "new-token-abc123",
                "client": "semsPlusWeb",
                "version": "",
                "language": "en",
                "region": "eu",
            },
        }

        requests_mock.post(OLD_LOGIN_URL, json=legacy_response)
        requests_mock.post(NEW_LOGIN_URL, json=new_login_response)

        result = self.api.getLoginToken(self.username, self.password)

        assert result is not None
        assert result["uid"] == "new-uid-123"
        assert result["token"] == "new-token-abc123"
        assert result["api"] == "https://eu-gateway.semsportal.com/web/sems"

    def test_new_login_api_in_data_without_top_level_api(self, requests_mock):
        """Test SEMS+ login prefers api nested under data when top-level api is absent."""
        legacy_response = {"code": 1001, "msg": "Invalid credentials", "data": None}
        new_login_response = {
            "code": "00000",
            "description": "成功",
            "traceId": "ffbdeb4084a2929c15e63e2b37aac1d3",
            "data": {
                "uid": "new-uid-123",
                "timestamp": "1777042079872",
                "token": "new-token-abc123",
                "client": "",
                "version": "",
                "language": "en",
                "api": "https://eu-gateway.semsportal.com/web/sems",
                "region": "eu",
            },
        }

        requests_mock.post(OLD_LOGIN_URL, json=legacy_response)
        requests_mock.post(NEW_LOGIN_URL, json=new_login_response)

        result = self.api.getLoginToken(self.username, self.password)

        assert result is not None
        assert result["uid"] == "new-uid-123"
        assert result["token"] == "new-token-abc123"
        assert result["api"] == "https://eu-gateway.semsportal.com/web/sems"

    def test_redact_for_log_redacts_known_patterns_and_keys(self):
        """Test that shared redaction keeps labels visible, redacts string values, preserves numeric values."""
        value = {
            "sn": "GW0000SN000TEST1",
            "powerstation_id": "12345678-1234-5678-9abc-123456789abc",
            "exact_serial": "GW0000SN000TEST1",
            "inverters": {
                "GW0000SN000TEST1": {
                    "owner_email": "test@example.com",
                    "relation_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "capacity": 3.0,
                }
            },
            "message": "Device connected",
        }

        redacted = redact_for_log(value)

        assert redacted["sn"] == "<GW0...ST1>"
        assert redacted["powerstation_id"] == "<1234...9abc>"
        assert redacted["exact_serial"] == "<GW0...ST1>"
        assert "<GW0...ST1>" in redacted["inverters"]
        assert (
            redacted["inverters"][next(iter(redacted["inverters"]))]["owner_email"]
            == "<***@example.com>"
        )
        assert (
            redacted["inverters"][next(iter(redacted["inverters"]))]["relation_id"]
            == "<aaaa...eeee>"
        )
        assert (
            redacted["inverters"][next(iter(redacted["inverters"]))]["capacity"] == 3.0
        )  # Numeric values preserved
        assert redacted["message"] == "Device connected"
        assert redacted["inverters"]

    def test_redact_for_log_redacts_dataclass_objects(self):
        """Test that shared redaction handles dataclass objects."""
        from dataclasses import dataclass

        @dataclass
        class SampleEntity:
            """Sample entity with sensitive data."""

            name: str
            serial_number: str
            numeric_value: int
            nested_data: dict

        obj = SampleEntity(
            name="Test Entity",
            serial_number="GW0000SN000TEST1",
            numeric_value=42,
            nested_data={
                "sn": "GW0000SN000TEST1",
                "value_path": ["GW0000SN000TEST1", "pac"],
                "owner_email": "user@example.com",
                "capacity": 3.0,
            },
        )

        redacted = redact_for_log(obj)

        assert isinstance(redacted, dict)
        assert redacted["name"] == "Test Entity"
        assert redacted["serial_number"] == "<GW0...ST1>"
        assert redacted["numeric_value"] == 42  # Numeric values preserved
        assert redacted["nested_data"]["sn"] == "<GW0...ST1>"
        assert redacted["nested_data"]["value_path"][0] == "<GW0...ST1>"
        assert redacted["nested_data"]["owner_email"] == "<***@example.com>"
        assert redacted["nested_data"]["capacity"] == 3.0  # Numeric values preserved

    def test_failed_login_invalid_credentials(self, requests_mock):
        """Test failed login with invalid credentials."""
        legacy_response = {
            "hasError": True,
            "code": 1001,
            "msg": "Invalid credentials",
            "data": None,
        }
        new_response = {
            "code": "C0602",
            "description": "account_login_abnormal",
            "data": None,
        }

        requests_mock.post(OLD_LOGIN_URL, json=legacy_response)
        requests_mock.post(NEW_LOGIN_URL, json=new_response)

        result = self.api.getLoginToken(self.username, self.password)

        assert result is None

    def test_api_error_logs_server_description(self, requests_mock, caplog):
        """Test API errors include the server description when msg is absent."""
        requests_mock.post(
            "https://example.test/api",
            json={
                "code": "100004",
                "description": "parameter error.",
                "errorMsg": "parameter error.",
                "data": None,
            },
        )

        with caplog.at_level(logging.WARNING):
            result = self.api._make_http_request(
                "https://example.test/api",
                {},
                operation_name="SEMS+ login API call",
            )

        assert result is None
        assert "code: 100004, message: parameter error." in caplog.text

    def test_response_summary_logs_nested_api(self, requests_mock, caplog):
        """Test login response summaries include the nested gateway API."""
        requests_mock.post(
            "https://example.test/api",
            json={
                "code": "00000",
                "description": "success",
                "data": {"api": "https://eu-gateway.semsportal.com/web/sems"},
            },
        )

        with caplog.at_level(logging.DEBUG):
            self.api._make_http_request(
                "https://example.test/api",
                {},
                operation_name="SEMS+ login API call",
            )

        assert "api=https://eu-gateway.semsportal.com/web/sems" in caplog.text

    def test_permission_error_is_not_retried(self):
        """Test permission failures propagate without fetching another token."""
        self.api._web_token = {
            "uid": "uid",
            "token": "token",
            "api": "https://example.test",
            "client": "semsPlusWeb",
        }

        with (
            patch.object(
                self.api,
                "_make_http_request",
                side_effect=SemsPermissionError(
                    "getWebInverterTelemetry API call",
                    "You do not have access or operation rights",
                ),
            ) as mock_http_request,
            patch.object(self.api, "_get_web_login_token") as mock_login,
        ):
            with pytest.raises(SemsPermissionError):
                self.api._make_api_call(
                    "/telemetry",
                    operation_name="getWebInverterTelemetry API call",
                    is_web=True,
                    token_type="web",
                )

        mock_http_request.assert_called_once()
        mock_login.assert_not_called()

    def test_telecounting_token_error_is_not_error_logged(self, requests_mock, caplog):
        """Test a rejected token is raised for re-login, not logged as an error."""
        requests_mock.post(
            "https://example.test/api",
            json={
                "code": "C0602",
                "description": "account login abnormal",
                "data": None,
            },
        )

        with (
            caplog.at_level(logging.DEBUG),
            pytest.raises(SemsAuthExpiredError, match="C0602"),
        ):
            self.api._make_http_request(
                "https://example.test/api",
                {},
                operation_name="getWebInverterTelecounting API call",
            )

        assert "code C0602: account login abnormal" in caplog.text
        assert not any(record.levelno >= logging.WARNING for record in caplog.records)

    def test_login_network_error(self, requests_mock):
        """Test login with network error."""
        requests_mock.post(
            NEW_LOGIN_URL,
            exc=requests.ConnectionError("Network error"),
        )
        requests_mock.post(
            OLD_LOGIN_URL,
            exc=requests.ConnectionError("Network error"),
        )

        result = self.api.getLoginToken(self.username, self.password)

        assert result is None

    @patch.object(SemsApi, "_make_http_request")
    def test_get_new_web_login_token_success(self, mock_http_request):
        """Test successful web login token retrieval."""
        mock_response = {
            "code": 0,
            "data": {
                "uid": "test-uid",
                "token": "test-token",
                "timestamp": 1234567890,
                "client": "semsPlusWeb",
            },
            "api": "https://api.test.com/",
        }
        mock_http_request.return_value = mock_response

        result = self.api._get_new_login_token("test_user", "test_pass", is_web=True)

        expected_token = {
            "uid": "test-uid",
            "token": "test-token",
            "timestamp": 1234567890,
            "client": "semsPlusWeb",
            "api": "https://api.test.com/",
        }
        assert result == expected_token
        mock_http_request.assert_called_once()

    def test_web_login_uses_regional_browser_identity(self, requests_mock):
        """Test SEMS+ Web login matches the regional browser request."""
        requests_mock.post(
            NEW_LOGIN_URL,
            json={
                "code": "00000",
                "data": {
                    "uid": "test-uid",
                    "token": "test-token",
                    "client": "semsPlusWeb",
                    "api": "https://api.test.com/",
                },
            },
        )

        assert self.api._get_new_login_token("test_user", "test_pass", is_web=True)

        request = requests_mock.last_request
        assert request is not None
        assert request.headers["Origin"] == "https://semsplus.goodwe.com"
        assert request.headers["Referer"] == "https://semsplus.goodwe.com/"
        assert "Chrome/126.0.0.0" in request.headers["User-Agent"]
        assert request.headers["X-Signature"]

    @patch("custom_components.sems.sems_api.time.time")
    def test_generate_signature(self, mock_time):
        """Test SEMS+ web signature encoding."""
        mock_time.return_value = 1234567890
        token = {
            "uid": "test-uid",
            "token": "test-token",
            "timestamp": 1234567890,
            "client": "semsPlusWeb",
            "api": "https://api.test.com/",
        }

        assert self.api._generate_signature(token) == (
            "MjJiNzc3MmY3Y2QzMDlhYTZkNDFkMmMzOWY3ODFiMWMyZjQ4OTQ5YWU2YjZiMTIzMjI1YzJhNGI4MDU3MDk5ZkAxMjM0NTY3ODkwMDAw"
        )

    @patch.object(SemsApi, "_get_new_login_token")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_web_api_call_success(self, mock_http_request, mock_login):
        """Test successful API call."""
        # Set up token
        mock_token = {
            "uid": "test-uid",
            "token": "test-token",
            "timestamp": 1234567890,
            "client": "semsPlusWeb",
            "api": "https://api.test.com/",
        }
        mock_login.return_value = mock_token

        mock_response = {"code": 0, "data": {"result": "success"}}
        mock_http_request.return_value = mock_response

        result = self.api._make_api_call(
            "/test/endpoint",
            data='{"test": "data"}',
            operation_name="test web API call",
            is_web=True,
        )

        assert result == {"result": "success"}
        assert self.api._web_token == mock_token
        mock_login.assert_called_once_with("test_user", "test_password", is_web=True)
        mock_http_request.assert_called_once()

    @patch.object(SemsApi, "_get_new_login_token")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_new_token_web_api_call_success(self, mock_http_request, mock_login):
        """Test a SEMS+ endpoint can use the non-Web login token."""
        mock_token = {
            "uid": "test-uid",
            "token": "test-token",
            "timestamp": 1234567890,
            "client": "semsPlus",
            "api": "https://api.test.com/",
        }
        mock_login.return_value = mock_token
        mock_http_request.return_value = {"code": 0, "data": {"result": "success"}}

        result = self.api._make_api_call(
            "/test/endpoint",
            operation_name="test new-token Web API call",
            is_web=True,
            token_type="new",
        )

        assert result == {"result": "success"}
        assert self.api._new_token == mock_token
        mock_login.assert_called_once_with("test_user", "test_password")
        mock_http_request.assert_called_once()

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

    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_rewrites_gateway_base_for_powerstation_control_paths(
        self, mock_http_request
    ):
        """Test gateway base is rewritten for legacy PowerStation control routes."""
        self.api._token = {
            "token": "test-token",
            "api": "https://eu-gateway.semsportal.com/web/sems",
            "region": "eu",
        }
        mock_http_request.return_value = {"code": 0, "data": {"result": "success"}}

        result = self.api._make_api_call(
            "/PowerStation/SaveRemoteControlInverter",
            data='{"powerStationId":"station123"}',
            operation_name="control API call",
        )

        assert result == {"result": "success"}
        called_url = mock_http_request.call_args[0][0]
        assert (
            called_url
            == "https://eu.semsportal.com/api/PowerStation/SaveRemoteControlInverter"
        )

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_token_renewal(self, mock_http_request, mock_login):
        """Test API call with token renewal."""
        # No initial token
        self.api._token = None
        self.api._web_token = {"token": "stale-web-token"}

        mock_login.return_value = {"token": "new-token", "api": "https://api.test.com"}

        mock_response = {"code": 0, "data": {"result": "success"}}
        mock_http_request.return_value = mock_response

        result = self.api._make_api_call(
            "/test/endpoint", operation_name="test API call"
        )

        assert result == {"result": "success"}
        mock_login.assert_called_once_with(self.username, self.password)
        assert self.api._web_token is None

    @patch.object(SemsApi, "getLoginToken")
    def test_make_api_call_login_failure(self, mock_login):
        """Test a failed login pauses the client instead of retrying."""
        self.api._token = None
        mock_login.return_value = None

        with pytest.raises(SemsRateLimitedError):
            self.api._make_api_call("/test/endpoint", operation_name="test API call")
        with pytest.raises(SemsRateLimitedError):
            self.api._make_api_call("/test/endpoint", operation_name="test API call")

        mock_login.assert_called_once()

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_retry_on_failure(self, mock_http_request, mock_login):
        """Test API call retry on validation failure."""
        # Set up token
        self.api._token = {"token": "test-token", "api": "https://api.test.com"}

        # First call is rejected for its token, second succeeds
        mock_http_request.side_effect = [
            SemsAuthExpiredError("test API call rejected the token"),
            {"code": 0, "data": {"result": "success"}},
        ]

        mock_login.return_value = {"token": "new-token", "api": "https://api.test.com"}

        result = self.api._make_api_call(
            "/test/endpoint", operation_name="test API call", maxTokenRetries=2
        )

        assert result == {"result": "success"}
        assert mock_http_request.call_count == 2
        mock_login.assert_called_once()

    @patch.object(SemsApi, "getLoginToken")
    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_api_error_does_not_log_in(
        self, mock_http_request, mock_login
    ):
        """Test other API errors fail without fetching a new token."""
        self.api._token = {"token": "test-token", "api": "https://api.test.com"}
        mock_http_request.return_value = None

        with pytest.raises(OutOfRetries):
            self.api._make_api_call("/test/endpoint", operation_name="test API call")

        mock_http_request.assert_called_once()
        mock_login.assert_not_called()

    @patch("custom_components.sems.sems_api.requests.Session.request")
    def test_immediate_charging_states_read_fail_does_not_retry(self, mock_request):
        """Reproduce read_fail responses from the immediate charging endpoint."""
        self.api._web_token = {
            "uid": "test-uid",
            "token": "test-token",
            "client": "semsPlusWeb",
            "api": "https://eu-gateway.semsportal.com/web/sems",
        }

        read_fail_response = Mock()
        read_fail_response.status_code = 200
        read_fail_response.json.return_value = {
            "code": "read_fail",
            "description": "读取失败",
            "data": None,
        }
        read_fail_response.raise_for_status.return_value = None

        mock_request.side_effect = [read_fail_response]

        result = self.api.getBatteryImmediateChargingStates(MOCK_INVERTER_SN)

        assert mock_request.call_count == 1
        # No state, rather than an empty state that reads as "disabled".
        assert result is None
        assert (
            mock_request.call_args_list[0]
            .args[1]
            .endswith(
                "/sems-remote/api/v1/address/remote/get-cache-device-function-parameters"
            )
        )

    @patch.object(SemsApi, "_make_http_request")
    def test_make_api_call_rate_limit_propagates(self, mock_http_request):
        """Test API call propagates rate limit errors to coordinator layer."""
        self.api._token = {"token": "test-token", "api": "https://api.test.com"}
        mock_http_request.side_effect = SemsRateLimitedError(retry_after=300)

        with pytest.raises(SemsRateLimitedError):
            self.api._make_api_call("/test/endpoint", operation_name="test API call")

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

        assert result == []
        mock_api_call.assert_called_once_with(
            "/sems-plant/api/portal/stations/page",
            data='{"current": 1, "size": 100}',
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getPowerStationIds API call",
            is_web=True,
            token_type="web",
        )

    @patch.object(SemsApi, "_make_api_call")
    def test_get_web_inverter_devices(self, mock_api_call):
        """Test SEMS+ inverter discovery normalization."""
        mock_api_call.return_value = {
            "deviceDetailList": [
                {
                    "deviceType": "INVERTER",
                    "statusDetailList": [
                        {
                            "status": 1,
                            "snList": ["SN1"],
                            "detailMap": {
                                "SN1": {
                                    "sn": "SN1",
                                    "name": "Inverter",
                                    "subtype": "grid",
                                }
                            },
                        }
                    ],
                },
                {
                    "deviceType": "ENERGY_STORAGE_INTEGRATED_CABINET",
                    "statusDetailList": [
                        {
                            "status": 5,
                            "snList": ["CABINET1"],
                            "detailMap": {
                                "CABINET1": {
                                    "sn": "CABINET1",
                                    "name": "All-in-One",
                                    "subtype": "storage",
                                }
                            },
                        }
                    ],
                },
            ]
        }

        assert self.api.getWebInverterDevices("station") == [
            {
                "sn": "SN1",
                "name": "Inverter",
                "subtype": "grid",
                "deviceType": "INVERTER",
                "status": 1,
            },
            {
                "sn": "CABINET1",
                "name": "All-in-One",
                "subtype": "storage",
                "deviceType": "ENERGY_STORAGE_INTEGRATED_CABINET",
                "status": 5,
            },
        ]
        mock_api_call.assert_called_once_with(
            "/sems-plant/api/stations/device/all-status?stationId=station",
            method="GET",
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getWebInverterDevices API call",
            is_web=True,
            token_type="web",
        )

    def test_get_web_data_reuses_cached_device_inventory_after_request_failure(self):
        """Reuse recent discovery metadata, but never its stale device status."""
        with (API_EXAMPLES_DIR / "all_status.json").open(encoding="utf-8") as file:
            captured_devices = json.load(file)["data"]

        with (
            patch.object(
                self.api, "_make_api_call", side_effect=[captured_devices, None]
            ),
            patch.object(
                self.api, "getWebInverterTelemetry", return_value={"pac": 1200}
            ),
            patch.object(
                self.api, "getWebInverterTelecounting", return_value={"etotal": 42}
            ),
            patch.object(self.api, "getWebStationFlow", return_value={}),
            patch.object(self.api, "_get_web_energy_statistics", return_value=None),
        ):
            first = self.api.getWebData("station")
            recovered = self.api.getWebData("station")

        first_inverter = first["inverter"][0]["invert_full"]
        recovered_inverter = recovered["inverter"][0]["invert_full"]
        assert recovered_inverter["sn"] == first_inverter["sn"]
        assert recovered_inverter["pac"] == 1200
        assert "status" not in recovered_inverter
        assert recovered["unavailable_data_sources"]["inverters"][
            recovered_inverter["sn"]
        ] == {"device_status"}

    def test_get_web_data_does_not_reuse_inventory_after_successful_empty_response(
        self,
    ):
        """A successful empty device list replaces the cached inventory."""
        with (API_EXAMPLES_DIR / "all_status.json").open(encoding="utf-8") as file:
            captured_devices = json.load(file)["data"]

        with (
            patch.object(
                self.api,
                "_make_api_call",
                side_effect=[
                    captured_devices,
                    {"deviceDetailList": []},
                    None,
                ],
            ),
            patch.object(self.api, "getWebInverterTelemetry", return_value={}),
            patch.object(self.api, "getWebInverterTelecounting", return_value={}),
            patch.object(self.api, "getWebStationFlow", return_value={}),
            patch.object(self.api, "_get_web_energy_statistics", return_value=None),
        ):
            self.api.getWebData("station")
            result = self.api.getWebData("station")
            with pytest.raises(OutOfRetries):
                self.api.getWebData("station")

        assert result["inverter"] == []
        assert "unavailable_data_sources" not in result

    def test_get_web_data_does_not_use_expired_device_inventory(self):
        """Expired discovery metadata cannot hide an unavailable API."""
        self.api._web_cache["devices:station"] = (
            10.0,
            [{"sn": "SN1", "deviceType": "INVERTER", "status": 1}],
        )

        with (
            patch.object(self.api, "getWebInverterDevices", side_effect=OutOfRetries),
            patch("custom_components.sems.sems_api.time.monotonic", return_value=3610),
            pytest.raises(OutOfRetries),
        ):
            self.api.getWebData("station")

    @patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
    @patch.object(SemsApi, "getWebStationFlow", return_value={})
    @patch.object(SemsApi, "getWebInverterTelecounting", return_value={})
    @patch.object(SemsApi, "getWebInverterTelemetry", return_value={})
    @patch.object(SemsApi, "getWebInverterDevices")
    def test_get_web_data_uses_name_as_model(
        self,
        mock_devices,
        mock_telemetry,
        mock_telecounting,
        mock_flow,
        mock_statistics,
    ):
        """Test SEMS+ fallback combines the device name and subtype as model."""
        mock_devices.return_value = [
            {
                "sn": "SN1",
                "name": "Zolder",
                "subtype": "grid",
                "deviceType": "INVERTER",
            }
        ]

        assert self.api.getWebData("station") == {
            "inverter": [
                {
                    "invert_full": {
                        "sn": "SN1",
                        "name": "Zolder",
                        "subtype": "grid",
                        "deviceType": "INVERTER",
                        "powerstation_id": "station",
                        "model_type": "Zolder (grid)",
                    }
                }
            ]
        }
        mock_telemetry.assert_called_once_with(
            "station", "SN1", False, 2, device_type="INVERTER"
        )
        mock_telecounting.assert_called_once_with(
            "station", "SN1", False, 2, device_type="INVERTER"
        )

    def test_normalize_web_homekit_data_maps_station_flow_and_meter(self):
        """Test SEMS+ station flow and smart-meter values use HomeKit fields."""
        result = SemsApi._normalize_web_homekit_data(
            {"pAc": 0, "pGrid": -1.351, "pConsum": 1.351},
            {
                "sn": "METER1",
                "meter_power": 1351,
                "meter_phase_a_power": -0.451,
                "proPurchaseStatsToday": 1.2,
                "proGridStatsToday": 0.3,
                "proPurchaseStatsTotal": 12.4,
                "proGridStatsTotal": 3.5,
            },
        )

        assert result == {
            "sn": "METER1",
            "gridStatus": 1,
            "loadStatus": 1,
            "isSemsPlusFlow": True,
            "pv": 0,
            "grid": -1351,
            "load": 1351,
            "meter_power": 1351,
            "meter_phase_a_power": -0.451,
            "Charts_buy": 1.2,
            "Charts_sell": 0.3,
            "Totals_buy": 12.4,
            "Totals_sell": 3.5,
            "hasEnergeStatisticsCharts": True,
        }

    def test_normalize_web_homekit_data_load_is_never_negative(self):
        """Test a negative pConsum while exporting maps to positive consumption."""
        result = SemsApi._normalize_web_homekit_data(
            {"pSystem": 3.03, "pGrid": 2.53, "pConsum": -0.5}
        )

        assert result["load"] == 500
        assert result["grid"] == 2530
        assert result["gridStatus"] == -1

    def test_normalize_web_homekit_data_skips_null_and_invalid_values(self):
        """Test null or non-numeric flow values are skipped, not raised."""
        result = SemsApi._normalize_web_homekit_data(
            {"pAc": "n/a", "pGrid": None, "pConsum": 1.2, "pBat": "-"}
        )

        assert result["gridStatus"] == 1
        assert result["loadStatus"] == 1
        assert result["load"] == 1200
        assert "pv" not in result
        assert "grid" not in result
        assert "battery" not in result

    def test_prune_web_cache_drops_stale_entries(self):
        """Stale date-keyed entries are evicted; counters and fresh ones stay."""
        day = 86_400
        self.api._web_cache = {
            "station:day:2026-01-01:2026-01-01": (0.0, {"sum": [1.0]}),
            "failed:production:station:2026-01-01:2026-01-01": (0.0, None),
            "counters:station:SN1:INVERTER": (0.0, {"etotal": 10.0}),
            "station:day:2026-01-03:2026-01-03": (2 * day, {"sum": [2.0]}),
        }
        self.api._web_cache_pruned_at = 0.0

        with patch(
            "custom_components.sems.sems_api.time.monotonic",
            return_value=2 * day + 1,
        ):
            self.api._prune_web_cache()

        assert set(self.api._web_cache) == {
            "counters:station:SN1:INVERTER",
            "station:day:2026-01-03:2026-01-03",
        }

    def test_prune_web_cache_runs_at_most_hourly(self):
        """Pruning is skipped until the prune interval has passed."""
        self.api._web_cache = {"old": (0.0, None)}
        self.api._web_cache_pruned_at = 10 * 86_400

        with patch(
            "custom_components.sems.sems_api.time.monotonic",
            return_value=10 * 86_400 + 60,
        ):
            self.api._prune_web_cache()

        assert "old" in self.api._web_cache

    def test_prune_web_cache_synchronizes_concurrent_writes(self):
        """A cache writer cannot mutate the dict while pruning iterates it."""
        iteration_started = Event()
        continue_iteration = Event()

        class PausingDict(dict):
            def items(self):
                entries = iter(super().items())
                yield next(entries)
                iteration_started.set()
                assert continue_iteration.wait(timeout=5)
                yield from entries

        self.api._web_cache = PausingDict({"old-1": (0.0, None), "old-2": (0.0, None)})
        self.api._web_cache_pruned_at = 0.0

        with (
            patch(
                "custom_components.sems.sems_api.time.monotonic",
                return_value=3 * 86_400,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            prune = executor.submit(self.api._prune_web_cache)
            assert iteration_started.wait(timeout=5)
            write = executor.submit(
                self.api._set_web_cache_entry, "fresh", (3 * 86_400, None)
            )
            assert not write.done()
            continue_iteration.set()
            prune.result(timeout=5)
            write.result(timeout=5)

        assert self.api._web_cache == {"fresh": (3 * 86_400, None)}

    def test_get_web_data_prunes_web_cache(self):
        """Every data refresh gives the cache a chance to shrink."""
        with (
            patch.object(
                SemsApi, "_prune_web_cache", side_effect=RuntimeError("pruned")
            ),
            pytest.raises(RuntimeError, match="pruned"),
        ):
            self.api.getWebData("station")

    def test_normalize_web_homekit_data_maps_station_flow_without_meter(self):
        """Test station flow remains usable when no smart meter is discovered."""
        result = SemsApi._normalize_web_homekit_data(
            {
                "pSystem": 2.4,
                "pAc": 2.4,
                "pBat": -1.1,
                "pGrid": -0.5,
                "pConsum": 1.8,
                "soc": 62,
            }
        )

        assert result == {
            "sn": None,
            "gridStatus": 1,
            "loadStatus": 1,
            "isSemsPlusFlow": True,
            "pv": 2400,
            "grid": -500,
            "load": 1800,
            "battery": 1100,
            "batteryStatus": 1,
            "bettery": 1100,
            "betteryStatus": 1,
            "soc": 62,
            "hasEnergeStatisticsCharts": False,
        }

    @patch.object(
        SemsApi,
        "getWebInverterTelecounting",
        return_value={
            "capacity": 3.0,
            "eday": 8.8,
            "eweek": 23.4,
            "thismonthetotle": 185.6,
            "eyear": 2613.6,
            "etotal": 21841.1,
        },
    )
    @patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
    @patch.object(SemsApi, "getWebStationFlow", return_value={})
    @patch.object(SemsApi, "getWebInverterTelemetry", return_value={})
    @patch.object(SemsApi, "getWebInverterDevices")
    def test_get_web_data_preserves_counters_without_live_telemetry(
        self,
        mock_devices,
        mock_telemetry,
        mock_flow,
        mock_statistics,
        mock_telecounting,
    ):
        """Test a waiting inverter response with counters but no live telemetry."""
        mock_devices.return_value = [
            {
                "sn": "SN1",
                "name": "Zolder",
                "subtype": "grid",
                "deviceType": "INVERTER",
                "status": 0,
            }
        ]

        inverter = self.api.getWebData("station")["inverter"][0]["invert_full"]

        assert inverter == {
            "sn": "SN1",
            "name": "Zolder",
            "subtype": "grid",
            "deviceType": "INVERTER",
            "status": 0,
            "powerstation_id": "station",
            "model_type": "Zolder (grid)",
            "pac": 0,
            "capacity": 3.0,
            "eday": 8.8,
            "eweek": 23.4,
            "thismonthetotle": 185.6,
            "eyear": 2613.6,
            "etotal": 21841.1,
        }
        assert "tempperature" not in inverter
        mock_telemetry.assert_called_once_with(
            "station", "SN1", False, 2, device_type="INVERTER"
        )
        mock_telecounting.assert_called_once_with(
            "station", "SN1", False, 2, device_type="INVERTER"
        )

    @patch.object(SemsApi, "_make_api_call")
    def test_get_web_inverter_telemetry(self, mock_api_call):
        """Test SEMS+ telemetry normalization and unit conversion."""
        mock_api_call.return_value = [
            {
                "code": "system",
                "factors": [
                    {"code": "sn", "data": "SN1"},
                    {"code": "hTotal", "data": "10"},
                    {"code": "Temperature", "data": "25.5"},
                ],
            },
            {
                "code": "ac",
                "factors": [
                    {"code": "pAc", "data": "1.064"},
                    {"code": "gridPF", "data": "-0.001"},
                    {"code": "PHASE-A:Vac", "data": "233.3"},
                    {"code": "PHASE-B:Vac", "data": "234.1"},
                    {"code": "PHASE-C:Vac", "data": "235.2"},
                    {"code": "Iac", "data": "4.3"},
                    {"code": "Fac", "data": "49.95"},
                ],
            },
            {
                "code": "pv",
                "factors": [
                    {"code": "MPPT-1:Vpv", "data": "319.8"},
                    {"code": "MPPT-1:Ipv", "data": "3.1"},
                    {"code": "MPPT-1:Ppv", "data": "0.99138"},
                ],
            },
        ]

        assert self.api.getWebInverterTelemetry("station", "SN1") == {
            "sn": "SN1",
            "hour_total": 10.0,
            "tempperature": 25.5,
            "vac1": 233.3,
            "vac2": 234.1,
            "vac3": 235.2,
            "iac1": 4.3,
            "fac1": 49.95,
            "power_factor": -0.001,
            "pac": 1064.0,
            "vpv1": 319.8,
            "ipv1": 3.1,
            "ppv1": 991.38,
        }

    @pytest.mark.parametrize(
        "method_name",
        ("getWebInverterTelemetry", "getWebInverterTelecounting"),
    )
    @patch.object(SemsApi, "_make_api_call", return_value=None)
    def test_web_measurement_request_failure_raises(self, mock_api_call, method_name):
        """Do not normalize a failed request as a successful empty response."""
        with pytest.raises(OutOfRetries):
            getattr(self.api, method_name)("station", "SN1")

    @pytest.mark.parametrize(
        "method_name",
        ("getWebInverterTelemetry", "getWebInverterTelecounting"),
    )
    @patch("custom_components.sems.sems_api.dt_util.now")
    @patch.object(SemsApi, "_make_api_call", return_value=[])
    def test_empty_web_measurement_response_is_successful(
        self, mock_api_call, mock_now, method_name
    ):
        """Keep a valid empty response distinct from a failed request."""
        mock_now.return_value = datetime(2026, 1, 15, 12)

        assert getattr(self.api, method_name)("station", "SN1") == {}

    @patch.object(SemsApi, "_make_api_call", return_value=[])
    def test_get_web_data_uses_discovered_device_type(self, mock_api_call):
        """Test cabinet telemetry and telecounting use the discovered type."""
        self.api.getWebInverterTelemetry(
            "station",
            "CABINET1",
            device_type="ENERGY_STORAGE_INTEGRATED_CABINET",
        )
        self.api.getWebInverterTelecounting(
            "station",
            "CABINET1",
            device_type="ENERGY_STORAGE_INTEGRATED_CABINET",
        )

        assert (
            mock_api_call.call_args_list[0]
            .args[0]
            .endswith(
                "telemetry?deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId=station"
            )
        )
        assert (
            mock_api_call.call_args_list[1]
            .args[0]
            .endswith(
                "telecounting?deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId=station"
            )
        )

    @patch.object(SemsApi, "_make_api_call")
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_get_web_inverter_telecounting(self, mock_now, mock_api_call):
        """Test SEMS+ energy counter normalization."""
        mock_now.return_value = datetime(2026, 1, 15, 12)
        mock_api_call.return_value = [
            {
                "code": "telecounting_today",
                "factors": [{"code": "proPvStatsToday", "data": "12.34"}],
            },
            {
                "code": "telecounting_month",
                "factors": [{"code": "proPvStatsMonth", "data": "123.45"}],
            },
            {
                "code": "telecounting_week",
                "factors": [{"code": "proPvStatsWeek", "data": "56.78"}],
            },
            {
                "code": "telecounting_year",
                "factors": [{"code": "proPvStatsYear", "data": "2345.67"}],
            },
            {
                "code": "telecounting_lifetime",
                "factors": [
                    {"code": "proPvStatsTotal", "data": "12345.67"},
                    {"code": "ratedPower", "data": "5"},
                ],
            },
        ]

        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "capacity": 5.0,
            "eday": 12.34,
            "eweek": 56.78,
            "thismonthetotle": 123.45,
            "eyear": 2345.67,
            "etotal": 12345.67,
        }

    @patch("custom_components.sems.sems_api.dt_util.now")
    @patch.object(SemsApi, "_make_api_call")
    def test_get_web_inverter_telecounting_holds_counters_at_midnight(
        self: "TestSemsApi", mock_api_call: Mock, mock_now: Mock
    ) -> None:
        """Test previous-day readings after midnight do not stick (#94)."""

        def poll(now: datetime, today: float, week: float, total: float) -> dict:
            mock_now.return_value = now
            mock_api_call.return_value = [
                {
                    "code": "telecounting",
                    "factors": [
                        {"code": "proPvStatsToday", "data": str(today)},
                        {"code": "proPvStatsWeek", "data": str(week)},
                        {"code": "proPvStatsTotal", "data": str(total)},
                    ],
                }
            ]
            return self.api.getWebInverterTelecounting("station", "SN1")

        poll(datetime(2026, 9, 26, 23, 50), 11.0, 62.7, 1517.2)
        poll(datetime(2026, 9, 26, 23, 55), 11.0, 62.7, 1517.2)
        # From 23:58 until the portal has settled, nothing new is published:
        # an early reset, then the previous day's production replayed for
        # several polls.
        replay = [(datetime(2026, 9, 26, 23, 58), 0, 62.7, 1517.2)]
        replay += [
            (datetime(2026, 9, 27, 0, minute), 11.0, 73.7, 1528.2)
            for minute in range(1, 8)
        ]
        replay += [(datetime(2026, 9, 27, 0, 15), 0, 62.7, 1517.2)]
        for now, today, week, total in replay:
            held = poll(now, today, week, total)
            assert (held["eday"], held["eweek"], held["etotal"]) == (
                11.0,
                62.7,
                1517.2,
            )

        settled = poll(datetime(2026, 9, 27, 0, 20), 0, 62.7, 1517.2)
        assert (settled["eday"], settled["eweek"], settled["etotal"]) == (
            0,
            62.7,
            1517.2,
        )
        poll(datetime(2026, 9, 27, 8, 0), 0.1, 62.8, 1517.3)
        morning = poll(datetime(2026, 9, 27, 8, 1), 0.2, 62.9, 1517.4)
        assert (morning["eday"], morning["eweek"], morning["etotal"]) == (
            0.2,
            62.9,
            1517.4,
        )

    @patch("custom_components.sems.sems_api.dt_util.now")
    @patch.object(SemsApi, "_make_api_call")
    def test_get_web_inverter_telecounting_does_not_cache_midnight_cold_start(
        self: "TestSemsApi", mock_api_call: Mock, mock_now: Mock
    ) -> None:
        """Test stale rollover readings on startup are not cached as current."""
        mock_api_call.return_value = [
            {
                "code": "telecounting",
                "factors": [
                    {"code": "proPvStatsToday", "data": "11.0"},
                    {"code": "proPvStatsWeek", "data": "73.7"},
                    {"code": "proPvStatsTotal", "data": "1528.2"},
                ],
            }
        ]
        mock_now.return_value = datetime(2026, 9, 27, 0, 1)
        assert self.api.getWebInverterTelecounting("station", "SN1") == {}

        mock_now.return_value = datetime(2026, 9, 27, 0, 14)
        assert self.api.getWebInverterTelecounting("station", "SN1") == {}

        mock_now.return_value = datetime(2026, 9, 27, 0, 15)
        assert self.api.getWebInverterTelecounting("station", "SN1") == {}

        mock_api_call.return_value = [
            {
                "code": "telecounting",
                "factors": [
                    {"code": "proPvStatsToday", "data": "0"},
                    {"code": "proPvStatsWeek", "data": "62.7"},
                    {"code": "proPvStatsTotal", "data": "1517.2"},
                ],
            }
        ]
        mock_now.return_value = datetime(2026, 9, 27, 0, 20)
        counters = self.api.getWebInverterTelecounting("station", "SN1")
        assert (counters["eday"], counters["eweek"], counters["etotal"]) == (
            0,
            62.7,
            1517.2,
        )

    @patch.object(SemsApi, "_make_api_call")
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_get_web_inverter_telecounting_ignores_invalid_lifetime_reset(
        self, mock_now, mock_api_call
    ):
        """Test a transient zero lifetime counter is not published."""
        mock_now.return_value = datetime(2026, 1, 15, 12)
        response = [
            {
                "code": "telecounting_lifetime",
                "factors": [{"code": "proPvStatsTotal", "data": "12345.67"}],
            }
        ]
        mock_api_call.return_value = response
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "etotal": 12345.67
        }

        mock_api_call.return_value = [
            {
                "code": "telecounting_lifetime",
                "factors": [{"code": "proPvStatsTotal", "data": "0"}],
            }
        ]
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "etotal": 12345.67
        }

        mock_api_call.return_value = [
            {
                "code": "telecounting_lifetime",
                "factors": [{"code": "proPvStatsTotal", "data": "12345"}],
            }
        ]
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "etotal": 12345.67
        }

        mock_api_call.return_value = [
            {
                "code": "telecounting_lifetime",
                "factors": [{"code": "proPvStatsTotal", "data": "12346.1"}],
            }
        ]
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "etotal": 12346.1
        }

    @patch.object(SemsApi, "_make_api_call")
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_get_web_inverter_telecounting_ignores_battery_lifetime_reset(
        self, mock_now, mock_api_call
    ):
        """Test transient zero battery lifetime counters are not published (#249)."""
        mock_now.return_value = datetime(2026, 9, 29, 16, 51)

        def poll(charge: str, discharge: str) -> dict:
            mock_api_call.return_value = [
                {
                    "code": "telecounting_lifetime",
                    "factors": [
                        {"code": "proCharStatsTotal", "data": charge},
                        {"code": "proDischarStatsTotal", "data": discharge},
                    ],
                }
            ]
            return self.api.getWebInverterTelecounting("station", "SN1")

        expected = {"echarge_total": 7720.0, "edischarge_total": 7436.0}
        assert poll("7720", "7436") == expected
        assert poll("0", "0") == expected
        assert poll("7719", "7435") == expected
        assert poll("7721", "7437") == {
            "echarge_total": 7721.0,
            "edischarge_total": 7437.0,
        }

    @patch.object(SemsApi, "_make_api_call")
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_get_web_inverter_telecounting_skips_zero_lifetime_without_history(
        self, mock_now, mock_api_call
    ):
        """Test a zero PV lifetime counter on the first poll is not published (#249)."""
        mock_now.return_value = datetime(2026, 9, 29, 16, 51)
        mock_api_call.return_value = [
            {
                "code": "telecounting",
                "factors": [
                    {"code": "proPvStatsToday", "data": "0"},
                    {"code": "proPvStatsTotal", "data": "0"},
                ],
            }
        ]
        assert self.api.getWebInverterTelecounting("station", "SN1") == {"eday": 0.0}

        mock_api_call.return_value = [
            {
                "code": "telecounting",
                "factors": [
                    {"code": "proPvStatsToday", "data": "12.5"},
                    {"code": "proPvStatsTotal", "data": "7610"},
                ],
            }
        ]
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "eday": 12.5,
            "etotal": 7610.0,
        }

    @patch("custom_components.sems.sems_api.dt_util.now")
    @patch.object(SemsApi, "_make_api_call")
    def test_get_web_inverter_telecounting_preserves_period_counters(
        self, mock_api_call, mock_now
    ):
        """Test period counters only reset when their period changes."""
        mock_now.return_value = datetime(2026, 1, 15, 12)
        response = [
            {
                "code": "telecounting",
                "factors": [
                    {"code": "proPvStatsToday", "data": "10"},
                    {"code": "proPvStatsWeek", "data": "20"},
                    {"code": "proPvStatsMonth", "data": "30"},
                    {"code": "proPvStatsYear", "data": "40"},
                ],
            }
        ]
        mock_api_call.return_value = response
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "eday": 10.0,
            "eweek": 20.0,
            "thismonthetotle": 30.0,
            "eyear": 40.0,
        }

        mock_api_call.return_value = [
            {
                "code": "telecounting",
                "factors": [
                    {"code": "proPvStatsToday", "data": "0"},
                    {"code": "proPvStatsWeek", "data": "0"},
                    {"code": "proPvStatsMonth", "data": "0"},
                    {"code": "proPvStatsYear", "data": "0"},
                ],
            }
        ]
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "eday": 10.0,
            "eweek": 20.0,
            "thismonthetotle": 30.0,
            "eyear": 40.0,
        }

        mock_now.return_value = datetime(2026, 2, 1, 12)
        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "eday": 0.0,
            "eweek": 0.0,
            "thismonthetotle": 0.0,
            "eyear": 40.0,
        }

    @patch.object(SemsApi, "_make_api_call")
    @patch("custom_components.sems.sems_api.dt_util.now")
    def test_get_web_inverter_telecounting_maps_battery_counters(
        self, mock_now, mock_api_call
    ):
        """Test SEMS+ battery charge and discharge counter normalization."""
        mock_now.return_value = datetime(2026, 1, 15, 12)
        mock_api_call.return_value = [
            {
                "code": "telecounting_today",
                "factors": [
                    {"code": "proCharStatsToday", "data": "12.1"},
                    {"code": "proDischarStatsToday", "data": "5.4"},
                ],
            },
            {
                "code": "telecounting_lifetime",
                "factors": [
                    {"code": "proCharStatsTotal", "data": "120.1"},
                    {"code": "proDischarStatsTotal", "data": "55.4"},
                ],
            },
        ]

        assert self.api.getWebInverterTelecounting("station", "SN1") == {
            "eChargeDay": 12.1,
            "eDischargeDay": 5.4,
            "echarge_total": 120.1,
            "edischarge_total": 55.4,
        }

    @patch.object(SemsApi, "_make_api_call")
    def test_get_battery_system_telemetry(self, mock_api_call):
        """Test BAT_SYS telemetry normalization."""
        mock_api_call.return_value = [
            {
                "code": "battery",
                "factors": [
                    {"code": "soc", "data": "85"},
                    {"code": "pBat", "data": "1.2"},
                    {"code": "voltage", "data": "400"},
                    {"code": "a", "data": "3"},
                    {"code": "batSysTemp", "data": "24"},
                ],
            }
        ]

        assert self.api.getBatterySystemTelemetry("station", "BAT1") == {
            "soc": 85.0,
            "power": 1.2,
            "voltage": 400.0,
            "current": 3.0,
            "temperature": 24.0,
        }
        mock_api_call.assert_called_once_with(
            "/sems-plant/api/equipments/BAT1/telemetry?deviceType=BAT_SYS&pwId=station",
            method="GET",
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getBatterySystemTelemetry API call",
            is_web=True,
            token_type="web",
        )

    @patch.object(SemsApi, "getBatterySystemTelemetry")
    def test_get_web_batteries_maps_existing_entity_shape(self, mock_telemetry):
        """Test related BAT_SYS values map to the existing battery sensors."""
        mock_telemetry.return_value = {
            "soc": 85,
            "soh": 98,
            "power": -1.2,
            "voltage": 400,
            "current": -3,
            "temperature": 24,
        }

        assert self.api._get_web_batteries(
            "station",
            [{"sn": "BAT1", "deviceType": "BAT_SYS"}],
        ) == [
            {
                "sn": "BAT1",
                "soc": 85,
                "soh": 98,
                "pbattery": -1200,
                "vbattery": 400,
                "ibattery": -3,
                "bms_temperature": 24,
            }
        ]
        mock_telemetry.assert_called_once_with("station", "BAT1")

    @patch.object(SemsApi, "_make_api_call")
    def test_get_battery_system_devices(self, mock_api_call):
        """Test optional BAT_SYS discovery."""
        mock_api_call.return_value = [{"sn": "BAT1", "type": "BAT_SYS"}]

        assert self.api.getBatterySystemDevices("station", "INV1") == [
            {"sn": "BAT1", "type": "BAT_SYS"}
        ]
        mock_api_call.assert_called_once_with(
            "/sems-plant/api/equipments/INV1/relatedDevices"
            "?sn=INV1&deviceType=BAT_SYS&pwId=station",
            method="GET",
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getBatterySystemDevices API call",
            is_web=True,
        )

    @patch.object(SemsApi, "_make_api_call")
    def test_get_power_station_ids_uses_web_station_list(self, mock_api_call):
        """Test station discovery uses the SEMS+ Web station list."""
        mock_api_call.return_value = {
            "dataList": [{"id": "station-1"}, {"id": "station-2"}]
        }

        assert self.api.getPowerStationIds() == ["station-1", "station-2"]
        mock_api_call.assert_called_once_with(
            "/sems-plant/api/portal/stations/page",
            data='{"current": 1, "size": 100}',
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getPowerStationIds API call",
            is_web=True,
            token_type="web",
        )

    @patch.object(SemsApi, "getWebData")
    def test_get_data_uses_web_api(self, mock_web_data):
        """Test getData uses the SEMS+ Web API."""
        mock_web_data.return_value = {"inverter": [{"invert_full": {"sn": "SN1"}}]}

        result = self.api.getData("station123", renewToken=True, maxTokenRetries=1)

        assert result == mock_web_data.return_value
        mock_web_data.assert_called_once_with(
            "station123", True, 1, include_last_month=False
        )

    @patch.object(SemsApi, "_make_api_call")
    def test_get_energy_storage_integrated_cabinets(self, mock_api_call):
        """Test getEnergyStorageIntegratedCabinets method."""
        expected_data = [
            {
                "sn": "VD506170156742NAH34BL7824",
                "no": "1",
                "name": "BAT1",
                "translateCode": "mppt1_battery",
                "type": "BAT_SYS",
                "status": 6,
                "soc": 55.0,
                "isConnected": True,
                "pbat": -11.54568,
            }
        ]

        mock_api_call.return_value = expected_data

        power_station_id = "station123"
        serial_number = "test_sn"

        result = self.api.getEnergyStorageIntegratedCabinets(
            power_station_id, serial_number
        )

        assert result == expected_data

        mock_api_call.assert_called_once_with(
            f"/sems-plant/api/equipments/{serial_number}/relatedDevices?sn={serial_number}&deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId={power_station_id}",
            method="GET",
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getEnergyStorageIntegratedCabinets API call",
            is_web=True,
        )

    @patch.object(SemsApi, "_make_api_call")
    def test_get_battery_general_functions(self, mock_api_call):
        """Test battery function request."""
        mock_api_call.return_value = {}

        serial_number = "test_sn"
        bat_index = 1

        result = self.api.getBatteryGeneralFunctions(serial_number, bat_index)

        assert result == {}

        mock_api_call.assert_called_once_with(
            "/sems-remote/api/v2/address/remote/getDeviceFunctionTabMenus",
            method="POST",
            data='{"batIndex": "1", "menuCode": 1, "module": "GENERAL_FUNCTIONS", "sn": "test_sn"}',
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getBatteryGeneralFunctions API call",
            is_web=True,
            retry_on_api_error=False,
        )

    @patch.object(SemsApi, "_make_api_call")
    def test_get_battery_immediate_charging_states(self, mock_api_call):
        """Test getBatteryImmediateChargingStates method."""
        expected_data = {"47545": 0, "47546": 100, "47603": 100}

        mock_api_call.return_value = expected_data

        serial_number = "test_sn"

        result = self.api.getBatteryImmediateChargingStates(serial_number)

        assert result == expected_data

        mock_api_call.assert_called_once_with(
            "/sems-remote/api/v1/address/remote/get-cache-device-function-parameters",
            method="POST",
            data='{"sn": "test_sn", "addresses": ["47545", "47545", "47546", "47603"], "addrFuncMap": {"47545": "2013217017330515970", "47546": "1991791639537946635", "47603": "1991791639537946636"}}',
            renewToken=False,
            maxTokenRetries=2,
            operation_name="getBatteryImmediateChargingStates API call",
            is_web=True,
            retry_on_api_error=False,
        )

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
    @patch.object(SemsApi, "setDeviceFunctionParameters")
    def test_change_status_uses_web_control(self, mock_web_control, mock_control_call):
        """Test inverter status uses the SEMS+ Web control endpoint."""
        mock_web_control.return_value = True

        self.api.change_status(
            "inverter123",
            4,
            plant_id="station123",
            device_name="Inverter",
        )

        mock_web_control.assert_called_once_with(
            "station123",
            "inverter123",
            "Inverter",
            {"80017": 4},
            {"status_setting": "start_up"},
            {"80017": "2043643517552594945"},
            renewToken=False,
            maxTokenRetries=2,
            virtual_sn="inverter123",
        )
        mock_control_call.assert_not_called()

    @patch.object(SemsApi, "_make_control_api_call")
    @patch.object(SemsApi, "setDeviceFunctionParameters")
    def test_change_status_falls_back_to_legacy_control(
        self, mock_web_control, mock_control_call
    ):
        """Test inverter status falls back when Web control fails."""
        mock_web_control.return_value = False
        mock_control_call.return_value = True

        self.api.change_status(
            "inverter123",
            2,
            plant_id="station123",
            device_name="Inverter",
        )

        mock_control_call.assert_called_once()

    @patch.object(SemsApi, "_make_control_api_call")
    @patch.object(SemsApi, "setDeviceFunctionParameters")
    def test_change_status_falls_back_after_web_retries(
        self, mock_web_control, mock_control_call
    ):
        """Test inverter status falls back after Web retries are exhausted."""
        mock_web_control.side_effect = OutOfRetries
        mock_control_call.return_value = True

        self.api.change_status(
            "inverter123",
            2,
            plant_id="station123",
            device_name="Inverter",
        )

        mock_control_call.assert_called_once()

    def test_change_status_success_real_structure(self, requests_mock):
        """Test successful inverter status change."""
        self.api._preferred_login_mode = "legacy"
        login_response = {
            "code": 0,
            "data": {"uid": "test-uid", "token": "test-token"},
            "api": "https://eu.semsportal.com/api/",
        }
        requests_mock.post(OLD_LOGIN_URL, json=login_response)

        endpoint = (
            "https://eu.semsportal.com/api//PowerStation/SaveRemoteControlInverter"
        )
        requests_mock.post(endpoint, json={"status": "success"}, status_code=200)

        self.api.change_status(MOCK_INVERTER_SN, 1)

    @patch.object(SemsApi, "_make_control_api_call")
    def test_change_status_failure(self, mock_control_call):
        """Test change_status method with failure."""
        mock_control_call.return_value = False

        with pytest.raises(
            HomeAssistantError,
            match="Verify that the GoodWe account has remote-control permission",
        ):
            self.api.change_status("inverter123", 1)

        mock_control_call.assert_called_once()

    @pytest.mark.parametrize(
        ("method_name", "value", "address", "function_id", "control_log"),
        [
            (
                "stopImmediateCharging",
                0,
                "47545",
                "2013217017330515970",
                {"stop_charging": "remote_Switch_off"},
            ),
            (
                "startImmediateCharging",
                1,
                "47545",
                "1991791639537946634",
                {"immediate_charge": "on"},
            ),
            (
                "setImmediateChargingEndSoC",
                50,
                "47546",
                "1991791639537946635",
                {"end_charge_soc": 50},
            ),
            (
                "setImmediateChargingChargingPower",
                60,
                "47603",
                "1991791639537946636",
                {"bat_immediate_charge_power": 60},
            ),
        ],
    )
    @patch.object(SemsApi, "_make_api_call")
    def test_set_immediate_charging_parameter(
        self, mock_api_call, method_name, value, address, function_id, control_log
    ):
        """Test immediate-charging parameter updates."""
        method = getattr(self.api, method_name)
        arguments = ("teststation", "inverter123", "mppt1_battery")
        if method_name in {"stopImmediateCharging", "startImmediateCharging"}:
            method(*arguments, address, function_id)
        else:
            method(*arguments, value, address, function_id)

        mock_api_call.assert_called_once_with(
            "/sems-remote/api/v1/address/remote/setDeviceFunctionParameters",
            method="POST",
            data=json.dumps(
                {
                    "sn": "inverter123",
                    "addressMap": {address: value},
                    "addrFuncMap": {address: function_id},
                    "controlItemLogs": control_log,
                    "waitingForDevice": True,
                    "plantId": "teststation",
                    "deviceName": "mppt1_battery",
                }
            ),
            renewToken=False,
            maxTokenRetries=2,
            operation_name="setDeviceFunctionParameters API call",
            is_web=True,
        )

    @patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
    @patch.object(SemsApi, "getWebStationFlow", return_value={"pAc": 2.5, "pGrid": -1})
    @patch.object(SemsApi, "getWebInverterTelecounting", side_effect=OutOfRetries)
    @patch.object(SemsApi, "getWebInverterTelemetry", side_effect=OutOfRetries)
    @patch.object(SemsApi, "getWebInverterDevices")
    def test_get_web_data_keeps_device_when_telemetry_is_unavailable(
        self,
        mock_devices,
        mock_telemetry,
        mock_telecounting,
        mock_flow,
        mock_statistics,
    ):
        """Test station flow keeps a device usable when telemetry is forbidden."""
        mock_devices.return_value = [
            {
                "sn": "SN1",
                "name": "Zolder",
                "subtype": "grid",
                "deviceType": "INVERTER",
            }
        ]

        result = self.api.getWebData("station")
        inverter = result["inverter"][0]["invert_full"]

        assert inverter["pac"] == 2500
        assert inverter["pmeter"] == -1000
        assert result["unavailable_data_sources"] == {
            "inverters": {"SN1": {"telemetry", "counters"}},
            "homekit": set(),
        }
        mock_telemetry.assert_called_once_with(
            "station", "SN1", False, 2, device_type="INVERTER"
        )
        mock_telecounting.assert_called_once_with(
            "station", "SN1", False, 2, device_type="INVERTER"
        )
        mock_flow.assert_called_once_with("station", False, 2)

    @patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
    @patch.object(
        SemsApi, "getWebStationFlow", return_value={"pAc": 0, "pGrid": 0, "pConsum": 0}
    )
    @patch.object(SemsApi, "getWebInverterTelecounting", return_value={})
    @patch.object(
        SemsApi,
        "getWebInverterTelemetry",
        side_effect=[{"meter_power": 1234}, OutOfRetries],
    )
    @patch.object(SemsApi, "getWebInverterDevices")
    def test_get_web_data_does_not_reuse_failed_smart_meter_telemetry(
        self,
        mock_devices,
        mock_telemetry,
        mock_telecounting,
        mock_flow,
        mock_statistics,
    ):
        """Mark smart-meter telemetry unavailable instead of publishing cached data."""
        mock_devices.return_value = [
            {"sn": "METER1", "name": "Meter", "deviceType": "SMART_METER"},
        ]

        self.api.getWebData("station")
        result = self.api.getWebData("station")

        assert "meter_power" not in result["powerflow"]
        assert result["unavailable_data_sources"]["homekit"] == {"telemetry"}
        assert mock_telemetry.call_count == 2

    @patch.object(SemsApi, "_make_api_call")
    def test_get_web_battery_rack_telemetry_maps_existing_battery_entities(
        self, mock_api_call
    ):
        """Test BATTERY_RACK BMS fields use the existing battery entity shape."""
        mock_api_call.return_value = [
            {
                "code": "runtime",
                "factors": [
                    {"code": "soc", "data": "81"},
                    {"code": "soh", "data": "97"},
                    {"code": "pBat", "data": "1.25"},
                    {"code": "voltage", "data": "51.2"},
                    {"code": "a", "data": "24.4"},
                    {"code": "tempMaxCell", "data": "31.5"},
                    {"code": "aMaxChar", "data": "40"},
                    {"code": "aMaxDischar", "data": "50"},
                ],
            }
        ]

        assert self.api.getWebInverterTelemetry(
            "station", "BAT1", device_type="BATTERY_RACK"
        ) == {
            "soc": 81.0,
            "soh": 97.0,
            "pbattery": 1250.0,
            "vbattery": 51.2,
            "ibattery": 24.4,
            "bms_temperature": 31.5,
            "bms_charge_i_max": 40.0,
            "bms_discharge_i_max": 50.0,
        }

    @patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
    @patch.object(SemsApi, "getWebStationFlow", return_value={"pAc": 2.5, "pGrid": -1})
    @patch.object(SemsApi, "getWebInverterTelecounting", return_value={})
    @patch.object(SemsApi, "getWebInverterTelemetry", return_value={})
    @patch.object(SemsApi, "getWebInverterDevices")
    def test_get_web_data_preserves_battery_rack_and_dongle(
        self,
        mock_devices,
        mock_telemetry,
        mock_telecounting,
        mock_flow,
        mock_statistics,
    ):
        """Test non-inverter SEMS+ device groups remain available as entities."""
        mock_devices.return_value = [
            {"sn": "INV1", "name": "Inverter", "deviceType": "INVERTER"},
            {"sn": "BAT1", "name": "Battery", "deviceType": "BATTERY_RACK"},
            {"sn": "DONGLE1", "name": "Dongle", "deviceType": "DONGLE"},
        ]

        result = self.api.getWebData("station")

        assert [item["invert_full"]["deviceType"] for item in result["inverter"]] == [
            "INVERTER",
            "BATTERY_RACK",
            "DONGLE",
        ]
        assert result["inverter"][0]["invert_full"]["pac"] == 2500
        assert result["inverter"][0]["invert_full"]["pmeter"] == -1000
        assert "battery_count" not in result["inverter"][1]["invert_full"]
        assert "more_batterys" not in result["inverter"][1]["invert_full"]
        assert mock_telemetry.call_count == 2
        assert mock_telecounting.call_count == 2

    @patch.object(SemsApi, "_get_web_energy_statistics", return_value=None)
    @patch.object(SemsApi, "getWebStationFlow", return_value={})
    @patch.object(SemsApi, "getWebInverterTelecounting", return_value={})
    @patch.object(SemsApi, "getWebInverterTelemetry", return_value={"pac": 900.0})
    @patch.object(SemsApi, "getWebInverterDevices")
    def test_get_web_data_survives_denied_storage_lookup(
        self,
        mock_devices,
        mock_telemetry,
        mock_telecounting,
        mock_flow,
        mock_statistics,
    ):
        """A denied optional storage lookup must not fail the station refresh."""
        mock_devices.return_value = [
            {
                "sn": "INV1",
                "name": "Inverter",
                "subtype": "store",
                "deviceType": "INVERTER",
            }
        ]
        with patch.object(
            self.api,
            "getEnergyStorageIntegratedCabinets",
            side_effect=SemsPermissionError("relatedDevices", "denied"),
        ):
            result = self.api.getWebData("station")

        inverter = result["inverter"][0]["invert_full"]
        assert inverter["pac"] == 900.0
        assert "battery_count" not in inverter

    @patch.object(SemsApi, "getBatterySystemTelemetry")
    def test_web_batteries_skip_denied_battery_telemetry(self, mock_telemetry):
        """A denied BAT_SYS telemetry request only drops that battery."""
        mock_telemetry.side_effect = [
            SemsPermissionError("BAT_SYS telemetry", "denied"),
            {"soc": 99.0, "power": 1.25},
        ]
        cabinets = [
            {"sn": "BAT_A", "type": "BAT_SYS"},
            {"sn": "BAT_B", "type": "BAT_SYS"},
        ]

        assert self.api._get_web_batteries("station", cabinets) == [
            {"sn": "BAT_B", "soc": 99.0, "pbattery": 1250.0}
        ]


class TestOutOfRetries:
    """Test OutOfRetries exception."""

    def test_out_of_retries_exception(self):
        """Test OutOfRetries exception creation."""
        exception = OutOfRetries("Test message")
        assert str(exception) == "Test message"
        assert isinstance(exception, Exception)


if __name__ == "__main__":
    pytest.main([__file__])

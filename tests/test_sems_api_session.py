"""Tests for serialized SEMS+ logins, back-off and request caching."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from unittest.mock import Mock, patch

import pytest

from custom_components.sems.sems_api import (
    NEW_LOGIN_URL,
    OutOfRetries,
    SemsApi,
    SemsAuthError,
    SemsAuthExpiredError,
    SemsRateLimitedError,
)

API_BASE = "https://eu-gateway.example.test/web/sems"
FLOW_URL = f"{API_BASE}/sems-plant/api/stations/flow"
STATISTICS_URL = f"{API_BASE}/sems-plant/api/stations/statistics"
PRODUCTION_URL = f"{API_BASE}/sems-plant/api/stations/production"
FUNCTION_MENUS_URL = (
    f"{API_BASE}/sems-remote/api/v2/address/remote/getDeviceFunctionTabMenus"
)
MOCK_USERNAME = "user@example.com"
MOCK_PASSWORD = "test_password"
MOCK_INVERTER_SN = "GW0000SN000TEST1"
MOCK_STATION_ID_1 = "12345678-1234-5678-9abc-123456789abc"
MOCK_STATION_ID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class FakeSemsServer:
    """SEMS+ Web stand-in that accepts only the most recently issued token."""

    def __init__(self, requests_mock: Any, login_delay: float = 0.0) -> None:
        """Register the login and flow endpoints."""
        self.logins = 0
        self.current_token: str | None = None
        self.login_delay = login_delay
        self._lock = threading.Lock()
        requests_mock.post(NEW_LOGIN_URL, json=self._login)
        requests_mock.get(FLOW_URL, json=self._flow)

    def _login(self, request: Any, context: Any) -> dict[str, Any]:
        with self._lock:
            self.logins += 1
            self.current_token = f"token-{self.logins}"
            token = self.current_token
        time.sleep(self.login_delay)
        return {
            "code": "00000",
            "data": {
                "uid": "test-uid",
                "token": token,
                "timestamp": 1,
                "client": "semsPlusWeb",
            },
            "api": API_BASE,
        }

    def _flow(self, request: Any, context: Any) -> dict[str, Any]:
        token = json.loads(request.headers["token"]).get("token")
        if token != self.current_token:
            return {"code": "C0602", "description": "account login abnormal"}
        return {"code": "00000", "data": {"pAc": 1.0}}


def _web_token(token: str) -> dict[str, Any]:
    return {
        "uid": "test-uid",
        "token": token,
        "timestamp": 1,
        "client": "semsPlusWeb",
        "api": API_BASE,
    }


def _run_parallel(count: int, target: Any) -> list[Any]:
    """Run target in threads that start together; return results/exceptions."""
    barrier = threading.Barrier(count)
    results: list[Any] = [None] * count

    def worker(index: int) -> None:
        barrier.wait()
        try:
            results[index] = target()
        except Exception as err:
            results[index] = err

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    return results


# ---------------------------------------------------------------------------
# Serialized re-authentication
# ---------------------------------------------------------------------------


@contextmanager
def _sync_first_request(api: SemsApi, count: int):
    """Hold each thread after it got its first token until all threads have one.

    This makes every thread send its first request with the same token.
    """
    original = api._get_authenticated_request_context
    barrier = threading.Barrier(count, timeout=5)
    synced = threading.local()

    def context(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if not getattr(synced, "done", False):
            synced.done = True
            barrier.wait()
        return result

    with patch.object(api, "_get_authenticated_request_context", side_effect=context):
        yield


def test_concurrent_requests_with_stale_token_log_in_once(requests_mock) -> None:
    """Parallel requests rejected with a stale token share one new login."""
    server = FakeSemsServer(requests_mock, login_delay=0.05)
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("stale-token")

    with _sync_first_request(api, 6):
        results = _run_parallel(6, lambda: api.getWebStationFlow(MOCK_STATION_ID_1))

    stale = [
        r
        for r in requests_mock.request_history
        if r.url.startswith(FLOW_URL) and "stale-token" in r.headers["token"]
    ]
    assert len(stale) == 6

    assert results == [{"pAc": 1.0}] * 6
    assert server.logins == 1
    assert api._web_token is not None
    assert api._web_token["token"] == "token-1"


def test_concurrent_requests_without_token_log_in_once(requests_mock) -> None:
    """Parallel first requests of a fresh client share one login."""
    server = FakeSemsServer(requests_mock, login_delay=0.05)
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)

    with _sync_first_request(api, 4):
        results = _run_parallel(4, lambda: api.getWebStationFlow(MOCK_STATION_ID_1))

    assert results == [{"pAc": 1.0}] * 4
    assert server.logins == 1


def test_rejected_fresh_token_re_authenticates_only_once(requests_mock) -> None:
    """A request logs in at most once, even if SEMS rejects the new token too."""
    requests_mock.post(
        NEW_LOGIN_URL,
        json={"code": "00000", "data": _web_token("fresh"), "api": API_BASE},
    )
    requests_mock.get(
        FLOW_URL, json={"code": "C0602", "description": "account login abnormal"}
    )
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("stale-token")

    with pytest.raises(OutOfRetries):
        api.getWebStationFlow(MOCK_STATION_ID_1)

    assert requests_mock.request_history[-1].url.startswith(FLOW_URL)
    logins = [r for r in requests_mock.request_history if r.url == NEW_LOGIN_URL]
    flows = [r for r in requests_mock.request_history if r.url.startswith(FLOW_URL)]
    assert len(logins) == 1
    assert len(flows) == 2


@pytest.mark.parametrize("code", ["100004", "read_fail", "E500"])
def test_non_auth_error_codes_do_not_log_in(requests_mock, code: str) -> None:
    """Only session codes trigger a login; other API errors fail directly."""
    requests_mock.post(NEW_LOGIN_URL, json={"code": "00000"})
    requests_mock.get(FLOW_URL, json={"code": code, "description": "error"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")

    with pytest.raises(OutOfRetries):
        api.getWebStationFlow(MOCK_STATION_ID_1)

    assert requests_mock.call_count == 1
    assert not any(r.url == NEW_LOGIN_URL for r in requests_mock.request_history)


def test_authorization_expired_code_re_authenticates(requests_mock) -> None:
    """The legacy authorization-expired code also renews the token."""
    server = FakeSemsServer(requests_mock)
    requests_mock.get(
        FLOW_URL,
        [
            {"json": {"code": "100002", "msg": "authorization expired"}},
            {"json": {"code": "00000", "data": {"pAc": 2.0}}},
        ],
    )
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("expired-token")

    assert api.getWebStationFlow(MOCK_STATION_ID_1) == {"pAc": 2.0}
    assert server.logins == 1


def test_session_failure_is_warned_once(requests_mock, caplog) -> None:
    """Repeated session failures do not flood the log with warnings."""
    requests_mock.post(
        NEW_LOGIN_URL,
        json={"code": "00000", "data": _web_token("fresh"), "api": API_BASE},
    )
    requests_mock.get(FLOW_URL, json={"code": "C0602", "description": "abnormal"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)

    for _ in range(3):
        with pytest.raises(OutOfRetries):
            api.getWebStationFlow(MOCK_STATION_ID_1)

    warnings = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    assert len(warnings) == 1
    assert "even after re-authentication" in warnings[0].getMessage()


# ---------------------------------------------------------------------------
# Rate limiting and rejected logins
# ---------------------------------------------------------------------------


def test_http_429_starts_cooldown_without_login(requests_mock) -> None:
    """HTTP 429 pauses the client and never triggers a login."""
    requests_mock.post(NEW_LOGIN_URL, json={"code": "00000"})
    requests_mock.get(FLOW_URL, status_code=429, headers={"Retry-After": "120"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")

    with pytest.raises(SemsRateLimitedError) as err:
        api.getWebStationFlow(MOCK_STATION_ID_1)
    assert err.value.retry_after == 120

    # Parallel callers during the cool-down neither log in nor hit the API.
    results = _run_parallel(5, lambda: api.getWebStationFlow(MOCK_STATION_ID_2))
    assert all(isinstance(result, SemsRateLimitedError) for result in results)
    assert requests_mock.call_count == 1
    assert not any(r.url == NEW_LOGIN_URL for r in requests_mock.request_history)


def test_http_429_on_login_pauses_further_logins(requests_mock) -> None:
    """A throttled login is not retried by the next request."""
    requests_mock.post(NEW_LOGIN_URL, status_code=429)
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)

    for _ in range(3):
        with pytest.raises(SemsRateLimitedError):
            api.getWebStationFlow(MOCK_STATION_ID_1)

    assert requests_mock.call_count == 1


def test_cooldown_grows_exponentially_and_resets_on_success(requests_mock) -> None:
    """Consecutive rate limits double the pause up to the cap."""
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")
    requests_mock.get(FLOW_URL, status_code=429)

    delays = []
    for _ in range(6):
        with pytest.raises(SemsRateLimitedError) as err:
            api.getWebStationFlow(MOCK_STATION_ID_1)
        delays.append(err.value.retry_after)
        api._cooldown_until = 0.0  # let the pause expire

    assert delays == [60, 120, 240, 480, 900, 900]

    requests_mock.get(FLOW_URL, json={"code": "00000", "data": {"pAc": 1.0}})
    api.getWebStationFlow(MOCK_STATION_ID_1)
    requests_mock.get(FLOW_URL, status_code=429)
    with pytest.raises(SemsRateLimitedError) as err:
        api.getWebStationFlow(MOCK_STATION_ID_1)
    assert err.value.retry_after == 60


def test_rate_limit_code_uses_cooldown(requests_mock) -> None:
    """The GY0429 response code pauses the client like HTTP 429."""
    requests_mock.get(FLOW_URL, json={"code": "GY0429", "msg": "Too many requests"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")

    with pytest.raises(SemsRateLimitedError) as err:
        api.getWebStationFlow(MOCK_STATION_ID_1)
    assert err.value.retry_after == 300
    with pytest.raises(SemsRateLimitedError):
        api.getWebStationFlow(MOCK_STATION_ID_1)
    assert requests_mock.call_count == 1


def test_rejected_login_pauses_and_then_requests_reauth(requests_mock) -> None:
    """Repeatedly rejected credentials end in SemsAuthError, not a login loop."""
    requests_mock.post(NEW_LOGIN_URL, json={"code": "100005", "msg": "bad password"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)

    for _ in range(2):
        with pytest.raises(SemsRateLimitedError):
            api.getWebStationFlow(MOCK_STATION_ID_1)
        # Nothing is sent while paused.
        with pytest.raises(SemsRateLimitedError):
            api.getWebStationFlow(MOCK_STATION_ID_1)
        api._cooldown_until = 0.0

    with pytest.raises(SemsAuthError):
        api.getWebStationFlow(MOCK_STATION_ID_1)
    assert requests_mock.call_count == 3


def test_abnormal_login_code_is_not_treated_as_bad_credentials(
    requests_mock,
) -> None:
    """C0602 at login can be risk control, so it only pauses the client."""
    requests_mock.post(NEW_LOGIN_URL, json={"code": "C0602", "msg": "abnormal"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)

    for _ in range(5):
        with pytest.raises(SemsRateLimitedError):
            api.getWebStationFlow(MOCK_STATION_ID_1)
        api._cooldown_until = 0.0


@pytest.mark.parametrize(
    ("header", "expected"), [("30", 30), ("-5", 0), ("soon", None), (None, None)]
)
def test_parse_retry_after(header: str | None, expected: int | None) -> None:
    """Only numeric Retry-After headers are used."""
    assert SemsApi._parse_retry_after(header) == expected


def test_control_call_renews_rejected_legacy_token() -> None:
    """A control command rejected for its token is retried with a new login."""
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._token = {"token": "stale", "api": "https://eu.semsportal.example"}
    fresh = {"token": "fresh", "api": "https://eu.semsportal.example"}

    with (
        patch.object(api, "getLoginToken", return_value=fresh) as mock_login,
        patch.object(
            api,
            "_make_http_request",
            side_effect=[
                SemsAuthExpiredError("control rejected the token"),
                {"code": 0},
            ],
        ) as mock_request,
    ):
        assert api._make_control_api_call({"InverterSN": MOCK_INVERTER_SN})

    mock_login.assert_called_once()
    assert mock_request.call_count == 2


def test_update_credentials_drops_tokens() -> None:
    """A new password invalidates tokens and earlier rejections."""
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("old")
    api._auth_rejections = 2

    api.update_credentials(MOCK_PASSWORD)
    assert api._web_token is not None

    api.update_credentials("new_password")
    assert api._web_token is None
    assert api._auth_rejections == 0
    assert api._password == "new_password"


def test_client_uses_one_session(requests_mock) -> None:
    """All requests go through the client's session, which close() closes."""
    requests_mock.get(FLOW_URL, json={"code": "00000", "data": {}})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")

    with patch.object(api._session, "close") as mock_close:
        api.getWebStationFlow(MOCK_STATION_ID_1)
        api.close()

    mock_close.assert_called_once()


def test_at_most_two_requests_in_flight() -> None:
    """The shared client never has more than two requests in flight."""
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def send(*args: Any, **kwargs: Any) -> Mock:
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        response = Mock(status_code=200)
        response.json.return_value = {"code": "00000", "data": {}}
        return response

    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")

    with patch.object(api._session, "request", side_effect=send):
        results = _run_parallel(6, lambda: api.getWebStationFlow(MOCK_STATION_ID_1))

    assert results == [{}] * 6
    assert peak == 2


# ---------------------------------------------------------------------------
# Caching of slow or failing optional requests
# ---------------------------------------------------------------------------


def test_station_production_is_cached(requests_mock) -> None:
    """Station production is fetched once per refresh period."""
    requests_mock.post(
        PRODUCTION_URL, json={"code": "00000", "data": {"currency": "EUR"}}
    )
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 1, 23, 59, 59)

    assert api._get_web_production(MOCK_STATION_ID_1, start, end) == {"currency": "EUR"}
    assert api._get_web_production(MOCK_STATION_ID_1, start, end) == {"currency": "EUR"}
    assert requests_mock.call_count == 1
    # Another station of the shared account has its own entry.
    api._get_web_production(MOCK_STATION_ID_2, start, end)
    assert requests_mock.call_count == 2


def test_failed_statistics_are_not_retried_every_refresh(requests_mock) -> None:
    """A failed statistics request waits before it is tried again."""
    requests_mock.post(STATISTICS_URL, json={"code": "E500", "msg": "timeout"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")
    start = datetime(2026, 1, 1)
    end = datetime(2026, 12, 31, 23, 59, 59)

    for _ in range(3):
        assert api._get_web_statistics(MOCK_STATION_ID_1, "year", start, end) is None
    assert requests_mock.call_count == 1

    # After the retry delay the request is sent again.
    key = f"failed:{MOCK_STATION_ID_1}:year:{start.date()}:{end.date()}"
    api._web_cache[key] = (time.monotonic() - 301, None)
    requests_mock.post(
        STATISTICS_URL,
        json={
            "code": "00000",
            "data": {
                "dataList": [
                    {
                        "item": "proSystemTotalStats",
                        "statisticsList": [{"date": "2026", "val": "5.5"}],
                    }
                ]
            },
        },
    )
    assert api._get_web_statistics(MOCK_STATION_ID_1, "year", start, end) == {
        "proSystemTotalStats": [5.5]
    }
    assert requests_mock.call_count == 2


def test_failed_statistics_refresh_keeps_last_value(requests_mock) -> None:
    """An expired but successful result is kept when the refresh fails."""
    requests_mock.post(STATISTICS_URL, json={"code": "E500", "msg": "timeout"})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 1, 23, 59, 59)
    key = f"{MOCK_STATION_ID_1}:day:{start.date()}:{end.date()}"
    api._web_cache[key] = (time.monotonic() - 1_000, {"proSystemTotalStats": [1.0]})

    assert api._get_web_statistics(MOCK_STATION_ID_1, "day", start, end) == {
        "proSystemTotalStats": [1.0]
    }


def test_battery_function_menus_are_cached(requests_mock) -> None:
    """Static battery function menus are not refetched on every refresh."""
    menus = {"functionMenus": {"children": [{"functions": []}]}}
    requests_mock.post(FUNCTION_MENUS_URL, json={"code": "00000", "data": menus})
    api = SemsApi(Mock(), MOCK_USERNAME, MOCK_PASSWORD)
    api._web_token = _web_token("valid-token")

    assert api.getBatteryGeneralFunctions(MOCK_INVERTER_SN, 1) == menus
    assert api.getBatteryGeneralFunctions(MOCK_INVERTER_SN, 1) == menus
    assert requests_mock.call_count == 1

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Literal, NamedTuple

import requests
from homeassistant import exceptions
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import redact_for_log

_LOGGER = logging.getLogger(__name__)

OLD_LOGIN_URL = "https://www.semsportal.com/api/v3/Common/CrossLogin"
NEW_LOGIN_URL = "https://semsplus.goodwe.com/web/sems/sems-user/api/v1/auth/cross-login"
_SUPPORTED_WEB_DEVICE_TYPES = {
    "INVERTER",
    "SMART_METER",
    "ENERGY_STORAGE_INTEGRATED_CABINET",
    "BATTERY_RACK",
    "DONGLE",
    "EV_CHARGER",
}
_WEB_INVERTER_ENTITY_TYPES = {
    "INVERTER",
    "ENERGY_STORAGE_INTEGRATED_CABINET",
    "BATTERY_RACK",
    "DONGLE",
}
_WEB_REAL_INVERTER_TYPES = {
    "INVERTER",
    "ENERGY_STORAGE_INTEGRATED_CABINET",
}
_WEB_STATISTICS_KEY_MAP = {
    "proSystemTotalStats": "sum",
    "proPurchaseStats": "buy",
    "proGridStats": "sell",
    "proConsumStats": "consumptionOfLoad",
    "proSelfConsumStats": "selfUseOfPv",
    "proCharStats": "charge",
    "proDischarStats": "disCharge",
}
_WEB_STATISTICS_RATE_MAP = {
    "contributionRate": "contributingRate",
    "proSelfConsumRate": "selfUseRate",
}
# SEMS+ Web data requests use GET with stationId/pwId query parameters and the
# Web token plus X-Signature headers.
_RequestTimeout = 30  # seconds
_RateLimitRetryAfterSeconds = 300
# One client is shared by all stations of an account; keep its load bounded.
_MaxConcurrentRequests = 2
# Client-wide cool-down after rate limiting or a rejected login. It doubles on
# each consecutive failure; Retry-After is honoured up to its own cap.
_CooldownBaseSeconds = 60
_CooldownMaxSeconds = 900
_RetryAfterMaxSeconds = 3_600

_SuccessCodes = {0, "0", "00000"}
_RateLimitCode = "GY0429"
# Codes for a token the server no longer accepts (expired or replaced session).
# Only these trigger a re-login.
_AuthExpiredCodes = {"100002", "C0602"}
# Login rejections that say nothing about the credentials themselves.
_TransientLoginCodes = {"C0602", _RateLimitCode}
# Consecutive credential rejections before the entry asks for reauthentication.
_AuthRejectionsBeforeReauth = 3
_BrowserUserAgent = "Home Assistant GoodWe SEMS API Integration"
_SemsPlusWebUserAgent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

_DefaultHeaders = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "token": '{"version":"3.1.1","client":"ios","language":"en"}',
}

_NewLoginHeaders = {
    "Content-Type": "application/json",
    "Accept": "application/json, */*;q=0.5",
}

_NewSEMSPlusWebLoginHeaders = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://semsplus.goodwe.com",
    "Referer": "https://semsplus.goodwe.com/",
    "Token": '{"uid":"","timestamp":0,"token":"","client":"semsPlusWeb","version":"","language":"en"}',
}


_NewLoginFallbackApi = "https://eu-gateway.semsportal.com/web/sems"
_LegacyApiFallback = "https://eu.semsportal.com/api"

type TokenType = Literal["legacy", "new", "web"]
type LoginHandler = Callable[[str, str], dict[str, Any] | None]


class ApiEndpoint(NamedTuple):
    """Authenticated API endpoint and the token type it requires."""

    url_part: str
    token_type: TokenType


_POWER_CONTROL_ENDPOINT = ApiEndpoint(
    "/PowerStation/SaveRemoteControlInverter", "legacy"
)
_WEB_INVERTER_STATUS_ADDRESS = "80017"
_WEB_INVERTER_STATUS_FUNCTION_ID = "2043643517552594945"
_WEB_DEVICE_STATUS_ENDPOINT = ApiEndpoint(
    "/sems-plant/api/stations/device/all-status", "web"
)
_WEB_TELEMETRY_ENDPOINT = ApiEndpoint(
    "/sems-plant/api/equipments/{serial_number}/telemetry", "web"
)
_WEB_TELECOUNTING_ENDPOINT = ApiEndpoint(
    "/sems-plant/api/equipments/{serial_number}/telecounting", "web"
)
_WEB_STATION_FLOW_ENDPOINT = ApiEndpoint("/sems-plant/api/stations/flow", "web")
_WEB_STATION_LIST_ENDPOINT = ApiEndpoint("/sems-plant/api/portal/stations/page", "web")
_WEB_STATION_STATISTICS_ENDPOINT = ApiEndpoint(
    "/sems-plant/api/stations/statistics", "web"
)
_WEB_STATION_PRODUCTION_ENDPOINT = ApiEndpoint(
    "/sems-plant/api/stations/production", "web"
)
# EV chargers (e.g. HCA wallboxes) are read and controlled through the same
# SEMS+ Web endpoints the Web UI uses on the charger device page.
_WEB_EV_CHARGER_MODE_INFO_ENDPOINT = ApiEndpoint(
    "/sems-remote/api/ev-charger/control-item-content-list/{serial_number}", "web"
)
_WEB_EV_CHARGER_LAST_CHARGE_ENDPOINT = ApiEndpoint(
    "/sems-plant/api/v1/chargePile/getLastCharge", "web"
)
_WEB_EV_CHARGER_COMMAND_URL_PART = "/sems-remote/api/ev-charger/{command}"
_WEB_STATISTICS_ITEMS = [
    "proConsumStats",
    "proGridStats",
    "proPurchaseStats",
    "proSelfConsumStats",
    "proDischarStats",
    "proCharStats",
    "proSystemTotalStats",
]
_WEB_STATISTICS_REFRESH_SECONDS = 300
_WEB_HISTORIC_STATISTICS_REFRESH_SECONDS = 86_400
_WEB_STATISTICS_EARLIEST_YEAR = 2015
_WEB_RELATED_DEVICES_REFRESH_SECONDS = 3_600
_WEB_DEVICE_LIST_CACHE_SECONDS = 3_600
_WEB_FAILED_REQUEST_RETRY_SECONDS = 300
_WEB_FUNCTION_MENUS_REFRESH_SECONDS = 21_600
# Cache entries not refreshed for this long are dropped. Statistics keys
# contain dates, so without pruning the cache grows every day.
_WEB_CACHE_MAX_AGE_SECONDS = 2 * _WEB_HISTORIC_STATISTICS_REFRESH_SECONDS
_WEB_CACHE_PRUNE_INTERVAL_SECONDS = 3_600
# Counter caches hold the last valid counter values for the plausibility
# checks; they are not date-keyed and must survive pruning.
_WEB_CACHE_PERSISTENT_PREFIXES = ("counters:",)


class SemsApi:
    """Interface to the SEMS API."""

    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        """Init dummy hub."""
        self._hass = hass
        self._username = username
        self._password = password
        self._token: dict[str, Any] | None = None
        self._new_token: dict[str, Any] | None = None
        self._web_token: dict[str, Any] | None = None  # Used for SEMS+ web APIs
        self._preferred_login_mode: TokenType | None = None
        self._web_cache: dict[str, tuple[float, Any]] = {}
        self._web_cache_lock = threading.Lock()
        self._web_cache_pruned_at = time.monotonic()
        self._session = requests.Session()
        self._request_slots = threading.BoundedSemaphore(_MaxConcurrentRequests)
        # Logins are serialized. Each successful login bumps the generation of
        # its token type, so a request that was rejected with an older token
        # reuses a token another thread already fetched instead of logging in.
        self._auth_lock = threading.Lock()
        self._token_generation: dict[TokenType, int] = {
            "legacy": 0,
            "new": 0,
            "web": 0,
        }
        self._last_login_rejection_code: str | None = None
        self._auth_rejections = 0
        self._session_failure_logged = False
        self._cooldown_lock = threading.Lock()
        self._cooldown_until = 0.0
        self._cooldown_strikes = 0

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def update_credentials(self, password: str) -> None:
        """Use a new password, dropping tokens obtained with the old one."""
        with self._auth_lock:
            if password == self._password:
                return
            self._password = password
            self._token = None
            self._new_token = None
            self._web_token = None
            self._auth_rejections = 0

    def test_authentication(self) -> bool:
        """Test if we can authenticate with the host."""
        try:
            self._web_token = self._get_web_login_token(self._username, self._password)
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            requests.RequestException,
        ) as exception:
            _LOGGER.warning("SEMS+ Web authentication failed: %s", exception)
        else:
            if self._web_token is not None:
                return True

        try:
            self._token = self.getLoginToken(self._username, self._password)
        except (AttributeError, KeyError, TypeError, ValueError) as exception:
            _LOGGER.exception("SEMS Authentication exception: %s", exception)
            return False
        else:
            return self._token is not None

    def _make_http_request(
        self,
        url: str,
        headers: dict[str, str],
        data: str | None = None,
        json_data: dict[str, Any] | None = None,
        operation_name: str = "HTTP request",
        validate_code: bool = True,
        method: str = "POST",
    ) -> dict[str, Any] | None:
        """Make a generic HTTP request with error handling and optional code validation."""
        self._raise_if_cooling_down(operation_name)
        try:
            _LOGGER.debug("SEMS - Making %s to %s", operation_name, url)
            with self._request_slots:
                response = self._session.request(
                    method.upper(),
                    url,
                    headers={"User-Agent": _BrowserUserAgent, **headers},
                    data=data,
                    json=json_data,
                    timeout=_RequestTimeout,
                )

            _LOGGER.debug("%s Response: %s", operation_name, response)
            # _LOGGER.debug("%s Response text: %s", operation_name, response.text)

            if response.status_code == 429:
                retry_after = self._start_cooldown(
                    self._parse_retry_after(response.headers.get("Retry-After"))
                )
                _LOGGER.warning(
                    "SEMS rate limited %s (HTTP 429); pausing requests for %ss",
                    operation_name,
                    retry_after,
                )
                raise SemsRateLimitedError(
                    retry_after=retry_after,
                    message=f"{operation_name} returned HTTP 429",
                )

            response.raise_for_status()
            json_response: dict[str, Any] = response.json()
            response_code = json_response.get("code")

            if self._is_sensitive_operation(operation_name):
                _LOGGER.debug(
                    "SEMS - %s response payload: %s",
                    operation_name,
                    redact_for_log(json_response),
                )

            _LOGGER.debug(
                "SEMS - %s response summary: code=%s msg=%s description=%s api=%s has_data=%s",
                operation_name,
                response_code,
                json_response.get("msg"),
                json_response.get("description"),
                json_response.get("api")
                or (
                    json_response.get("data", {}).get("api")
                    if isinstance(json_response.get("data"), dict)
                    else None
                ),
                json_response.get("data") not in (None, "", [], {}),
            )

            if str(response_code) == _RateLimitCode:
                retry_after = self._start_cooldown(_RateLimitRetryAfterSeconds)
                _LOGGER.warning(
                    "SEMS rate limited %s (code %s); pausing requests for %ss",
                    operation_name,
                    _RateLimitCode,
                    retry_after,
                )
                raise SemsRateLimitedError(
                    retry_after=retry_after,
                    message=(
                        f"{operation_name} returned rate-limit code {_RateLimitCode}"
                    ),
                )

            if str(response_code) == "100025":
                raise SemsPermissionError(
                    operation_name,
                    self._response_error_message(json_response),
                )

            # Login responses are classified by _extract_login_token instead.
            is_login = self._is_sensitive_operation(operation_name)
            if str(response_code) in _AuthExpiredCodes and not is_login:
                _LOGGER.debug(
                    "%s rejected the token with code %s: %s",
                    operation_name,
                    response_code,
                    self._response_error_message(json_response),
                )
                raise SemsAuthExpiredError(
                    f"{operation_name} rejected the token with code {response_code}"
                )

            if response_code in _SuccessCodes:
                self._reset_cooldown()

            # Validate response code if requested
            if validate_code:
                if response_code not in _SuccessCodes:
                    _LOGGER.warning(
                        "%s failed with code: %s, message: %s",
                        operation_name,
                        response_code,
                        self._response_error_message(json_response),
                    )
                    return None

            return json_response

        except requests.HTTPError as exception:
            if (response := exception.response) is not None:
                if self._is_sensitive_operation(operation_name):
                    _LOGGER.error(
                        "Unable to complete %s: status=%s url=%s (response body redacted)",
                        operation_name,
                        response.status_code,
                        response.url,
                    )
                else:
                    _LOGGER.error(
                        "Unable to complete %s: status=%s url=%s body=%s",
                        operation_name,
                        response.status_code,
                        response.url,
                        response.text,
                    )
            else:
                _LOGGER.error("Unable to complete %s: %s", operation_name, exception)
            raise
        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.warning("Unable to complete %s: %s", operation_name, exception)
            raise

    @staticmethod
    def _parse_retry_after(value: str | None) -> int | None:
        """Return a Retry-After header in seconds, if given as a number."""
        try:
            return max(0, int(value)) if value is not None else None
        except ValueError:
            return None

    def _start_cooldown(self, retry_after: int | None = None) -> int:
        """Pause all requests of this client and return the pause in seconds."""
        with self._cooldown_lock:
            now = time.monotonic()
            if self._cooldown_until > now:
                # Parallel requests hitting the same limit extend nothing.
                return math.ceil(self._cooldown_until - now)
            self._cooldown_strikes += 1
            delay = min(
                _CooldownBaseSeconds * 2 ** (self._cooldown_strikes - 1),
                _CooldownMaxSeconds,
            )
            if retry_after:
                delay = max(delay, min(retry_after, _RetryAfterMaxSeconds))
            self._cooldown_until = now + delay
            return delay

    def _reset_cooldown(self) -> None:
        """Forget earlier failures after a successful response."""
        if self._cooldown_strikes:
            with self._cooldown_lock:
                self._cooldown_strikes = 0

    def _raise_if_cooling_down(self, operation_name: str) -> None:
        """Skip requests while the client is cooling down."""
        remaining = self._cooldown_until - time.monotonic()
        if remaining > 0:
            raise SemsRateLimitedError(
                retry_after=math.ceil(remaining),
                message=(
                    f"{operation_name} skipped; SEMS requests are paused for "
                    f"{math.ceil(remaining)}s"
                ),
            )

    def _is_sensitive_operation(self, operation_name: str) -> bool:
        """Return True if the operation name indicates it handles sensitive credentials."""
        return "login" in operation_name.lower()

    @staticmethod
    def _response_error_message(json_response: dict[str, Any]) -> str:
        """Return the most useful non-sensitive message from an API response."""
        for key in ("msg", "description", "errorMsg", "translationCode"):
            message = json_response.get(key)
            if isinstance(message, str) and message:
                return message
        return "Unknown error"

    def _hash_password_for_new_login(self, password: str) -> str:
        """Return the SEMS+ password encoding."""
        # MD5 is required by the SEMS+ API protocol; usedforsecurity=False avoids
        # failures on FIPS-enabled systems where MD5 is disabled for security use.
        md5_password = hashlib.md5(
            password.encode("utf-8"), usedforsecurity=False
        ).hexdigest()
        return base64.b64encode(md5_password.encode("utf-8")).decode("utf-8")

    def _is_powerstation_route(self, url_part: str) -> bool:
        """Return whether the route should use the legacy PowerStation host."""
        return url_part.startswith("/PowerStation") or url_part.startswith(
            "/v3/PowerStation"
        )

    def _extract_gateway_region(self, api_base: str) -> str | None:
        """Return the SEMS region prefix from a gateway API base."""
        host = api_base.split("//", 1)[-1].split("/", 1)[0]
        if host.endswith("-gateway.semsportal.com"):
            return host.removesuffix("-gateway.semsportal.com") or None

        if host.endswith(".semsportal.com"):
            return host.split(".", 1)[0] or None

        return None

    def _normalize_powerstation_api_base(self, api_base: str, url_part: str) -> str:
        """Return the effective API base for PowerStation requests."""
        if not self._is_powerstation_route(url_part):
            return api_base

        if "/web/sems" not in api_base and "/sems/" not in api_base:
            return api_base

        region = None
        if isinstance(self._token, dict) and isinstance(self._token.get("region"), str):
            region = self._token["region"] or None
        if region is None:
            region = self._extract_gateway_region(api_base)

        if region:
            rewritten_base = f"https://{region}.semsportal.com/api"
            _LOGGER.debug(
                "SEMS - Rewriting API base from %s to %s for %s",
                api_base,
                rewritten_base,
                url_part,
            )
            return rewritten_base

        _LOGGER.debug(
            "SEMS - Rewriting API base from %s to fallback %s for %s",
            api_base,
            _LegacyApiFallback,
            url_part,
        )
        return _LegacyApiFallback

    def _get_authenticated_request_context(
        self,
        url_part: str,
        renewToken: bool,
        operation_name: str,
        token_type: TokenType = "legacy",
        stale_generation: int | None = None,
    ) -> tuple[str, dict[str, str], int]:
        """Return the request URL, headers and token generation for a call.

        `stale_generation` is the generation of a token the server rejected.
        """
        if renewToken and stale_generation is None:
            stale_generation = self._token_generation[token_type]
        token, generation = self._get_token(
            token_type, operation_name, stale_generation
        )

        api_base = self._normalize_powerstation_api_base(token["api"], url_part)
        api_url = api_base + url_part
        headers = self._build_authenticated_headers(token)

        _LOGGER.debug(
            "SEMS - %s request context: api_base=%s effective_api_base=%s url_part=%s token=%s",
            operation_name,
            token.get("api"),
            api_base,
            url_part,
            redact_for_log(token),
        )
        return api_url, headers, generation

    def _stored_token(self, token_type: TokenType) -> dict[str, Any] | None:
        """Return the current token of a type."""
        if token_type == "web":
            return self._web_token
        if token_type == "new":
            return self._new_token
        return self._token

    def _get_token(
        self,
        token_type: TokenType,
        operation_name: str,
        stale_generation: int | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Return a usable token and its generation, logging in only if needed.

        Raises SemsRateLimitedError while logins are paused and SemsAuthError
        once the credentials were rejected repeatedly.
        """
        with self._auth_lock:
            token = self._stored_token(token_type)
            generation = self._token_generation[token_type]
            if token is not None and stale_generation != generation:
                return token, generation

            # No login attempts while rate limited or after a failed login.
            self._raise_if_cooling_down(operation_name)
            _LOGGER.debug(
                "SEMS %s token missing or rejected, logging in for %s",
                token_type,
                operation_name,
            )
            self._last_login_rejection_code = None
            if token_type == "web":
                token = self._get_new_login_token(
                    self._username, self._password, is_web=True
                )
                self._web_token = token
            elif token_type == "new":
                token = self._get_new_login_token(self._username, self._password)
                self._new_token = token
            else:
                token = self.getLoginToken(self._username, self._password)
                self._token = token
                # A legacy re-login invalidates the SEMS+ Web session server-side.
                self._web_token = None

            if token is not None:
                self._auth_rejections = 0
                self._token_generation[token_type] += 1
                return token, self._token_generation[token_type]

            code = self._last_login_rejection_code
            if code is not None and code not in _TransientLoginCodes:
                self._auth_rejections += 1
            if self._auth_rejections >= _AuthRejectionsBeforeReauth:
                raise SemsAuthError(
                    f"SEMS rejected the credentials {self._auth_rejections} "
                    f"times in a row (code {code})"
                )
            retry_after = self._start_cooldown()
            _LOGGER.warning(
                "SEMS %s login failed (code %s); pausing requests for %ss",
                token_type,
                code,
                retry_after,
            )
            raise SemsRateLimitedError(
                retry_after=retry_after,
                message=f"SEMS {token_type} login failed for {operation_name}",
            )

    def _build_authenticated_headers(
        self,
        token_data: dict[str, Any],
    ) -> dict[str, str]:
        """Build request headers for authenticated API calls."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "token": json.dumps(token_data),
        }

        if token_data.get("client") == "semsPlusWeb":
            headers["X-Signature"] = self._generate_signature(token_data)

        return headers

    def _generate_signature(self, token_data: dict[str, Any]) -> str:
        epoch_ms = round(time.time() * 1000)
        digest = hashlib.sha256(
            f"{epoch_ms}@{token_data.get('uid', '')}@{token_data.get('token', '')}".encode()
        ).hexdigest()
        sig = f"{digest}@{epoch_ms}"
        return base64.b64encode(sig.encode()).decode()

    def _get_login_mode_order(self) -> list[TokenType]:
        """Return login modes in preferred order."""
        login_modes: list[TokenType] = ["new", "legacy", "web"]
        if self._preferred_login_mode in login_modes:
            login_modes.remove(self._preferred_login_mode)
            login_modes.insert(0, self._preferred_login_mode)
        return login_modes

    def _login_handler_for_mode(self, login_mode: TokenType) -> LoginHandler:
        """Return the login handler for a given mode."""
        if login_mode == "legacy":
            return self._get_legacy_login_token
        if login_mode == "web":
            return self._get_web_login_token
        return self._get_new_login_token

    def _get_web_login_token(
        self, userName: str, password: str
    ) -> dict[str, Any] | None:
        """Get a token from the SEMS+ web login endpoint."""
        return self._get_new_login_token(userName, password, is_web=True)

    def _resolve_login_api_url(
        self,
        json_response: dict[str, Any],
        token_data: dict[str, Any],
        login_mode: TokenType,
        fallback_api_url: str | None,
    ) -> str | None:
        """Resolve API URL from login response with optional fallback."""
        api_url = (
            json_response.get("api")
            if isinstance(json_response.get("api"), str)
            else token_data.get("api")
        )
        if isinstance(api_url, str) and api_url:
            return api_url

        if fallback_api_url is None:
            _LOGGER.error(
                "SEMS %s login response missing api field: keys=%s",
                login_mode,
                list(json_response.keys()),
            )
            return None

        _LOGGER.debug(
            "SEMS %s login response missing api field, falling back to %s",
            login_mode,
            fallback_api_url,
        )
        return fallback_api_url

    def _extract_login_token(
        self,
        json_response: dict[str, Any] | None,
        login_mode: TokenType,
        operation_name: str,
        fallback_api_url: str | None = None,
    ) -> dict[str, Any] | None:
        """Normalize a login response into the token payload expected elsewhere."""
        if json_response is None:
            return None

        code = json_response.get("code")
        if code not in _SuccessCodes:
            self._last_login_rejection_code = str(code)
            _LOGGER.debug(
                "SEMS %s login failed during %s with code %s, msg=%s, description=%s, api=%s, data_type=%s",
                login_mode,
                operation_name,
                code,
                json_response.get("msg"),
                json_response.get("description"),
                json_response.get("api"),
                type(json_response.get("data")).__name__,
            )
            return None

        token_data = json_response.get("data")
        if not isinstance(token_data, dict) or not token_data:
            _LOGGER.error(
                "SEMS %s login response data was missing or invalid: data_type=%s, keys=%s",
                login_mode,
                type(token_data).__name__,
                list(json_response.keys()),
            )
            return None

        api_url = self._resolve_login_api_url(
            json_response,
            token_data,
            login_mode,
            fallback_api_url,
        )
        if api_url is None:
            return None

        token_dict = dict(token_data)
        token_dict["api"] = api_url

        if not token_dict.get("token"):
            _LOGGER.warning(
                "SEMS %s login response missing valid token field - incomplete token received",
                login_mode,
            )
            return None

        _LOGGER.debug(
            "SEMS - API Token received via %s login: %s",
            login_mode,
            redact_for_log(token_dict),
        )

        if login_mode != "web":
            self._preferred_login_mode = login_mode

        return token_dict

    def _get_legacy_login_token(
        self, userName: str, password: str
    ) -> dict[str, Any] | None:
        """Get a token from the legacy SEMS login endpoint."""
        _LOGGER.debug("SEMS - Trying legacy login")
        login_data = json.dumps({"account": userName, "pwd": password})
        json_response = self._make_http_request(
            OLD_LOGIN_URL,
            _DefaultHeaders,
            data=login_data,
            operation_name="legacy login API call",
            validate_code=False,
        )
        return self._extract_login_token(
            json_response, "legacy", "legacy login API call"
        )

    def _get_new_login_token(
        self, userName: str, password: str, is_web: bool = False
    ) -> dict[str, Any] | None:
        """Get a token from the SEMS+ login endpoint."""
        login_mode: TokenType = "web" if is_web else "new"
        operation_name = (
            "SEMS+ Web login API call" if is_web else "SEMS+ login API call"
        )
        _LOGGER.debug("SEMS - Trying %s", operation_name)
        login_data = {
            "account": userName,
            "pwd": self._hash_password_for_new_login(password),
            "agreement": 1,
            "isChinese": False,
            "isLocal": False,
        }
        headers = _NewLoginHeaders
        if is_web:
            headers = {
                **_NewSEMSPlusWebLoginHeaders,
                "X-Signature": self._generate_signature({}),
                "User-Agent": _SemsPlusWebUserAgent,
            }

        json_response = self._make_http_request(
            NEW_LOGIN_URL,
            headers,
            json_data=login_data,
            operation_name=operation_name,
            validate_code=False,
        )
        return self._extract_login_token(
            json_response,
            login_mode,
            operation_name,
            _NewLoginFallbackApi,
        )

    def getLoginToken(self, userName: str, password: str) -> dict[str, Any] | None:
        """Get the login token for the SEMS API."""
        tried_login_modes: list[TokenType] = []
        for login_mode in self._get_login_mode_order():
            tried_login_modes.append(login_mode)
            try:
                token = self._login_handler_for_mode(login_mode)(userName, password)
            except SemsRateLimitedError:
                raise
            except (requests.RequestException, ValueError, KeyError) as exception:
                _LOGGER.warning(
                    "SEMS %s login failed; trying the next authentication method: %s",
                    login_mode,
                    exception,
                )
                continue

            if token is not None:
                # Keep preferred mode in sync even when login helpers are mocked in tests.
                self._preferred_login_mode = login_mode
                return token

        _LOGGER.warning(
            "Unable to authenticate with SEMS API; tried authentication methods: %s",
            ", ".join(tried_login_modes),
        )
        return None

    def _make_api_call(
        self,
        url_part: str,
        data: str | None = None,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        operation_name: str = "API call",
        method: str = "POST",
        is_web: bool = False,
        retry_on_api_error: bool = True,
        token_type: TokenType | None = None,
    ) -> Any | None:
        """Make an API call, re-authenticating at most once for a rejected token.

        Only codes for an expired or replaced session trigger the re-login.
        Other API error codes raise OutOfRetries without logging in again.
        """
        _LOGGER.debug("SEMS - Making %s", operation_name)
        if maxTokenRetries <= 0:
            _LOGGER.debug("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        if token_type is None:
            token_type = "web" if is_web else "legacy"

        may_reauthenticate = maxTokenRetries > 1
        stale_generation: int | None = None
        while True:
            api_url, headers, generation = self._get_authenticated_request_context(
                url_part,
                renewToken,
                operation_name,
                token_type=token_type,
                stale_generation=stale_generation,
            )

            try:
                json_response: dict[str, Any] | None = self._make_http_request(
                    api_url,
                    headers,
                    data=data,
                    method=method,
                    operation_name=operation_name,
                    validate_code=retry_on_api_error,
                )
            except SemsAuthExpiredError as exception:
                if may_reauthenticate:
                    may_reauthenticate = False
                    renewToken = False
                    stale_generation = generation
                    continue
                self._log_session_failure(operation_name, exception)
                raise OutOfRetries(str(exception)) from exception
            except SemsRateLimitedError as exception:
                _LOGGER.debug(
                    "SEMS - Propagating rate limit from %s to coordinator: "
                    "retry_after=%s",
                    operation_name,
                    exception.retry_after,
                )
                raise
            except SemsPermissionError:
                raise
            except (requests.RequestException, ValueError, KeyError) as exception:
                # _make_http_request already logged the failure.
                _LOGGER.debug("Unable to complete %s: %s", operation_name, exception)
                return None

            if json_response is None:
                # An API error that is not about the token; a new login would
                # not help.
                raise OutOfRetries(f"{operation_name} returned an API error")

            self._session_failure_logged = False
            if is_web and not self._is_sensitive_operation(operation_name):
                _LOGGER.debug(
                    "SEMS - %s response data: %s",
                    operation_name,
                    redact_for_log(json_response.get("data")),
                )

            return json_response.get("data", {}) if is_web else json_response["data"]

    def _log_session_failure(self, operation_name: str, err: Exception) -> None:
        """Warn once while SEMS keeps rejecting fresh tokens."""
        if self._session_failure_logged:
            _LOGGER.debug("%s failed after re-authentication: %s", operation_name, err)
            return
        self._session_failure_logged = True
        _LOGGER.warning(
            "SEMS rejected the session for %s even after re-authentication: %s. "
            "Further failures are logged at debug level until a request succeeds.",
            operation_name,
            err,
        )

    def getPowerStationIds(
        self, renewToken: bool = False, maxTokenRetries: int = 2
    ) -> list[str]:
        """Get power station ids from the SEMS+ Web API."""
        result = self._make_api_call(
            _WEB_STATION_LIST_ENDPOINT.url_part,
            data=json.dumps({"current": 1, "size": 100}),
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getPowerStationIds API call",
            is_web=True,
            token_type=_WEB_STATION_LIST_ENDPOINT.token_type,
        )
        if not isinstance(result, dict):
            return []
        return [
            station["id"]
            for station in result.get("dataList", [])
            if isinstance(station, dict) and isinstance(station.get("id"), str)
        ]

    def getData(
        self,
        powerStationId: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        include_last_month: bool = False,
    ) -> dict[str, Any]:
        """Get the latest data from the SEMS+ Web API."""
        return self.getWebData(
            powerStationId,
            renewToken,
            maxTokenRetries,
            include_last_month=include_last_month,
        )

    def _get_web_statistics(
        self,
        power_station_id: str,
        dimension: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, list[float]] | None:
        cache_key = f"{power_station_id}:{dimension}:{start.date()}:{end.date()}"
        refresh = (
            _WEB_STATISTICS_REFRESH_SECONDS
            if dimension == "day"
            else _WEB_HISTORIC_STATISTICS_REFRESH_SECONDS
        )
        cached = self._get_web_cache_entry(cache_key)
        if cached and time.monotonic() - cached[0] < refresh:
            return cached[1]
        if self._recently_failed(cache_key):
            return cached[1] if cached else None

        try:
            response = self._make_api_call(
                _WEB_STATION_STATISTICS_ENDPOINT.url_part,
                data=json.dumps(
                    {
                        "stationId": power_station_id,
                        "isReport": False,
                        "items": _WEB_STATISTICS_ITEMS,
                        "dimension": dimension,
                        "startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
                        "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                ),
                operation_name="getWebStationStatistics API call",
                is_web=True,
                token_type=_WEB_STATION_STATISTICS_ENDPOINT.token_type,
            )
        except OutOfRetries as err:
            _LOGGER.debug("SEMS %s statistics unavailable: %s", dimension, err)
            response = None
        if not isinstance(response, dict):
            self._remember_failure(cache_key)
            return cached[1] if cached else None

        parsed: dict[str, list[float]] = {}
        for item_data in response.get("dataList", []):
            if not isinstance(item_data, dict):
                continue
            item = item_data.get("item")
            if not isinstance(item, str):
                continue
            values: list[float] = []
            for statistic in item_data.get("statisticsList", []):
                if not isinstance(statistic, dict):
                    continue
                value = statistic.get("val")
                if not isinstance(value, (int, float, str)):
                    continue
                try:
                    numeric_value = float(value)
                except TypeError, ValueError:
                    continue
                if math.isfinite(numeric_value):
                    values.append(numeric_value)
            if values:
                parsed[item] = values
        for summary_key, item in (
            ("production", "proSystemTotalStats"),
            ("proConsum", "proConsumStats"),
            ("proGrid", "proGridStats"),
            ("proPurchase", "proPurchaseStats"),
            ("proSelfConsum", "proSelfConsumStats"),
            ("proDischar", "proDischarStats"),
            ("proChar", "proCharStats"),
        ):
            value = response.get(summary_key)
            if not isinstance(value, (int, float, str)):
                continue
            try:
                numeric_value = float(value)
            except TypeError, ValueError:
                continue
            if math.isfinite(numeric_value) and item not in parsed:
                parsed[item] = [numeric_value]
        for summary_key in _WEB_STATISTICS_RATE_MAP:
            value = response.get(summary_key)
            if not isinstance(value, (int, float, str)):
                continue
            try:
                numeric_value = float(value)
            except TypeError, ValueError:
                continue
            if math.isfinite(numeric_value):
                parsed[summary_key] = [numeric_value]

        response_dates: list[str] = []
        for item_data in response.get("dataList", []):
            if not isinstance(item_data, dict):
                continue
            for statistic in item_data.get("statisticsList", []):
                if not isinstance(statistic, dict):
                    continue
                date = statistic.get("date")
                if isinstance(date, str):
                    response_dates.append(date)
        _LOGGER.debug(
            "SEMS - getWebStationStatistics response: dimension=%s "
            "requested=%s..%s items=%s points=%s dates=%s..%s",
            dimension,
            start.date(),
            end.date(),
            sorted(parsed),
            sum(len(values) for values in parsed.values()),
            min(response_dates) if response_dates else None,
            max(response_dates) if response_dates else None,
        )
        self._set_web_cache_entry(cache_key, (time.monotonic(), parsed))
        return parsed

    def _get_web_cache_entry(self, key: str) -> tuple[float, Any] | None:
        """Read one response-cache entry safely across executor threads."""
        with self._web_cache_lock:
            return self._web_cache.get(key)

    def _set_web_cache_entry(self, key: str, value: tuple[float, Any]) -> None:
        """Write one response-cache entry safely across executor threads."""
        with self._web_cache_lock:
            self._web_cache[key] = value

    def _prune_web_cache(self) -> None:
        """Drop cache entries that have not been refreshed for a long time."""
        now = time.monotonic()
        with self._web_cache_lock:
            if now - self._web_cache_pruned_at < _WEB_CACHE_PRUNE_INTERVAL_SECONDS:
                return
            self._web_cache_pruned_at = now
            for key, entry in list(self._web_cache.items()):
                if (
                    not key.startswith(_WEB_CACHE_PERSISTENT_PREFIXES)
                    and now - entry[0] > _WEB_CACHE_MAX_AGE_SECONDS
                ):
                    self._web_cache.pop(key, None)

    def _recently_failed(self, cache_key: str) -> bool:
        """Return whether a request failed too recently to retry it."""
        failed = self._get_web_cache_entry(f"failed:{cache_key}")
        return bool(
            failed and time.monotonic() - failed[0] < _WEB_FAILED_REQUEST_RETRY_SECONDS
        )

    def _remember_failure(self, cache_key: str) -> None:
        """Delay the next attempt of a failed optional request."""
        self._set_web_cache_entry(f"failed:{cache_key}", (time.monotonic(), None))

    def _get_web_energy_statistics(
        self,
        power_station_id: str,
        inverters: list[dict[str, Any]],
        include_last_month: bool = False,
    ) -> tuple[dict[str, Any], dict[str, float], str | None, float | None] | None:
        """Return chart and lifetime statistics without making them coordinator-critical."""
        try:
            now = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            current_year = now.year
            charts: dict[str, Any] = {}
            totals: dict[str, float] = {}
            currency: str | None = None
            last_month_pv: float | None = None

            month_start = now.replace(day=1)
            previous_month_end = month_start - timedelta(seconds=1)
            previous_month_start = previous_month_end.replace(day=1)
            statistic_ranges = [
                ("day", now, now + timedelta(days=1) - timedelta(seconds=1)),
                ("day", month_start, now + timedelta(days=1) - timedelta(seconds=1)),
            ]
            if include_last_month:
                statistic_ranges.append(
                    ("day", previous_month_start, previous_month_end)
                )

            install_year: int | None = None
            for inverter in inverters:
                add_time = inverter.get("invert_full", {}).get("addTime")
                try:
                    year = datetime.fromtimestamp(int(add_time) / 1000).year
                    install_year = (
                        year if install_year is None else min(install_year, year)
                    )
                except TypeError, ValueError, OSError, OverflowError:
                    continue
            if install_year is None:
                install_year = _WEB_STATISTICS_EARLIEST_YEAR
            with ThreadPoolExecutor(max_workers=_MaxConcurrentRequests) as executor:
                production_future = executor.submit(
                    self._get_web_production,
                    power_station_id,
                    now,
                    now + timedelta(days=1) - timedelta(seconds=1),
                )
                statistics_futures = [
                    executor.submit(
                        self._get_web_statistics,
                        power_station_id,
                        dimension,
                        start,
                        end,
                    )
                    for dimension, start, end in statistic_ranges
                ]
                historic_statistics_future = executor.submit(
                    self._get_web_statistics,
                    power_station_id,
                    "year",
                    datetime(install_year, 1, 1),
                    datetime(current_year + 1, 1, 1) - timedelta(seconds=1),
                )

                production_data = production_future.result()
                statistic_data = [future.result() for future in statistics_futures]
                historic_statistics = historic_statistics_future.result()

            if production_data and isinstance(production_data.get("currency"), str):
                currency = production_data.get("currency")
            for (_dimension, start, _), data in zip(
                statistic_ranges, statistic_data, strict=True
            ):
                if not data:
                    continue
                if start == now:
                    # Only map series the station reports; a missing series must
                    # not become 0 and hide smart-meter counters.
                    charts.update(
                        {
                            target: sum(data[source])
                            for source, target in _WEB_STATISTICS_KEY_MAP.items()
                            if data.get(source)
                        }
                    )
                    if production_data:
                        for source, target in _WEB_STATISTICS_KEY_MAP.items():
                            if target not in charts and isinstance(
                                production_data.get(source), (int, float)
                            ):
                                charts[target] = production_data[source]
                    charts.update(
                        {
                            target: sum(data.get(source, [])) / 100
                            for source, target in _WEB_STATISTICS_RATE_MAP.items()
                            if data.get(source)
                        }
                    )
                elif start == previous_month_start:
                    last_month_pv = sum(data.get("proSystemTotalStats", []))

            if historic_statistics:
                for item, values in historic_statistics.items():
                    mapped_target = _WEB_STATISTICS_KEY_MAP.get(item)
                    if mapped_target is not None:
                        totals[mapped_target] = sum(values)
            self_use = totals.get("selfUseOfPv")
            consumption = totals.get("consumptionOfLoad")
            production_total = totals.get("sum")
            if self_use is not None and consumption:
                totals["contributingRate"] = self_use / consumption
            if self_use is not None and production_total:
                totals["selfUseRate"] = self_use / production_total

            return charts, totals, currency, last_month_pv
        except (OutOfRetries, SemsRateLimitedError) as err:
            _LOGGER.debug("SEMS station statistics unavailable: %s", err)
            return None

    def _get_web_production(
        self, power_station_id: str, start: datetime, end: datetime
    ) -> dict[str, Any] | None:
        """Get optional flat station production totals and currency."""
        cache_key = f"production:{power_station_id}:{start.date()}:{end.date()}"
        cached = self._get_web_cache_entry(cache_key)
        if cached and time.monotonic() - cached[0] < _WEB_STATISTICS_REFRESH_SECONDS:
            return cached[1]
        if self._recently_failed(cache_key):
            return cached[1] if cached else None

        try:
            response = self._make_api_call(
                _WEB_STATION_PRODUCTION_ENDPOINT.url_part,
                data=json.dumps(
                    {
                        "stationId": power_station_id,
                        "items": [
                            "proConsumStats",
                            "proGridStats",
                            "proPurchaseStats",
                            "profitGridStats",
                            "profitProStats",
                            "proSystemTotalStats",
                        ],
                        "dimension": "day",
                        "isReport": False,
                        "startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
                        "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                ),
                operation_name="getWebStationProduction API call",
                is_web=True,
                token_type=_WEB_STATION_PRODUCTION_ENDPOINT.token_type,
            )
        except OutOfRetries as err:
            _LOGGER.debug("SEMS station production unavailable: %s", err)
            response = None
        if not isinstance(response, dict):
            self._remember_failure(cache_key)
            return cached[1] if cached else None
        self._set_web_cache_entry(cache_key, (time.monotonic(), response))
        return response

    def getWebData(
        self,
        powerStationId: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        include_last_month: bool = False,
    ) -> dict[str, Any]:
        """Build the legacy coordinator shape from SEMS+ Web responses."""
        self._prune_web_cache()
        inverters: list[dict[str, Any]] = []
        smart_meters: list[dict[str, Any]] = []
        ev_chargers: dict[str, dict[str, Any]] = {}
        unavailable_inverter_sources: dict[str, set[str]] = {}
        unavailable_homekit_sources: set[str] = set()
        device_cache_key = f"devices:{powerStationId}"
        cached_devices = self._get_web_cache_entry(device_cache_key)
        device_inventory_unavailable = False
        try:
            devices = self.getWebInverterDevices(
                powerStationId, renewToken, maxTokenRetries
            )
        except OutOfRetries, SemsRateLimitedError:
            if (
                cached_devices is None
                or time.monotonic() - cached_devices[0]
                >= _WEB_DEVICE_LIST_CACHE_SECONDS
                or not isinstance(cached_devices[1], list)
                or not cached_devices[1]
            ):
                raise
            _LOGGER.debug("SEMS+ device discovery unavailable; using recent inventory")
            devices = [
                {key: value for key, value in device.items() if key != "status"}
                for device in cached_devices[1]
                if isinstance(device, dict)
            ]
            device_inventory_unavailable = True
        else:
            self._set_web_cache_entry(device_cache_key, (time.monotonic(), devices))

        for device in devices:
            serial_number = device.get("sn")
            if not isinstance(serial_number, str):
                continue
            device_type = device.get("deviceType", "INVERTER")
            if not isinstance(device_type, str):
                device_type = "INVERTER"
            device_data = dict(device)
            if device_type == "EV_CHARGER":
                ev_chargers[serial_number] = self.getWebEvCharger(
                    powerStationId, device_data, renewToken, maxTokenRetries
                )
                continue
            if (
                device_inventory_unavailable
                and device_type in _WEB_INVERTER_ENTITY_TYPES
            ):
                unavailable_inverter_sources.setdefault(serial_number, set()).add(
                    "device_status"
                )
            # Dongles have status, but no useful telemetry or counters. Avoid
            # making unsupported requests for them while preserving their
            # device/entity entry.
            if device_type != "DONGLE":
                unavailable_sources: set[str] = set()
                try:
                    telemetry = self.getWebInverterTelemetry(
                        powerStationId,
                        serial_number,
                        renewToken,
                        maxTokenRetries,
                        device_type=device_type,
                    )
                    device_data.update(telemetry)
                except SemsPermissionError as err:
                    _LOGGER.warning(
                        "SEMS+ denied telemetry access for inverter %s: %s. "
                        "Check the GoodWe account or plant permissions.",
                        serial_number,
                        err,
                    )
                    unavailable_sources.add("telemetry")
                except (OutOfRetries, SemsRateLimitedError) as err:
                    _LOGGER.debug(
                        "SEMS+ telemetry unavailable for inverter %s: %s",
                        serial_number,
                        err,
                    )
                    unavailable_sources.add("telemetry")
                if "pac" not in device_data and device_data.get("status") in (-1, 0):
                    device_data["pac"] = 0
                try:
                    device_data.update(
                        self.getWebInverterTelecounting(
                            powerStationId,
                            serial_number,
                            renewToken,
                            maxTokenRetries,
                            device_type=device_type,
                        )
                    )
                except SemsPermissionError as err:
                    _LOGGER.warning(
                        "SEMS+ denied counter access for inverter %s: %s. "
                        "Check the GoodWe account or plant permissions.",
                        serial_number,
                        err,
                    )
                    unavailable_sources.add("counters")
                except (OutOfRetries, SemsRateLimitedError) as err:
                    _LOGGER.debug(
                        "SEMS+ counters unavailable for inverter %s: %s",
                        serial_number,
                        err,
                    )
                    unavailable_sources.add("counters")
                if unavailable_sources:
                    if device_type == "SMART_METER":
                        unavailable_homekit_sources.update(unavailable_sources)
                    else:
                        unavailable_inverter_sources.setdefault(
                            serial_number, set()
                        ).update(unavailable_sources)
            if device_type == "BATTERY_RACK":
                battery_data = {
                    key: device_data.pop(key)
                    for key in (
                        "pbattery",
                        "vbattery",
                        "ibattery",
                        "soc",
                        "soh",
                        "bms_temperature",
                        "bms_charge_i_max",
                        "bms_discharge_i_max",
                    )
                    if key in device_data
                }
                if battery_data:
                    device_data["battery_count"] = 1
                    device_data["more_batterys"] = [battery_data]
            device_data.setdefault("powerstation_id", powerStationId)
            if device_type == "SMART_METER":
                smart_meters.append(device_data)
                continue
            if device_type not in _WEB_INVERTER_ENTITY_TYPES:
                continue
            if "model_type" not in device_data:
                name = device_data.get("name")
                subtype = device_data.get("subtype")
                device_data["model_type"] = (
                    f"{name} ({subtype})"
                    if name and subtype
                    else name or subtype or "unknown"
                )
            inverters.append({"invert_full": device_data})

        real_inverters = [
            inverter
            for inverter in inverters
            if inverter["invert_full"].get("deviceType") in _WEB_REAL_INVERTER_TYPES
        ]
        result: dict[str, Any] = {"inverter": inverters}
        if ev_chargers:
            result["ev_chargers"] = ev_chargers
        try:
            flow = self.getWebStationFlow(powerStationId, renewToken, maxTokenRetries)
        except (OutOfRetries, SemsRateLimitedError, SemsPermissionError) as err:
            _LOGGER.debug("SEMS station flow unavailable: %s", err)
            flow = {}
            for charger in ev_chargers.values():
                charger["unavailable_sources"].add("flow")
        if len(ev_chargers) == 1 and flow.get("pEvChar") is not None:
            # Station flow reports the (total) EV charging power in kW; it can
            # only be attributed to a charger when the station has one.
            try:
                next(iter(ev_chargers.values()))["charging_power"] = (
                    abs(float(flow["pEvChar"])) * 1000
                )
            except TypeError, ValueError:
                _LOGGER.debug("SEMS station flow has an invalid pEvChar value")
        if flow:
            if (
                not smart_meters
                and len(real_inverters) == 1
                and (grid_power := flow.get("pGrid")) is not None
            ):
                try:
                    for inverter in real_inverters:
                        inverter["invert_full"]["pmeter"] = float(grid_power) * 1000
                except TypeError, ValueError:
                    _LOGGER.debug("SEMS station flow has an invalid pGrid value")
            if len(real_inverters) == 1:
                inverter_full = real_inverters[0]["invert_full"]
                if (
                    "pac" not in inverter_full
                    and (solar_power := flow.get("pAc")) is not None
                ):
                    try:
                        inverter_full["pac"] = float(solar_power) * 1000
                    except TypeError, ValueError:
                        _LOGGER.debug("SEMS station flow has an invalid pAc value")
            result.update(
                {
                    "hasPowerflow": True,
                    "powerflow": self._normalize_web_homekit_data(
                        flow, smart_meters[0] if smart_meters else None
                    ),
                    "hasEnergeStatisticsCharts": True,
                }
            )
        storage_cabinets: dict[str, list[dict[str, Any]]] = {}
        for inverter in inverters:
            inverter_full = inverter["invert_full"]
            if not (
                inverter_full.get("deviceType") == "ENERGY_STORAGE_INTEGRATED_CABINET"
                or inverter_full.get("subtype") == "store"
            ):
                continue
            serial_number = inverter_full["sn"]
            cache_key = f"cabinets:{powerStationId}:{serial_number}"
            cached = self._get_web_cache_entry(cache_key)
            if (
                cached
                and time.monotonic() - cached[0] < _WEB_RELATED_DEVICES_REFRESH_SECONDS
            ):
                cabinets = cached[1]
            else:
                try:
                    cabinets = self.getEnergyStorageIntegratedCabinets(
                        powerStationId, serial_number, renewToken, maxTokenRetries
                    )
                except (
                    OutOfRetries,
                    SemsPermissionError,
                    SemsRateLimitedError,
                ) as err:
                    _LOGGER.debug(
                        "SEMS related storage devices unavailable for %s: %s",
                        serial_number,
                        err,
                    )
                    cabinets = []
                if cabinets:
                    self._set_web_cache_entry(cache_key, (time.monotonic(), cabinets))
                elif cached:
                    cabinets = cached[1]
            storage_cabinets[serial_number] = cabinets
            batteries = self._get_web_batteries(powerStationId, cabinets)
            if batteries:
                inverter_full["battery_count"] = len(batteries)
                inverter_full["more_batterys"] = batteries
        if any(storage_cabinets.values()):
            result["info"] = {"is_stored": True}
            result["_energy_storage_cabinets"] = storage_cabinets
        statistics = self._get_web_energy_statistics(
            powerStationId,
            inverters,
            include_last_month=include_last_month,
        )
        charts, totals, currency, last_month_pv = (
            statistics if statistics is not None else ({}, {}, None, None)
        )
        if smart_meters:
            # The smart meter measures grid import/export directly; prefer its
            # counters over station statistics, which may omit or zero them.
            for source, stats, target in (
                ("proPurchaseStatsToday", charts, "buy"),
                ("proGridStatsToday", charts, "sell"),
                ("proPurchaseStatsTotal", totals, "buy"),
                ("proGridStatsTotal", totals, "sell"),
            ):
                values = [
                    meter[source]
                    for meter in smart_meters
                    if isinstance(meter.get(source), (int, float))
                ]
                if values:
                    stats[target] = sum(values)
        if charts or totals:
            result["hasEnergeStatisticsCharts"] = True
            result["energeStatisticsCharts"] = charts
            result["energeStatisticsTotals"] = totals
        if last_month_pv is not None and len(real_inverters) == 1:
            invert_full = real_inverters[0].get("invert_full")
            if isinstance(invert_full, dict):
                invert_full["lastmonthetotle"] = last_month_pv
        if currency is not None:
            result["kpi"] = {"currency": currency}
        if unavailable_inverter_sources or unavailable_homekit_sources:
            result["unavailable_data_sources"] = {
                "inverters": unavailable_inverter_sources,
                "homekit": unavailable_homekit_sources,
            }
        return result

    def getWebEvCharger(
        self,
        powerStationId: str,
        device: dict[str, Any],
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> dict[str, Any]:
        """Get EV charger telemetry, counters, mode settings, and charge state.

        Each request is optional so one failing charger endpoint does not hide
        the others or the station's inverter data. Failed requests are listed
        in `unavailable_sources` so the entities they feed report unavailable.
        """
        serial_number = device["sn"]
        unavailable_sources: set[str] = set()
        charger: dict[str, Any] = {
            **device,
            "powerstation_id": powerStationId,
            "factors": {},
            "mode_info": {},
            "charge_log": {},
            "unavailable_sources": unavailable_sources,
        }
        for endpoint, name in (
            (_WEB_TELEMETRY_ENDPOINT, "telemetry"),
            (_WEB_TELECOUNTING_ENDPOINT, "telecounting"),
        ):
            try:
                result = self._make_api_call(
                    f"{endpoint.url_part.format(serial_number=serial_number)}"
                    f"?deviceType=EV_CHARGER&pwId={powerStationId}",
                    method="GET",
                    renewToken=renewToken,
                    maxTokenRetries=maxTokenRetries,
                    operation_name=f"getWebEvCharger {name} API call",
                    is_web=True,
                    token_type=endpoint.token_type,
                )
            except (OutOfRetries, SemsRateLimitedError, SemsPermissionError) as err:
                _LOGGER.debug("SEMS EV charger %s unavailable: %s", name, err)
                unavailable_sources.add(name)
                continue
            charger["factors"].update(
                {
                    code: {**factor, "source": name}
                    for code, factor in self._web_factors_with_units(
                        result if isinstance(result, list) else None
                    ).items()
                }
            )

        for key, url_part, operation_name in (
            (
                "mode_info",
                _WEB_EV_CHARGER_MODE_INFO_ENDPOINT.url_part.format(
                    serial_number=serial_number
                ),
                "getWebEvChargerModeInfo API call",
            ),
            (
                "last_charge",
                f"{_WEB_EV_CHARGER_LAST_CHARGE_ENDPOINT.url_part}"
                f"?chargeSn={serial_number}&pwId={powerStationId}",
                "getWebEvChargerLastCharge API call",
            ),
        ):
            try:
                result = self._make_api_call(
                    url_part,
                    method="GET",
                    renewToken=renewToken,
                    maxTokenRetries=maxTokenRetries,
                    operation_name=operation_name,
                    is_web=True,
                    token_type="web",
                )
            except (OutOfRetries, SemsRateLimitedError, SemsPermissionError) as err:
                _LOGGER.debug("SEMS EV charger %s unavailable: %s", key, err)
                unavailable_sources.add(key)
                continue
            if not isinstance(result, dict):
                continue
            if key == "last_charge":
                charge_log = result.get("chargeLog")
                charger["charge_log"] = (
                    charge_log if isinstance(charge_log, dict) else {}
                )
            else:
                charger[key] = result

        # Current charge mode and "More Control" settings (Web UI evChargeInfo).
        product_model = charger["mode_info"].get("productModel")
        charger["detail"] = {}
        if product_model:
            try:
                detail = self._make_api_call(
                    _WEB_EV_CHARGER_COMMAND_URL_PART.format(command="detail"),
                    data=json.dumps(
                        {"sn": serial_number, "productModel": product_model}
                    ),
                    method="POST",
                    renewToken=renewToken,
                    maxTokenRetries=maxTokenRetries,
                    operation_name="getWebEvChargerDetail API call",
                    is_web=True,
                    token_type="web",
                )
            except (OutOfRetries, SemsRateLimitedError, SemsPermissionError) as err:
                _LOGGER.debug("SEMS EV charger detail unavailable: %s", err)
                unavailable_sources.add("detail")
            else:
                if isinstance(detail, dict):
                    charger["detail"] = detail
        elif "mode_info" in unavailable_sources:
            # Without the model the settings can't be read either.
            unavailable_sources.add("detail")
        return charger

    @staticmethod
    def _web_factors_with_units(
        response: list[dict[str, Any]] | None,
    ) -> dict[str, dict[str, Any]]:
        """Return numeric SEMS+ factors with their unit and alias by code."""
        factors: dict[str, dict[str, Any]] = {}
        for group in response or []:
            if not isinstance(group, dict):
                continue
            for factor in group.get("factors", []):
                if not isinstance(factor, dict):
                    continue
                code = factor.get("code")
                try:
                    value = float(factor["data"])
                except KeyError, TypeError, ValueError:
                    continue
                if not isinstance(code, str):
                    continue
                factors[code] = {
                    "value": value,
                    "unit": factor.get("unit") or None,
                    "alias": factor.get("alias") or code,
                }
        return factors

    def _send_ev_charger_command(self, command: str, payload: dict[str, Any]) -> bool:
        """Send an EV charger control command through SEMS+ Web."""
        return (
            self._make_api_call(
                _WEB_EV_CHARGER_COMMAND_URL_PART.format(command=command),
                method="POST",
                data=json.dumps(payload),
                operation_name=f"EV charger {command} API call",
                is_web=True,
                token_type="web",
            )
            is not None
        )

    def startEvCharging(
        self, plant_id: str, serial_number: str, product_model: str, mode: int
    ) -> bool:
        """Start charging on an EV charger."""
        return self._send_ev_charger_command(
            "startCharge",
            {
                "sn": serial_number,
                "plantId": plant_id,
                "productModel": product_model,
                "mode": mode,
            },
        )

    def stopEvCharging(
        self, plant_id: str, serial_number: str, product_model: str, mode: int
    ) -> bool:
        """Stop charging on an EV charger."""
        return self._send_ev_charger_command(
            "stopCharge",
            {
                "sn": serial_number,
                "plantId": plant_id,
                "productModel": product_model,
                "mode": mode,
            },
        )

    def setEvChargeMode(
        self,
        plant_id: str,
        serial_number: str,
        product_model: str,
        mode: int,
        detail: dict[str, Any] | None = None,
    ) -> bool:
        """Set the EV charge mode (0 fast, 1 PV, 2 PV and battery).

        Like the Web UI, fast mode resends the configured maximum power.
        """
        payload: dict[str, Any] = {
            "mode": mode,
            "sn": serial_number,
            "plantId": plant_id,
            "productModel": product_model,
        }
        if mode == 0 and detail and detail.get("chargeMaxPower") is not None:
            payload["chargeMaxPower"] = detail["chargeMaxPower"]
            payload["chargePowerSetted"] = detail.get("chargePowerSetted") or 0
        return self._send_ev_charger_command("set-mode", payload)

    def setEvChargerConfig(
        self,
        plant_id: str,
        serial_number: str,
        product_model: str,
        field: str,
        value: float | int,
    ) -> bool:
        """Change one EV charger "More Control" setting (Web UI set-config)."""
        return self._send_ev_charger_command(
            "set-config",
            {
                "sn": serial_number,
                "plantId": plant_id,
                "productModel": product_model,
                field: value,
            },
        )

    def getWebStationFlow(
        self,
        powerStationId: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> dict[str, Any]:
        """Get station power-flow data from SEMS+ Web."""
        result = self._make_api_call(
            f"{_WEB_STATION_FLOW_ENDPOINT.url_part}?stationId={powerStationId}",
            method="GET",
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getWebStationFlow API call",
            is_web=True,
            token_type=_WEB_STATION_FLOW_ENDPOINT.token_type,
        )
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _normalize_web_homekit_data(
        flow: dict[str, Any], smart_meter: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Map SEMS+ flow and smart-meter counters to HomeKit fields."""
        # SEMS+ can report null or non-numeric flow values; skip them instead
        # of failing the whole refresh.
        grid_power = SemsApi._numeric_web_factor(flow, "pGrid")
        grid_status = -1 if grid_power is not None and grid_power > 0 else 1
        homekit: dict[str, Any] = {
            "sn": smart_meter.get("sn") if smart_meter else None,
            "gridStatus": grid_status,
            "loadStatus": grid_status,
            # Marks SEMS+ Web flow data, whose load is always the consumption.
            "isSemsPlusFlow": True,
        }
        for source, target in (
            ("pSystem" if "pSystem" in flow else "pAc", "pv"),
            ("pGrid", "grid"),
            ("pConsum", "load"),
            ("pBat", "battery"),
        ):
            if (value := SemsApi._numeric_web_factor(flow, source)) is not None:
                homekit[target] = value * 1000
        if "load" in homekit:
            # Household consumption is never negative; SEMS+ can report pConsum
            # with a flow-direction sign.
            homekit["load"] = abs(homekit["load"])
        if (soc := flow.get("soc")) is not None:
            homekit["soc"] = soc
        if "battery" in homekit:
            battery_value = homekit["battery"]
            battery_status = -1 if battery_value > 0 else 1
            battery_magnitude = abs(battery_value)
            homekit["battery"] = battery_magnitude
            homekit["batteryStatus"] = battery_status
            homekit["bettery"] = battery_magnitude
            homekit["betteryStatus"] = battery_status
        if smart_meter:
            homekit.update(
                {
                    key: value
                    for key, value in smart_meter.items()
                    if key.startswith("meter_")
                }
            )

        for source, target in (
            ("proPurchaseStatsToday", "Charts_buy"),
            ("proGridStatsToday", "Charts_sell"),
            ("proPurchaseStatsTotal", "Totals_buy"),
            ("proGridStatsTotal", "Totals_sell"),
        ):
            if smart_meter and (value := smart_meter.get(source)) is not None:
                homekit[target] = value

        homekit["hasEnergeStatisticsCharts"] = any(
            key.startswith(("Charts_", "Totals_")) for key in homekit
        )
        return homekit

    @staticmethod
    def _flatten_web_factors(
        response: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Flatten SEMS+ factor groups by factor code."""
        factors: dict[str, Any] = {}
        for group in response or []:
            if not isinstance(group, dict):
                continue
            for factor in group.get("factors", []):
                if not isinstance(factor, dict) or factor.get("data") is None:
                    continue
                code = factor.get("code")
                if isinstance(code, str):
                    factors[code] = factor["data"]
        return factors

    @staticmethod
    def _numeric_web_factor(factors: dict[str, Any], code: str) -> float | None:
        """Return a numeric SEMS+ factor, if present and valid."""
        value = factors.get(code)
        if value is None:
            return None
        try:
            return float(value)
        except TypeError, ValueError:
            return None

    def getWebInverterDevices(
        self, powerStationId: str, renewToken: bool = False, maxTokenRetries: int = 2
    ) -> list[dict[str, Any]]:
        """Discover inverter devices through the SEMS+ Web API."""
        result = self._make_api_call(
            f"{_WEB_DEVICE_STATUS_ENDPOINT.url_part}?stationId={powerStationId}",
            method="GET",
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getWebInverterDevices API call",
            is_web=True,
            token_type=_WEB_DEVICE_STATUS_ENDPOINT.token_type,
        )
        if result is None:
            raise OutOfRetries("SEMS+ device discovery request failed")
        devices: list[dict[str, Any]] = []
        for device_group in (
            result.get("deviceDetailList", []) if isinstance(result, dict) else []
        ):
            if not isinstance(device_group, dict):
                continue
            device_type = device_group.get("deviceType")
            if device_type not in _SUPPORTED_WEB_DEVICE_TYPES:
                continue
            for status_group in device_group.get("statusDetailList", []):
                if not isinstance(status_group, dict):
                    continue
                detail_map = status_group.get("detailMap", {})
                if not isinstance(detail_map, dict):
                    continue
                for serial_number in status_group.get("snList", []):
                    if not isinstance(serial_number, str):
                        continue
                    detail = detail_map.get(serial_number, {})
                    if isinstance(detail, dict):
                        devices.append(
                            {
                                **detail,
                                "deviceType": device_type,
                                "status": status_group.get("status"),
                            }
                        )
        return devices

    def getWebInverterTelemetry(
        self,
        powerStationId: str,
        serialNumber: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        device_type: str = "INVERTER",
    ) -> dict[str, Any]:
        """Get normalized live inverter telemetry from SEMS+ Web."""
        result = self._make_api_call(
            f"{_WEB_TELEMETRY_ENDPOINT.url_part.format(serial_number=serialNumber)}"
            f"?deviceType={device_type}&pwId={powerStationId}",
            method="GET",
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getWebInverterTelemetry API call",
            is_web=True,
            token_type=_WEB_TELEMETRY_ENDPOINT.token_type,
        )
        if result is None:
            raise OutOfRetries("SEMS+ telemetry request failed")
        factors = self._flatten_web_factors(
            result if isinstance(result, list) else None
        )
        telemetry: dict[str, Any] = {}
        string_fields = {"sn": "sn"}
        for source, target in string_fields.items():
            if isinstance(factors.get(source), str):
                telemetry[target] = factors[source]
        numeric_fields = {
            "hTotal": "hour_total",
            "Temperature": "tempperature",
            "totalPac": "meter_power",
            "Vac": "vac1",
            "PHASE-A:Vac": "vac1",
            "PHASE-B:Vac": "vac2",
            "PHASE-C:Vac": "vac3",
            "Iac": "iac1",
            "Fac": "fac1",
            "gridPF": "power_factor",
        }
        for source, target in numeric_fields.items():
            if (value := self._numeric_web_factor(factors, source)) is not None:
                telemetry[target] = value
        if "meter_power" in telemetry:
            telemetry["meter_power"] *= 1000
        for phase in ("A", "B", "C"):
            for suffix, target in (
                ("pAc", f"meter_phase_{phase.lower()}_power"),
                ("voltage", f"meter_phase_{phase.lower()}_voltage"),
                ("current", f"meter_phase_{phase.lower()}_current"),
            ):
                if (
                    value := self._numeric_web_factor(
                        factors, f"PHASE-{phase}:{suffix}"
                    )
                ) is not None:
                    telemetry[target] = value
        if (value := self._numeric_web_factor(factors, "pAc")) is not None:
            telemetry["pac"] = value * 1000
        for index in range(1, 5):
            for suffix, target_prefix in (("Vpv", "vpv"), ("Ipv", "ipv")):
                source = f"MPPT-{index}:{suffix}"
                if (value := self._numeric_web_factor(factors, source)) is not None:
                    telemetry[f"{target_prefix}{index}"] = value
            if (
                value := self._numeric_web_factor(factors, f"MPPT-{index}:Ppv")
            ) is not None:
                telemetry[f"ppv{index}"] = value * 1000
        if device_type == "BATTERY_RACK":
            battery_fields = {
                "pBat": ("pbattery", 1000),
                "voltage": ("vbattery", 1),
                "a": ("ibattery", 1),
                "soc": ("soc", 1),
                "soh": ("soh", 1),
                "tempMaxCell": ("bms_temperature", 1),
                "aMaxChar": ("bms_charge_i_max", 1),
                "aMaxDischar": ("bms_discharge_i_max", 1),
            }
            for source, (target, multiplier) in battery_fields.items():
                if (value := self._numeric_web_factor(factors, source)) is not None:
                    telemetry[target] = value * multiplier
        return telemetry

    def getWebInverterTelecounting(
        self,
        powerStationId: str,
        serialNumber: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        device_type: str = "INVERTER",
    ) -> dict[str, Any]:
        """Get normalized inverter energy counters from SEMS+ Web."""
        result = self._make_api_call(
            f"{_WEB_TELECOUNTING_ENDPOINT.url_part.format(serial_number=serialNumber)}"
            f"?deviceType={device_type}&pwId={powerStationId}",
            method="GET",
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getWebInverterTelecounting API call",
            is_web=True,
            token_type=_WEB_TELECOUNTING_ENDPOINT.token_type,
        )
        if result is None:
            raise OutOfRetries("SEMS+ counter request failed")
        factors = self._flatten_web_factors(
            result if isinstance(result, list) else None
        )
        counters: dict[str, Any] = {}
        for source, target in (
            ("ratedPower", "capacity"),
            ("proPvStatsToday", "eday"),
            ("proPvStatsWeek", "eweek"),
            ("proPvStatsMonth", "thismonthetotle"),
            ("proPvStatsYear", "eyear"),
            ("proPvStatsTotal", "etotal"),
            ("proCharStatsToday", "eChargeDay"),
            ("proDischarStatsToday", "eDischargeDay"),
            ("proCharStatsTotal", "echarge_total"),
            ("proDischarStatsTotal", "edischarge_total"),
        ):
            if (value := self._numeric_web_factor(factors, source)) is not None:
                counters[target] = value
        cache_key = f"counters:{powerStationId}:{serialNumber}:{device_type}"
        cached = self._get_web_cache_entry(cache_key)
        previous = cached[1] if cached and isinstance(cached[1], dict) else {}
        previous_periods = previous.get("_periods", {})
        if not isinstance(previous_periods, dict):
            previous_periods = {}
        now = dt_util.now()
        # Around midnight SEMS can report the previous day's counters for
        # several minutes after the reset (#94). Don't publish or cache them
        # before the portal has settled.
        # 23:58-00:20 is the window users in #94 have relied on for years.
        if (now.hour == 23 and now.minute >= 58) or (now.hour == 0 and now.minute < 20):
            _LOGGER.debug(
                "Keeping SEMS+ counters for %s during the midnight rollover",
                serialNumber,
            )
            return (
                {
                    key: value
                    for key, value in previous.items()
                    if not key.startswith("_")
                }
                if previous
                else {}
            )
        counter_periods = {
            "eday": now.date().isoformat(),
            "eweek": f"{now.isocalendar().year}-W{now.isocalendar().week}",
            "thismonthetotle": f"{now.year}-{now.month}",
            "eyear": str(now.year),
            "eChargeDay": now.date().isoformat(),
            "eDischargeDay": now.date().isoformat(),
        }
        for key in (
            "eday",
            "eweek",
            "thismonthetotle",
            "eyear",
            "etotal",
            "eChargeDay",
            "eDischargeDay",
            "echarge_total",
            "edischarge_total",
        ):
            value = counters.get(key)
            if value is None:
                continue
            old_value = previous.get(key)
            if key == "etotal" and value <= 0 and old_value is None:
                # The PV lifetime total of a commissioned inverter is never 0.
                # Without a cached value (after a restart) publish nothing.
                del counters[key]
                continue
            same_period = key not in counter_periods or (
                previous_periods.get(key) == counter_periods.get(key)
            )
            if (
                same_period
                and isinstance(old_value, (int, float))
                and old_value > 0
                and (value <= 0 or value < old_value)
            ):
                _LOGGER.warning(
                    "Ignoring invalid SEMS+ %s counter for %s: %s after %s",
                    key,
                    serialNumber,
                    value,
                    old_value,
                )
                counters[key] = old_value
        if device_type == "SMART_METER":
            for period in ("Today", "Week", "Month", "Year", "Total"):
                for source, target in (
                    (f"proPurchaseStats{period}", f"proPurchaseStats{period}"),
                    (f"proGridStats{period}", f"proGridStats{period}"),
                ):
                    if (value := self._numeric_web_factor(factors, source)) is not None:
                        counters[target] = value
        if counters:
            self._set_web_cache_entry(
                cache_key,
                (
                    time.monotonic(),
                    {
                        **previous,
                        **counters,
                        "_periods": {**previous_periods, **counter_periods},
                    },
                ),
            )
        return counters

    def getEnergyStorageIntegratedCabinets(
        self,
        powerStationId: str,
        serialNumber: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> list[dict[str, Any]]:
        """Get the energy storage integrated cabinets from the SEMS API."""
        result = self._make_api_call(
            f"/sems-plant/api/equipments/{serialNumber}/relatedDevices?sn={serialNumber}&deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId={powerStationId}",
            method="GET",
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getEnergyStorageIntegratedCabinets API call",
            is_web=True,
        )

        return result if isinstance(result, list) else []

    def _get_web_batteries(
        self, powerStationId: str, cabinets: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Map related BAT_SYS telemetry into the existing battery entity shape."""
        batteries: list[dict[str, Any]] = []
        for cabinet in cabinets:
            if not isinstance(cabinet, dict):
                continue
            device_type = cabinet.get("type") or cabinet.get("deviceType")
            if device_type != "BAT_SYS":
                continue
            serial_number = cabinet.get("sn")
            if not isinstance(serial_number, str):
                continue
            try:
                telemetry = self.getBatterySystemTelemetry(
                    powerStationId, serial_number
                )
            except (OutOfRetries, SemsPermissionError, SemsRateLimitedError) as err:
                _LOGGER.debug(
                    "SEMS BAT_SYS telemetry unavailable for %s: %s",
                    serial_number,
                    err,
                )
                continue
            battery: dict[str, Any] = {"sn": serial_number}
            for source, target in (
                ("power", "pbattery"),
                ("voltage", "vbattery"),
                ("current", "ibattery"),
                ("soc", "soc"),
                ("soh", "soh"),
                ("temperature", "bms_temperature"),
                ("max_charge_current", "bms_charge_i_max"),
                ("max_discharge_current", "bms_discharge_i_max"),
            ):
                if (value := telemetry.get(source)) is not None:
                    battery[target] = value * 1000 if source == "power" else value
            if len(battery) > 1:
                batteries.append(battery)
        return batteries

    def getBatterySystemDevices(
        self,
        powerStationId: str,
        serialNumber: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> list[dict[str, Any]]:
        """Discover attached BAT_SYS devices without making them mandatory."""
        result = self._make_api_call(
            f"/sems-plant/api/equipments/{serialNumber}/relatedDevices"
            f"?sn={serialNumber}&deviceType=BAT_SYS&pwId={powerStationId}",
            method="GET",
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getBatterySystemDevices API call",
            is_web=True,
        )
        return result if isinstance(result, list) else []

    def getBatterySystemTelemetry(
        self,
        powerStationId: str,
        serialNumber: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> dict[str, Any]:
        """Get telemetry for a related BAT_SYS device."""
        result = self._make_api_call(
            f"{_WEB_TELEMETRY_ENDPOINT.url_part.format(serial_number=serialNumber)}"
            f"?deviceType=BAT_SYS&pwId={powerStationId}",
            method="GET",
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getBatterySystemTelemetry API call",
            is_web=True,
            token_type=_WEB_TELEMETRY_ENDPOINT.token_type,
        )
        factors = self._flatten_web_factors(
            result if isinstance(result, list) else None
        )
        field_map = {
            "soc": "soc",
            "soh": "soh",
            "a": "current",
            "batSysTemp": "temperature",
            "aMaxChar": "max_charge_current",
            "aMaxDischar": "max_discharge_current",
            "voltage": "voltage",
            "SOC": "soc",
            "pBat": "power",
            "VBat": "voltage",
            "IBat": "current",
            "Temperature": "temperature",
            "MaxChargeCurrent": "max_charge_current",
            "MaxDischargeCurrent": "max_discharge_current",
        }
        return {
            target: value
            for source, target in field_map.items()
            if (value := self._numeric_web_factor(factors, source)) is not None
        }

    def getBatteryGeneralFunctions(
        self,
        serialNumber: str,
        batIndex: int,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> dict[str, Any]:
        """Get the battery general functions from the SEMS API."""
        # The function menus (addresses and ids) are static; don't refetch
        # them on every refresh.
        cache_key = f"function_menus:{serialNumber}:{batIndex}"
        cached = self._get_web_cache_entry(cache_key)
        if (
            cached
            and time.monotonic() - cached[0] < _WEB_FUNCTION_MENUS_REFRESH_SECONDS
        ):
            return cached[1]
        data = json.dumps(
            {
                "batIndex": str(batIndex),
                "menuCode": 1,
                "module": "GENERAL_FUNCTIONS",
                "sn": serialNumber,
            }
        )
        result = self._make_api_call(
            "/sems-remote/api/v2/address/remote/getDeviceFunctionTabMenus",
            method="POST",
            data=data,
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getBatteryGeneralFunctions API call",
            is_web=True,
            retry_on_api_error=False,
        )
        if not isinstance(result, dict):
            return {}
        if result.get("functionMenus"):
            self._set_web_cache_entry(cache_key, (time.monotonic(), result))
        return result

    def getBatteryImmediateChargingStates(
        self, serialNumber: str, renewToken: bool = False, maxTokenRetries: int = 2
    ) -> dict[str, Any] | None:
        """Get the battery immediate charging states from the SEMS API.

        Return None when SEMS returned no state, so callers don't mistake a
        failed read for a disabled function.
        """
        data = json.dumps(
            {
                "sn": serialNumber,
                "addresses": ["47545", "47545", "47546", "47603"],
                "addrFuncMap": {
                    "47545": "2013217017330515970",
                    "47546": "1991791639537946635",
                    "47603": "1991791639537946636",
                },
            }
        )

        result = self._make_api_call(
            "/sems-remote/api/v1/address/remote/get-cache-device-function-parameters",
            method="POST",
            data=data,
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getBatteryImmediateChargingStates API call",
            is_web=True,
            retry_on_api_error=False,
        )
        return result if isinstance(result, dict) else None

    def stopImmediateCharging(
        self,
        plant_id: str,
        serial_number: str,
        device_name: str,
        function_address: str,
        function_id: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ):
        self.setDeviceFunctionParameters(
            plant_id,
            serial_number,
            device_name,
            {function_address: 0},
            {"stop_charging": "remote_Switch_off"},
            {function_address: function_id},
            renewToken,
            maxTokenRetries,
        )

    def startImmediateCharging(
        self,
        plant_id: str,
        serial_number: str,
        device_name: str,
        function_address: str,
        function_id: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ):
        self.setDeviceFunctionParameters(
            plant_id,
            serial_number,
            device_name,
            {function_address: 1},
            {"immediate_charge": "on"},
            {function_address: function_id},
            renewToken,
            maxTokenRetries,
        )

    def setImmediateChargingEndSoC(
        self,
        plant_id: str,
        serial_number: str,
        device_name: str,
        end_soc: int,
        function_address: str,
        function_id: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ):
        self.setDeviceFunctionParameters(
            plant_id,
            serial_number,
            device_name,
            {function_address: end_soc},
            {"end_charge_soc": end_soc},
            {function_address: function_id},
            renewToken,
            maxTokenRetries,
        )

    def setImmediateChargingChargingPower(
        self,
        plant_id: str,
        serial_number: str,
        device_name: str,
        charging_power: int,
        function_address: str,
        function_id: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ):
        self.setDeviceFunctionParameters(
            plant_id,
            serial_number,
            device_name,
            {function_address: charging_power},
            {"bat_immediate_charge_power": charging_power},
            {function_address: function_id},
            renewToken,
            maxTokenRetries,
        )

    def setDeviceFunctionParameters(
        self,
        plant_id: str,
        serial_number: str,
        device_name: str,
        address_map: dict[str, Any],
        control_item_logs: dict[str, Any],
        addr_func_map: dict[str, str],
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        virtual_sn: str | None = None,
    ) -> bool:
        data = {
            "sn": serial_number,
            "addressMap": address_map,
            "addrFuncMap": addr_func_map,
            "controlItemLogs": control_item_logs,
            "waitingForDevice": True,
            "plantId": plant_id,
            "deviceName": device_name,
        }
        if virtual_sn is not None:
            data["virtualSn"] = virtual_sn

        return (
            self._make_api_call(
                "/sems-remote/api/v1/address/remote/setDeviceFunctionParameters",
                method="POST",
                data=json.dumps(data),
                renewToken=renewToken,
                maxTokenRetries=maxTokenRetries,
                operation_name="setDeviceFunctionParameters API call",
                is_web=True,
            )
            is not None
        )

    def _make_control_api_call(
        self,
        data: dict[str, Any],
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        operation_name: str = "Control API call",
    ) -> bool:
        """Make a control API call with different response handling."""
        _LOGGER.debug("SEMS - Making %s", operation_name)
        if maxTokenRetries <= 0:
            _LOGGER.info("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        api_url, headers, _generation = self._get_authenticated_request_context(
            _POWER_CONTROL_ENDPOINT.url_part,
            renewToken,
            operation_name,
            token_type=_POWER_CONTROL_ENDPOINT.token_type,
        )

        try:
            # Control API uses different validation (HTTP status code), so don't validate JSON response code
            self._make_http_request(
                api_url,
                headers,
                json_data=data,
                operation_name=operation_name,
                validate_code=False,
            )

            # For control API, any successful HTTP response (status 200) means success
            # The _make_http_request already validated HTTP status via raise_for_status()
            return True

        except requests.HTTPError as e:
            if hasattr(e.response, "status_code") and e.response.status_code != 200:
                _LOGGER.warning(
                    "%s not successful, retrying with new token, %s retries remaining",
                    operation_name,
                    maxTokenRetries,
                )
                return self._make_control_api_call(
                    data, True, maxTokenRetries - 1, operation_name
                )
            _LOGGER.error("Unable to execute %s: %s", operation_name, e)
            return False
        except SemsAuthExpiredError:
            return self._make_control_api_call(
                data, True, maxTokenRetries - 1, operation_name
            )
        except SemsRateLimitedError as exception:
            _LOGGER.warning("Unable to execute %s: %s", operation_name, exception)
            return False
        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.error("Unable to execute %s: %s", operation_name, exception)
            return False

    def change_status(
        self,
        inverterSn: str,
        status: str | int,
        plant_id: str | None = None,
        device_name: str | None = None,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> None:
        """Change inverter status through SEMS+ Web, falling back to legacy API."""
        if plant_id is not None and device_name is not None:
            web_status = str(status)
            if web_status in {"2", "4"}:
                try:
                    web_control_succeeded = self.setDeviceFunctionParameters(
                        plant_id,
                        inverterSn,
                        device_name,
                        {_WEB_INVERTER_STATUS_ADDRESS: int(web_status)},
                        {
                            "status_setting": (
                                "stop" if web_status == "2" else "start_up"
                            )
                        },
                        {
                            _WEB_INVERTER_STATUS_ADDRESS: _WEB_INVERTER_STATUS_FUNCTION_ID
                        },
                        renewToken=renewToken,
                        maxTokenRetries=maxTokenRetries,
                        virtual_sn=inverterSn,
                    )
                except OutOfRetries:
                    web_control_succeeded = False
                if web_control_succeeded:
                    return
                _LOGGER.warning(
                    "SEMS+ Web inverter status command failed; trying legacy API"
                )

        data = {
            "InverterSN": inverterSn,
            "InverterStatusSettingMark": "1",
            "InverterStatus": str(status),
        }

        success = self._make_control_api_call(
            data,
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name=f"power control command for inverter {inverterSn}",
        )

        if not success:
            action = {"2": "stop", "4": "start"}.get(str(status), str(status))
            device = device_name or inverterSn
            station = f" at station {plant_id}" if plant_id else ""
            message = (
                f"Unable to {action} inverter {device} "
                f"(serial {inverterSn}){station}. SEMS+ Web control was rejected "
                "and the legacy control request also failed. Verify that the "
                "GoodWe account has remote-control permission and re-register "
                "the integration with that account."
            )
            _LOGGER.error("%s", message)
            raise exceptions.HomeAssistantError(message)


class OutOfRetries(exceptions.HomeAssistantError):
    """Error to indicate too many error attempts."""


class SemsRateLimitedError(exceptions.HomeAssistantError):
    """Error to indicate the SEMS API requested retry with backoff."""

    def __init__(self, retry_after: int, message: str = "SEMS API rate limited"):
        """Initialize rate limit exception."""
        super().__init__(message)
        self.retry_after = retry_after


class SemsAuthExpiredError(exceptions.HomeAssistantError):
    """Error to indicate SEMS rejected the token (expired or replaced session)."""


class SemsAuthError(exceptions.HomeAssistantError):
    """Error to indicate SEMS repeatedly rejected the credentials."""


class SemsPermissionError(exceptions.HomeAssistantError):
    """Error to indicate the SEMS API denied access to an operation."""

    def __init__(self, operation_name: str, message: str):
        """Initialize the permission error."""
        super().__init__(f"{operation_name} was denied: {message}")

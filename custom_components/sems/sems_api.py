from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
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
}
_WEB_INVERTER_ENTITY_TYPES = {"INVERTER", "ENERGY_STORAGE_INTEGRATED_CABINET"}
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

_SuccessCodes = {0, "0", "00000"}
_RateLimitCode = "GY0429"
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
        try:
            _LOGGER.debug("SEMS - Making %s to %s", operation_name, url)
            response = requests.request(
                method.upper(),
                url,
                headers={"User-Agent": _BrowserUserAgent, **headers},
                data=data,
                json=json_data,
                timeout=_RequestTimeout,
            )

            _LOGGER.debug("%s Response: %s", operation_name, response)
            # _LOGGER.debug("%s Response text: %s", operation_name, response.text)

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
                json_response.get("api"),
                json_response.get("data") not in (None, "", [], {}),
            )

            if str(response_code) == _RateLimitCode:
                raise SemsRateLimitedError(
                    retry_after=_RateLimitRetryAfterSeconds,
                    message=(
                        f"{operation_name} returned rate-limit code {_RateLimitCode}"
                    ),
                )

            # Validate response code if requested
            if validate_code:
                if response_code not in _SuccessCodes:
                    _LOGGER.error(
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
            _LOGGER.error("Unable to complete %s: %s", operation_name, exception)
            raise

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
    ) -> tuple[str, dict[str, str]] | None:
        """Return the request URL and headers for an authenticated call."""
        if token_type == "web":
            token = self._web_token
        elif token_type == "new":
            token = self._new_token
        else:
            token = self._token

        if token is None or renewToken:
            _LOGGER.debug(
                "API token not set (%s) or new token requested (%s), fetching",
                redact_for_log(token),
                renewToken,
            )
            if token_type == "web":
                self._web_token = self._get_new_login_token(
                    self._username, self._password, is_web=True
                )
                token = self._web_token
            elif token_type == "new":
                self._new_token = self._get_new_login_token(
                    self._username, self._password
                )
                token = self._new_token
            else:
                self._token = self.getLoginToken(self._username, self._password)
                # A legacy re-login invalidates the SEMS+ Web session server-side.
                self._web_token = None
                token = self._token

        if token is None:
            _LOGGER.error(
                "Failed to obtain %s token for %s; endpoint %s cannot be called",
                token_type,
                operation_name,
                url_part,
            )
            return None

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
        return api_url, headers

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

        _LOGGER.error(
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
        """Make a generic API call with token management and retry logic."""
        _LOGGER.debug("SEMS - Making %s", operation_name)
        if maxTokenRetries <= 0:
            _LOGGER.info("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        if token_type is None:
            token_type = "web" if is_web else "legacy"

        context = self._get_authenticated_request_context(
            url_part,
            renewToken,
            operation_name,
            token_type=token_type,
        )
        if context is None:
            return None

        api_url, headers = context

        try:
            json_response: dict[str, Any] | None = self._make_http_request(
                api_url,
                headers,
                data=data,
                method=method,
                operation_name=operation_name,
                validate_code=retry_on_api_error,
            )

            # _make_http_request already validated the response, so if we get here, it's successful
            if json_response is None:
                # Response validation failed in _make_http_request
                _LOGGER.debug(
                    "%s not successful, retrying with new token, %s retries remaining",
                    operation_name,
                    maxTokenRetries,
                )
                return self._make_api_call(
                    url_part,
                    data,
                    True,
                    maxTokenRetries - 1,
                    operation_name,
                    method,
                    is_web,
                    retry_on_api_error,
                    token_type,
                )

            if is_web and not self._is_sensitive_operation(operation_name):
                _LOGGER.debug(
                    "SEMS - %s response data: %s",
                    operation_name,
                    redact_for_log(json_response.get("data")),
                )

            # Response is valid, return the data
            return json_response.get("data", {}) if is_web else json_response["data"]

        except SemsRateLimitedError as exception:
            _LOGGER.debug(
                "SEMS - Propagating rate limit from %s to coordinator: retry_after=%s",
                operation_name,
                exception.retry_after,
            )
            raise
        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.error("Unable to complete %s: %s", operation_name, exception)
            return None

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
        cached = self._web_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < refresh:
            return cached[1]

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
        if not isinstance(response, dict):
            return None

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
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
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
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric_value) and item not in parsed:
                parsed[item] = [numeric_value]
        for summary_key in _WEB_STATISTICS_RATE_MAP:
            value = response.get(summary_key)
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric_value):
                parsed[summary_key] = [numeric_value]

        response_dates = [
            statistic.get("date")
            for item_data in response.get("dataList", [])
            if isinstance(item_data, dict)
            for statistic in item_data.get("statisticsList", [])
            if isinstance(statistic, dict) and isinstance(statistic.get("date"), str)
        ]
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
        self._web_cache[cache_key] = (time.monotonic(), parsed)
        return parsed

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
                except (TypeError, ValueError, OSError, OverflowError):
                    continue
            if install_year is None:
                install_year = _WEB_STATISTICS_EARLIEST_YEAR
            with ThreadPoolExecutor(max_workers=5) as executor:
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

                production = production_future.result()
                statistic_data = [future.result() for future in statistics_futures]
                historic_statistics = historic_statistics_future.result()

            if production:
                currency = production.get("currency")
            for (_dimension, start, _), data in zip(
                statistic_ranges, statistic_data, strict=True
            ):
                if not data:
                    continue
                if start == now:
                    charts.update(
                        {
                            target: sum(data.get(source, []))
                            for source, target in _WEB_STATISTICS_KEY_MAP.items()
                        }
                    )
                    if production:
                        for source, target in _WEB_STATISTICS_KEY_MAP.items():
                            if target not in charts and isinstance(
                                production.get(source), (int, float)
                            ):
                                charts[target] = production[source]
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
                    target = _WEB_STATISTICS_KEY_MAP.get(item)
                    if target is not None:
                        totals[target] = sum(values)
            self_use = totals.get("selfUseOfPv")
            consumption = totals.get("consumptionOfLoad")
            production = totals.get("sum")
            if self_use is not None and consumption:
                totals["contributingRate"] = self_use / consumption
            if self_use is not None and production:
                totals["selfUseRate"] = self_use / production

            return charts, totals, currency, last_month_pv
        except (OutOfRetries, SemsRateLimitedError) as err:
            _LOGGER.debug("SEMS station statistics unavailable: %s", err)
            return None

    def _get_web_production(
        self, power_station_id: str, start: datetime, end: datetime
    ) -> dict[str, Any] | None:
        """Get optional flat station production totals and currency."""
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
        return response if isinstance(response, dict) else None

    def getWebData(
        self,
        powerStationId: str,
        renewToken: bool = False,
        maxTokenRetries: int = 2,
        include_last_month: bool = False,
    ) -> dict[str, Any]:
        """Build the legacy coordinator shape from SEMS+ Web responses."""
        inverters: list[dict[str, Any]] = []
        smart_meters: list[dict[str, Any]] = []
        for device in self.getWebInverterDevices(
            powerStationId, renewToken, maxTokenRetries
        ):
            serial_number = device.get("sn")
            if not isinstance(serial_number, str):
                continue
            device_type = device.get("deviceType", "INVERTER")
            if not isinstance(device_type, str):
                device_type = "INVERTER"
            device_data = {
                **device,
                **self.getWebInverterTelemetry(
                    powerStationId,
                    serial_number,
                    renewToken,
                    maxTokenRetries,
                    device_type=device_type,
                ),
                **self.getWebInverterTelecounting(
                    powerStationId,
                    serial_number,
                    renewToken,
                    maxTokenRetries,
                    device_type=device_type,
                ),
            }
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

        result: dict[str, Any] = {"inverter": inverters}
        try:
            flow = self.getWebStationFlow(powerStationId, renewToken, maxTokenRetries)
        except (OutOfRetries, SemsRateLimitedError) as err:
            _LOGGER.debug("SEMS station flow unavailable: %s", err)
            flow = {}
        if flow:
            if (
                not smart_meters
                and len(inverters) == 1
                and (grid_power := flow.get("pGrid")) is not None
            ):
                try:
                    for inverter in inverters:
                        inverter["invert_full"]["pmeter"] = float(grid_power) * 1000
                except (TypeError, ValueError):
                    _LOGGER.debug("SEMS station flow has an invalid pGrid value")
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
            cached = self._web_cache.get(cache_key)
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
                except (OutOfRetries, SemsRateLimitedError) as err:
                    _LOGGER.debug(
                        "SEMS related storage devices unavailable for %s: %s",
                        serial_number,
                        err,
                    )
                    cabinets = []
                if cabinets:
                    self._web_cache[cache_key] = (time.monotonic(), cabinets)
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
        if statistics is not None:
            charts, totals, currency, last_month_pv = statistics
            if charts:
                result["hasEnergeStatisticsCharts"] = True
                result["energeStatisticsCharts"] = charts
                result["energeStatisticsTotals"] = totals
            if last_month_pv is not None and len(inverters) == 1:
                invert_full = inverters[0].get("invert_full")
                if isinstance(invert_full, dict):
                    invert_full["lastmonthetotle"] = last_month_pv
            if currency is not None:
                result["kpi"] = {"currency": currency}
        return result

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
        grid_status = -1 if float(flow.get("pGrid", 0)) > 0 else 1
        battery_power = flow.get("pBat")
        battery_status = (
            -1 if battery_power is not None and float(battery_power) > 0 else 1
        )
        homekit: dict[str, Any] = {
            "sn": smart_meter.get("sn") if smart_meter else None,
            "gridStatus": grid_status,
            "loadStatus": grid_status,
        }
        for source, target in (
            ("pSystem" if "pSystem" in flow else "pAc", "pv"),
            ("pGrid", "grid"),
            ("pConsum", "load"),
            ("pBat", "battery"),
        ):
            if (value := flow.get(source)) is not None:
                homekit[target] = float(value) * 1000
        if (soc := flow.get("soc")) is not None:
            homekit["soc"] = soc
        if "battery" in homekit:
            homekit["batteryStatus"] = battery_status
            homekit["bettery"] = homekit["battery"]
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
        except (TypeError, ValueError):
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
        if device_type == "SMART_METER":
            for period in ("Today", "Week", "Month", "Year", "Total"):
                for source, target in (
                    (f"proPurchaseStats{period}", f"proPurchaseStats{period}"),
                    (f"proGridStats{period}", f"proGridStats{period}"),
                ):
                    if (value := self._numeric_web_factor(factors, source)) is not None:
                        counters[target] = value
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
            except (OutOfRetries, SemsRateLimitedError) as err:
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
        return result if isinstance(result, dict) else {}

    def getBatteryImmediateChargingStates(
        self, serialNumber: str, renewToken: bool = False, maxTokenRetries: int = 2
    ) -> dict[str, Any]:
        """Get the battery immediate charging states from the SEMS API."""
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
        return result if isinstance(result, dict) else {}

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
    ):
        data = {
            "sn": serial_number,
            "addressMap": address_map,
            "addrFuncMap": addr_func_map,
            "controlItemLogs": control_item_logs,
            "waitingForDevice": True,
            "plantId": plant_id,
            "deviceName": device_name,
        }

        self._make_api_call(
            "/sems-remote/api/v1/address/remote/setDeviceFunctionParameters",
            method="POST",
            data=json.dumps(data),
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="setDeviceFunctionParameters API call",
            is_web=True,
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

        context = self._get_authenticated_request_context(
            _POWER_CONTROL_ENDPOINT.url_part,
            renewToken,
            operation_name,
            token_type=_POWER_CONTROL_ENDPOINT.token_type,
        )
        if context is None:
            return False

        api_url, headers = context

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
        renewToken: bool = False,
        maxTokenRetries: int = 2,
    ) -> None:
        """Schedule the downtime of the station."""
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
            _LOGGER.error("Power control command failed after all retries")


class OutOfRetries(exceptions.HomeAssistantError):
    """Error to indicate too many error attempts."""


class SemsRateLimitedError(exceptions.HomeAssistantError):
    """Error to indicate the SEMS API requested retry with backoff."""

    def __init__(self, retry_after: int, message: str = "SEMS API rate limited"):
        """Initialize rate limit exception."""
        super().__init__(message)
        self.retry_after = retry_after

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any, Literal

import requests
from homeassistant import exceptions
from homeassistant.core import HomeAssistant

from .const import redact_for_log

_LOGGER = logging.getLogger(__name__)

OLD_LOGIN_URL = "https://www.semsportal.com/api/v3/Common/CrossLogin"
NEW_LOGIN_URL = "https://semsplus.goodwe.com/web/sems/sems-user/api/v1/auth/cross-login"
_GetPowerStationIdByOwnerURLPart = "/PowerStation/GetPowerStationIdByOwner"
_PowerStationURLPart = "/v3/PowerStation/GetMonitorDetailByPowerstationId"
_PowerControlURLPart = "/PowerStation/SaveRemoteControlInverter"
_RequestTimeout = 30  # seconds
_RateLimitRetryAfterSeconds = 300

_SuccessCodes = {0, "0", "00000"}
_RateLimitCode = "GY0429"

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
    "Accept": "application/json, */*;q=0.5",
    "Token": '{"uid":"","timestamp":0,"token":"","client":"semsPlusWeb","version":"","language":"en"}',
}


_NewLoginFallbackApi = "https://eu-gateway.semsportal.com/web/sems"
_LegacyApiFallback = "https://eu.semsportal.com/api"

type LoginMode = Literal["new", "legacy", "web"]
type LoginHandler = Callable[[str, str], dict[str, Any] | None]


class SemsApi:
    """Interface to the SEMS API."""

    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        """Init dummy hub."""
        self._hass = hass
        self._username = username
        self._password = password
        self._token: dict[str, Any] | None = None
        self._web_token: dict[str, Any] | None = None  # Used for SEMS+ web APIs
        self._preferred_login_mode: LoginMode | None = None

    def test_authentication(self) -> bool:
        """Test if we can authenticate with the host."""
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
                headers=headers,
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
                        json_response.get("msg", "Unknown error"),
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
        is_web: bool = False,
    ) -> tuple[str, dict[str, str]] | None:
        """Return the request URL and headers for an authenticated call."""
        if is_web:
            token = self._web_token
        else:
            token = self._token

        if token is None or renewToken:
            _LOGGER.debug(
                "API token not set (%s) or new token requested (%s), fetching",
                redact_for_log(token),
                renewToken,
            )
            if is_web:
                self._web_token = self._get_new_login_token(
                    self._username, self._password, is_web=True
                )
                token = self._web_token
            else:
                self._token = self.getLoginToken(self._username, self._password)
                token = self._token

        if token is None:
            _LOGGER.error("Failed to obtain API token")
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

    def _get_login_mode_order(self) -> list[LoginMode]:
        """Return login modes in preferred order."""
        login_modes: list[LoginMode] = ["new", "legacy"]
        if self._preferred_login_mode in login_modes:
            login_modes.remove(self._preferred_login_mode)
            login_modes.insert(0, self._preferred_login_mode)
        return login_modes

    def _login_handler_for_mode(self, login_mode: LoginMode) -> LoginHandler:
        """Return the login handler for a given mode."""
        if login_mode == "legacy":
            return self._get_legacy_login_token
        return self._get_new_login_token

    def _resolve_login_api_url(
        self,
        json_response: dict[str, Any],
        token_data: dict[str, Any],
        login_mode: LoginMode,
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
        login_mode: LoginMode,
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
        login_mode: LoginMode = "web" if is_web else "new"
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
        tried_login_modes: list[LoginMode] = []
        try:
            for login_mode in self._get_login_mode_order():
                tried_login_modes.append(login_mode)
                token = self._login_handler_for_mode(login_mode)(userName, password)

                if token is not None:
                    # Keep preferred mode in sync even when login helpers are mocked in tests.
                    self._preferred_login_mode = login_mode
                    return token

            _LOGGER.error(
                "Unable to authenticate with SEMS API; tried authentication methods: %s",
                ", ".join(tried_login_modes),
            )
            return None

        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.error(
                "Unable to fetch login token from SEMS API using %s authentication methods: %s",
                ", ".join(tried_login_modes),
                exception,
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
    ) -> Any | None:
        """Make a generic API call with token management and retry logic."""
        _LOGGER.debug("SEMS - Making %s", operation_name)
        if maxTokenRetries <= 0:
            _LOGGER.info("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        context = self._get_authenticated_request_context(
            url_part,
            renewToken,
            operation_name,
            is_web=is_web,
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
    ) -> Any | None:
        """Get the power station ids from the SEMS API."""
        return self._make_api_call(
            _GetPowerStationIdByOwnerURLPart,
            data=None,
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getPowerStationIds API call",
        )

    def getData(
        self, powerStationId: str, renewToken: bool = False, maxTokenRetries: int = 2
    ) -> dict[str, Any]:
        """Get the latest data from the SEMS API and updates the state."""
        data = '{"powerStationId":"' + powerStationId + '"}'
        result = self._make_api_call(
            _PowerStationURLPart,
            data=data,
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getData API call",
        )
        return result if isinstance(result, dict) else {}

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
            _PowerControlURLPart,
            renewToken,
            operation_name,
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

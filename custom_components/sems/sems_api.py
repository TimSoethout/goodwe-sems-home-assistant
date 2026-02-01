import json
import logging
import time

import requests

from homeassistant import exceptions

_LOGGER = logging.getLogger(__name__)

# Retry configuration for connection errors
_MAX_CONNECTION_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]  # seconds between retries

_LoginURL = "https://www.semsportal.com/api/v2/Common/CrossLogin"
_GetPowerStationIdByOwnerURLPart = "/PowerStation/GetPowerStationIdByOwner"
_PowerStationURLPart = "/v3/PowerStation/GetMonitorDetailByPowerstationId"
# _PowerControlURL = (
#     "https://www.semsportal.com/api/PowerStation/SaveRemoteControlInverter"
# )
_PowerControlURLPart = "/PowerStation/SaveRemoteControlInverter"
_RequestTimeout = 30  # seconds

_DefaultHeaders = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "token": '{"version":"","client":"ios","language":"en"}',
}


class SemsApi:
    """Interface to the SEMS API."""

    def __init__(self, hass, username, password):
        """Init dummy hub."""
        self._hass = hass
        self._username = username
        self._password = password
        self._token: dict | None = None

    def test_authentication(self) -> bool:
        """Test if we can authenticate with the host."""
        try:
            self._token = self.getLoginToken(self._username, self._password)
        except Exception as exception:
            _LOGGER.exception("SEMS Authentication exception: %s", exception)
            return False
        else:
            return self._token is not None

    def _make_http_request(
        self,
        url,
        headers,
        data=None,
        json_data=None,
        operation_name="HTTP request",
        validate_code=True,
        _retry_count=0,
    ):
        """Make a generic HTTP request with error handling, retry logic, and optional code validation."""
        try:
            _LOGGER.debug("SEMS - Making %s to %s", operation_name, url)

            response = requests.post(
                url,
                headers=headers,
                data=data,
                json=json_data,
                timeout=_RequestTimeout,
            )

            _LOGGER.debug("%s Response: %s", operation_name, response)
            # _LOGGER.debug("%s Response text: %s", operation_name, response.text)

            response.raise_for_status()
            jsonResponse = response.json()

            # Validate response code if requested
            if validate_code:
                if jsonResponse.get("code") not in (0, "0"):
                    _LOGGER.error(
                        "%s failed with code: %s, message: %s",
                        operation_name,
                        jsonResponse.get("code"),
                        jsonResponse.get("msg", "Unknown error"),
                    )
                    return None

                if jsonResponse.get("data") is None:
                    _LOGGER.error("%s response missing data field", operation_name)
                    return None

            return jsonResponse

        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as exception:
            # Connection errors (including RemoteDisconnected) - retry with backoff
            if _retry_count < _MAX_CONNECTION_RETRIES:
                delay = _RETRY_DELAYS[_retry_count] if _retry_count < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                _LOGGER.warning(
                    "SEMS connection error during %s, retry %d/%d in %ds: %s",
                    operation_name,
                    _retry_count + 1,
                    _MAX_CONNECTION_RETRIES,
                    delay,
                    exception,
                )
                time.sleep(delay)
                return self._make_http_request(
                    url, headers, data, json_data, operation_name, validate_code, _retry_count + 1
                )
            _LOGGER.error(
                "SEMS connection error during %s after %d retries: %s",
                operation_name,
                _MAX_CONNECTION_RETRIES,
                exception,
            )
            raise

        except requests.exceptions.Timeout as exception:
            # Timeout errors - also retry
            if _retry_count < _MAX_CONNECTION_RETRIES:
                delay = _RETRY_DELAYS[_retry_count] if _retry_count < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                _LOGGER.warning(
                    "SEMS timeout during %s, retry %d/%d in %ds",
                    operation_name,
                    _retry_count + 1,
                    _MAX_CONNECTION_RETRIES,
                    delay,
                )
                time.sleep(delay)
                return self._make_http_request(
                    url, headers, data, json_data, operation_name, validate_code, _retry_count + 1
                )
            _LOGGER.error(
                "SEMS timeout during %s after %d retries: %s",
                operation_name,
                _MAX_CONNECTION_RETRIES,
                exception,
            )
            raise

        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.error("Unable to complete %s: %s", operation_name, exception)
            raise

    def getLoginToken(self, userName: str, password: str) -> dict | None:
        """Get the login token for the SEMS API."""
        try:
            # Prepare Login Data to retrieve Authentication Token
            # Dict won't work here somehow, so this magic string creation must do.
            login_data = '{"account":"' + userName + '","pwd":"' + password + '"}'

            jsonResponse = self._make_http_request(
                _LoginURL,
                _DefaultHeaders,
                data=login_data,
                operation_name="login API call",
                validate_code=True,
            )

            if jsonResponse is None:
                return None

            # Get all the details from our response, needed to make the next POST request (the one that really fetches the data)
            # Also store the api url send with the authentication request for later use
            tokenDict = jsonResponse["data"]
            tokenDict["api"] = jsonResponse["api"]

            _LOGGER.debug("SEMS - API Token received: %s", tokenDict)
            return tokenDict

        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.error("Unable to fetch login token from SEMS API: %s", exception)
            return None

    def _make_api_call(
        self,
        url_part,
        data=None,
        renewToken=False,
        maxTokenRetries=2,
        operation_name="API call",
    ):
        """Make a generic API call with token management and retry logic."""
        _LOGGER.debug("SEMS - Making %s", operation_name)
        if maxTokenRetries <= 0:
            _LOGGER.info("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        if self._token is None or renewToken:
            _LOGGER.debug(
                "API token not set (%s) or new token requested (%s), fetching",
                self._token,
                renewToken,
            )
            self._token = self.getLoginToken(self._username, self._password)

        if self._token is None:
            _LOGGER.error("Failed to obtain API token")
            return None

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "token": json.dumps(self._token),
        }

        api_url = self._token["api"] + url_part

        try:
            jsonResponse = self._make_http_request(
                api_url,
                headers,
                data=data,
                operation_name=operation_name,
                validate_code=True,
            )

            # _make_http_request already validated the response, so if we get here, it's successful
            if jsonResponse is None:
                # Response validation failed in _make_http_request
                _LOGGER.debug(
                    "%s not successful, retrying with new token, %s retries remaining",
                    operation_name,
                    maxTokenRetries,
                )
                return self._make_api_call(
                    url_part, data, True, maxTokenRetries - 1, operation_name
                )

            # Response is valid, return the data
            return jsonResponse["data"]

        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.error("Unable to complete %s: %s", operation_name, exception)
            return None

    def getPowerStationIds(self, renewToken=False, maxTokenRetries=2) -> str | None:
        """Get the power station ids from the SEMS API."""
        return self._make_api_call(
            _GetPowerStationIdByOwnerURLPart,
            data=None,
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getPowerStationIds API call",
        )

    def getData(self, powerStationId, renewToken=False, maxTokenRetries=2) -> dict:
        """Get the latest data from the SEMS API and updates the state."""
        data = '{"powerStationId":"' + powerStationId + '"}'
        result = self._make_api_call(
            _PowerStationURLPart,
            data=data,
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getData API call",
        )
        return result or {}

    def _make_control_api_call(
        self,
        data,
        renewToken=False,
        maxTokenRetries=2,
        operation_name="Control API call",
    ):
        """Make a control API call with different response handling."""
        _LOGGER.debug("SEMS - Making %s", operation_name)
        if maxTokenRetries <= 0:
            _LOGGER.info("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        if self._token is None or renewToken:
            _LOGGER.debug(
                "API token not set (%s) or new token requested (%s), fetching",
                self._token,
                renewToken,
            )
            self._token = self.getLoginToken(self._username, self._password)

        if self._token is None:
            _LOGGER.error("Failed to obtain API token")
            return False

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "token": json.dumps(self._token),
        }

        api_url = self._token["api"] + _PowerControlURLPart

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
        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.error("Unable to execute %s: %s", operation_name, exception)
            return False

    def change_status(self, inverterSn, status, renewToken=False, maxTokenRetries=2):
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

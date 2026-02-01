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
_InverterAllPointURLPart = "/v3/PowerStation/GetInverterAllPoint"
_PowerflowURLPart = "/v2/PowerStation/GetPowerflow"
_PlantDetailURLPart = "/v3/PowerStation/GetPlantDetailByPowerstationId"
_WarningsURLPart = "/warning/PowerstationWarningsQuery"
_WeatherURLPart = "/v3/PowerStation/GetWeather"
_ChartURLPart = "/v2/Charts/GetChartByPlant"
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

    def getInverterAllPoint(self, powerStationId, renewToken=False, maxTokenRetries=2) -> dict:
        """Get detailed inverter data points (AC voltage, current, temp, PV strings, etc.).

        This endpoint returns additional inverter readings including:
        - AC voltage, current, and frequency
        - Inverter temperature
        - PV string voltage/current (PV1, PV2, PV3)
        - WiFi signal strength (RSSI)
        - Device type and capacity
        """
        _LOGGER.debug("SEMS - Making getInverterAllPoint API call")
        if maxTokenRetries <= 0:
            _LOGGER.info("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        if self._token is None or renewToken:
            self._token = self.getLoginToken(self._username, self._password)

        if self._token is None:
            _LOGGER.error("Failed to obtain API token")
            return {}

        # This endpoint requires form-urlencoded data (not JSON)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
            "token": json.dumps(self._token),
        }

        api_url = self._token["api"] + _InverterAllPointURLPart

        try:
            jsonResponse = self._make_http_request(
                api_url,
                headers,
                data={"powerStationId": powerStationId},
                operation_name="getInverterAllPoint API call",
                validate_code=True,
            )

            if jsonResponse is None:
                # Response validation failed, retry with new token
                _LOGGER.debug(
                    "getInverterAllPoint not successful, retrying with new token"
                )
                return self.getInverterAllPoint(powerStationId, True, maxTokenRetries - 1)

            return jsonResponse.get("data", {})

        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.debug("Unable to fetch inverter all point data: %s", exception)
            return {}

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

    def _make_form_api_call(
        self,
        url_part,
        data=None,
        renewToken=False,
        maxTokenRetries=2,
        operation_name="Form API call",
    ):
        """Make a form-encoded API call with token management."""
        _LOGGER.debug("SEMS - Making %s", operation_name)
        if maxTokenRetries <= 0:
            _LOGGER.info("SEMS - Maximum token fetch tries reached, aborting for now")
            raise OutOfRetries

        if self._token is None or renewToken:
            self._token = self.getLoginToken(self._username, self._password)

        if self._token is None:
            _LOGGER.error("Failed to obtain API token")
            return None

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
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

            if jsonResponse is None:
                _LOGGER.debug(
                    "%s not successful, retrying with new token, %s retries remaining",
                    operation_name,
                    maxTokenRetries,
                )
                return self._make_form_api_call(
                    url_part, data, True, maxTokenRetries - 1, operation_name
                )

            return jsonResponse.get("data", {})

        except (requests.RequestException, ValueError, KeyError) as exception:
            _LOGGER.debug("Unable to complete %s: %s", operation_name, exception)
            return None

    def getPowerflow(self, powerStationId, renewToken=False, maxTokenRetries=2) -> dict:
        """Get real-time power flow data.

        This is a lightweight endpoint that returns current power values:
        - pv: Solar production (W)
        - grid: Grid power (W)
        - load: House load (W)
        - bettery: Battery power (W)
        - soc: Battery state of charge (%)
        - pvStatus/gridStatus/loadStatus/betteryStatus: Direction indicators
        """
        result = self._make_form_api_call(
            _PowerflowURLPart,
            data={"PowerStationId": powerStationId},
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getPowerflow API call",
        )
        if result:
            return result.get("powerflow", {})
        return {}

    def getPlantDetail(self, powerStationId, renewToken=False, maxTokenRetries=2) -> dict:
        """Get detailed plant information including KPIs."""
        return self._make_form_api_call(
            _PlantDetailURLPart,
            data={"powerStationId": powerStationId},
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getPlantDetail API call",
        ) or {}

    def getWarnings(self, powerStationId, renewToken=False, maxTokenRetries=2) -> list:
        """Get active warnings and alerts."""
        result = self._make_form_api_call(
            _WarningsURLPart,
            data={"pw_id": powerStationId},
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getWarnings API call",
        )
        if result:
            return result.get("list", [])
        return []

    def getWeather(self, powerStationId, renewToken=False, maxTokenRetries=2) -> dict:
        """Get weather data for the plant location."""
        result = self._make_form_api_call(
            _WeatherURLPart,
            data={"powerStationId": powerStationId},
            renewToken=renewToken,
            maxTokenRetries=maxTokenRetries,
            operation_name="getWeather API call",
        )
        if result:
            return result.get("weather", {})
        return {}

    def getEnergyStatistics(self, powerStationId, date=None, range_type=2) -> dict:
        """Get energy statistics (import/export, self-consumption).

        Args:
            powerStationId: The power station ID
            date: Date in YYYY-MM-DD format (defaults to today)
            range_type: 1=day, 2=month, 3=year, 4=lifetime

        Returns data including:
            - buy: Grid import (kWh)
            - sell: Grid export/feed-in (kWh)
            - selfUseOfPv: Self-consumption (kWh)
            - selfUseRatio: Self-use percentage
        """
        from datetime import datetime as dt
        if date is None:
            date = dt.now().strftime("%Y-%m-%d")

        payload = {
            "id": powerStationId,
            "date": date,
            "range": str(range_type),
            "chartIndexId": "7",
            "isDetailFull": "",
        }

        # This endpoint uses JSON, not form data
        data = json.dumps(payload)
        result = self._make_api_call(
            _ChartURLPart,
            data=data,
            operation_name="getEnergyStatistics API call",
        )

        if result and result.get("modelData"):
            model_data = result["modelData"]
            return {
                "buy": model_data.get("buy", 0),
                "buy_percent": model_data.get("buyPercent", 0),
                "sell": model_data.get("sell", 0),
                "sell_percent": model_data.get("sellPercent", 0),
                "self_use_of_pv": model_data.get("selfUseOfPv", 0),
                "self_use_ratio": model_data.get("selfUseRatio", 0),
                "consumption_of_load": model_data.get("consumptionOfLoad", 0),
                "in_house": model_data.get("in_House", 0),
                "contribution_ratio": model_data.get("contributionRatio", 0),
                "generation": model_data.get("sum", 0),
                "charge": model_data.get("charge", 0),
                "discharge": model_data.get("disCharge", 0),
            }
        return {}

    def getAllData(self, powerStationId, quick_mode=False) -> dict:
        """Fetch all available data for a power station.

        Args:
            powerStationId: The power station ID
            quick_mode: If True, only fetch powerflow data (for split polling)

        Returns combined data from multiple endpoints.
        """
        result = {
            "powerstation_id": powerStationId,
            "powerflow": None,
            "plant_detail": None,
            "inverter_points": None,
            "warnings": None,
            "weather": None,
            "energy_statistics": None,
            "quick_mode": quick_mode,
        }

        # Powerflow is always fetched - it's the real-time power data
        try:
            result["powerflow"] = self.getPowerflow(powerStationId)
            if result["powerflow"]:
                _LOGGER.debug(
                    "SEMS: Powerflow - pv=%s, grid=%s (status=%s), load=%s",
                    result["powerflow"].get("pv"),
                    result["powerflow"].get("grid"),
                    result["powerflow"].get("gridStatus"),
                    result["powerflow"].get("load"),
                )
        except Exception as err:
            _LOGGER.debug("SEMS: Failed to get powerflow: %s", err)

        # In quick mode, skip the detailed/slower endpoints
        if quick_mode:
            _LOGGER.debug("SEMS: Quick mode - skipping detailed endpoints")
            return result

        # Full mode - fetch everything
        try:
            plant_data = self.getPlantDetail(powerStationId)
            if plant_data:
                result["plant_detail"] = plant_data
        except Exception as err:
            _LOGGER.debug("SEMS: Failed to get plant detail: %s", err)

        try:
            inverter_data = self.getInverterAllPoint(powerStationId)
            if inverter_data:
                result["inverter_points"] = inverter_data.get("inverterPoints", [])
        except Exception as err:
            _LOGGER.debug("SEMS: Failed to get inverter points: %s", err)

        try:
            result["warnings"] = self.getWarnings(powerStationId)
        except Exception as err:
            _LOGGER.debug("SEMS: Failed to get warnings: %s", err)

        try:
            result["weather"] = self.getWeather(powerStationId)
        except Exception as err:
            _LOGGER.debug("SEMS: Failed to get weather: %s", err)

        try:
            result["energy_statistics"] = self.getEnergyStatistics(powerStationId)
            if result["energy_statistics"]:
                _LOGGER.debug(
                    "SEMS: Energy stats - buy=%.1f, sell=%.1f, self_use=%.1f%%",
                    result["energy_statistics"].get("buy", 0),
                    result["energy_statistics"].get("sell", 0),
                    result["energy_statistics"].get("self_use_ratio", 0),
                )
        except Exception as err:
            _LOGGER.debug("SEMS: Failed to get energy statistics: %s", err)

        return result

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

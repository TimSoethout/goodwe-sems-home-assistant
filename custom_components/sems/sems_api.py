import json
import logging

import requests

from homeassistant import exceptions

_LOGGER = logging.getLogger(__name__)

# _LoginURL = "https://eu.semsportal.com/api/v2/Common/CrossLogin"
_LoginURL = "https://www.semsportal.com/api/v2/Common/CrossLogin"
_PowerStationURLPart = "/v2/PowerStation/GetMonitorDetailByPowerstationId"
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
        self._token = None

    def test_authentication(self) -> bool:
        """Test if we can authenticate with the host."""
        try:
            self._token = self.getLoginToken(self._username, self._password)
            return self._token is not None
        except Exception as exception:
            _LOGGER.exception("SEMS Authentication exception " + exception)
            return False

    def getLoginToken(self, userName, password):
        """Get the login token for the SEMS API"""
        try:
            # Get our Authentication Token from SEMS Portal API
            _LOGGER.debug("SEMS - Getting API token")

            # Prepare Login Data to retrieve Authentication Token
            # Dict won't work here somehow, so this magic string creation must do.
            login_data = '{"account":"' + userName + '","pwd":"' + password + '"}'
            # login_data = {"account": userName, "pwd": password}

            # Make POST request to retrieve Authentication Token from SEMS API
            login_response = requests.post(
                _LoginURL,
                headers=_DefaultHeaders,
                data=login_data,
                timeout=_RequestTimeout,
            )
            _LOGGER.debug("Login Response: %s", login_response)
            # _LOGGER.debug("Login Response text: %s", login_response.text)

            login_response.raise_for_status()

            # Process response as JSON
            jsonResponse = login_response.json()  # json.loads(login_response.text)
            # _LOGGER.debug("Login JSON response %s", jsonResponse)
            # Get all the details from our response, needed to make the next POST request (the one that really fetches the data)
            # Also store the api url send with the authentication request for later use
            tokenDict = jsonResponse["data"]
            tokenDict["api"] = jsonResponse["api"]

            _LOGGER.debug("SEMS - API Token received: %s", tokenDict)
            return tokenDict
        except Exception as exception:
            _LOGGER.error("Unable to fetch login token from SEMS API. %s", exception)
            return None

    def getData(self, powerStationId, renewToken=False, maxTokenRetries=2):
        """Get the latest data from the SEMS API and updates the state."""
        try:
            # Get the status of our SEMS Power Station
            _LOGGER.debug("SEMS - Making Power Station Status API Call")
            if maxTokenRetries <= 0:
                _LOGGER.info(
                    "SEMS - Maximum token fetch tries reached, aborting for now"
                )
                raise OutOfRetries
            if self._token is None or renewToken:
                _LOGGER.debug(
                    "API token not set (%s) or new token requested (%s), fetching",
                    self._token,
                    renewToken,
                )
                self._token = self.getLoginToken(self._username, self._password)

            # Prepare Power Station status Headers
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "token": json.dumps(self._token),
            }

            powerStationURL = self._token["api"] + _PowerStationURLPart
            _LOGGER.debug(
                "Querying SEMS API (%s) for power station id: %s",
                powerStationURL,
                powerStationId,
            )

            data = '{"powerStationId":"' + powerStationId + '"}'

            response = requests.post(
                powerStationURL, headers=headers, data=data, timeout=_RequestTimeout
            )
            jsonResponse = response.json()
            # try again and renew token is unsuccessful
            if jsonResponse["msg"] != "success" or jsonResponse["data"] is None:
                _LOGGER.debug(
                    "Query not successful (%s), retrying with new token, %s retries remaining",
                    jsonResponse["msg"],
                    maxTokenRetries,
                )
                return self.getData(
                    powerStationId, True, maxTokenRetries=maxTokenRetries - 1
                )

            return jsonResponse["data"]
        except Exception as exception:
            _LOGGER.error("Unable to fetch data from SEMS. %s", exception)


class OutOfRetries(exceptions.HomeAssistantError):
    """Error to indicate too many error attempts."""

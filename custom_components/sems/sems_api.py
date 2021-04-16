import json
import logging

import requests

_LOGGER = logging.getLogger(__name__)

_LoginURL = "https://eu.semsportal.com/api/v2/Common/CrossLogin"
_PowerStationURL = (
    "https://eu.semsportal.com/api/v2/PowerStation/GetMonitorDetailByPowerstationId"
)
_RequestTimeout = 30  # seconds

_DefaultHeaders = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "token": '{"version":"","client":"web","language":"en"}',
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
            token = json.dumps(jsonResponse["data"])

            _LOGGER.debug("SEMS - API Token received: %s", token)
            return token
        except Exception as exception:
            _LOGGER.error("Unable to fetch login token from SEMS API. %s", exception)
            return None

    def getData(self, powerStationId, renewToken=False):
        """Get the latest data from the SEMS API and updates the state."""
        try:
            # Get the status of our SEMS Power Station
            _LOGGER.debug("SEMS - Making Power Station Status API Call")
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
                "token": self._token,
            }

            _LOGGER.debug("Querying SEMS API for power station id: %s", powerStationId)

            data = '{"powerStationId":"' + powerStationId + '"}'

            response = requests.post(
                _PowerStationURL, headers=headers, data=data, timeout=_RequestTimeout
            )
            jsonResponse = response.json()
            # try again and renew token is unsuccessful
            if jsonResponse["msg"] != "success" or jsonResponse["data"] is None:
                _LOGGER.debug(
                    "Query not successful (%s), retrying with new token",
                    jsonResponse["msg"],
                )
                return self.getData(powerStationId, True)

            # return list of all inverters
            return jsonResponse["data"]["inverter"]
        except Exception as exception:
            _LOGGER.error("Unable to fetch data from SEMS. %s", exception)

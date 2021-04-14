import json
import logging

import requests
import voluptuous as vol
from datetime import timedelta
from typing import NamedTuple
import async_timeout

_LOGGER = logging.getLogger(__name__)

_LoginURL = "https://www.semsportal.com/api/v1/Common/CrossLogin"
_PowerStationURL = (
    "https://www.semsportal.com/api/v1/PowerStation/GetMonitorDetailByPowerstationId"
)
_RequestTimeout = 60  # seconds


class SemsApiToken(NamedTuple):
    requestTimestamp: str
    requestUID: str
    requestToken: str


# class SemsApiHub:
#     """ SemsApiHub """

#     def __init__(self, station_id: str) -> None:
#         """Initialize."""
#         self.station_id = station_id

#     def authenticate(self, username: str, password: str) -> bool:
#         """Test if we can authenticate with the host."""
#         try:
#             token = self.getLoginToken(username, password)
#             return True
#         except Exception as exception:
#             _LOGGER.exception("SEMS Authentication exception " + exception)
#             return False


class SemsApi:
    """ Interface to the SEMS API """

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

            # Prepare Login Headers to retrieve Authentication Token
            login_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "token": '{"version":"","client":"web","language":"en"}',
            }

            # Prepare Login Data to retrieve Authentication Token
            login_data = (
                '{"account":"'
                + userName
                + '","pwd":"'
                + password
                + '", "agreement_agreement": 1}'
            )

            # Make POST request to retrieve Authentication Token from SEMS API
            login_response = requests.post(
                _LoginURL,
                headers=login_headers,
                data=login_data,
                timeout=_RequestTimeout,
            )
            # _LOGGER.debug("Login Response: %s", login_response)

            # Process response as JSON
            jsonResponse = json.loads(login_response.text)
            _LOGGER.debug("Login JSON response %s", jsonResponse)
            # Get all the details from our response, needed to make the next POST request (the one that really fetches the data)
            requestTimestamp = jsonResponse["data"]["timestamp"]
            requestUID = jsonResponse["data"]["uid"]
            requestToken = jsonResponse["data"]["token"]

            token = SemsApiToken(requestTimestamp, requestUID, requestToken)
            _LOGGER.debug("SEMS - API Token received: %s", token)
            return token
        except Exception as exception:
            _LOGGER.error("Unable to fetch login token from SEMS API. %s", exception)
            return None

    def getData(self, stationId):
        """Get the latest data from the SEMS API and updates the state."""
        _LOGGER.debug("update called.")
        try:
            # Get the status of our SEMS Power Station
            _LOGGER.debug("SEMS - Making Power Station Status API Call")

            # if self._token is None:
            # _LOGGER.debug("API token not set, fetching")
            # always relogin for now.
            self._token = self.getLoginToken(self._username, self._password)

            # Prepare Power Station status Headers
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "token": '{"version":"","client":"web","language":"en","timestamp":"'
                + str(self._token.requestTimestamp)
                + '","uid":"'
                + self._token.requestUID
                + '","token":"'
                + self._token.requestToken
                + '"}',
            }

            _LOGGER.debug("Querying for : %s", stationId)

            data = '{"powerStationId":"' + stationId + '"}'

            response = requests.post(
                _PowerStationURL, headers=headers, data=data, timeout=_RequestTimeout
            )

            # Process response as JSON
            jsonResponseFinal = json.loads(response.text)

            # _LOGGER.debug("Data REST Response Received: %s", jsonResponseFinal)
            # _LOGGER.debug(jsonResponseFinal["data"]["inverter"])

            # return list of all inverters
            return jsonResponseFinal["data"]["inverter"]
            # for key, value in jsonResponseFinal["data"]["inverter"][0]["invert_full"].items():
            # if(key is not None and value is not None):
            # self._attributes[key] = value/
            # _LOGGER.debug("Updated attribute %s: %s", key, value)
        except Exception as exception:
            _LOGGER.error("Unable to fetch data from SEMS. %s", exception)

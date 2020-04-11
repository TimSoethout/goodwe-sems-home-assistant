"""
Support for power production statistics from Goodwe SEMS web portal.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import json
import logging

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

CONF_STATION_ID = "station_id"

# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_STATION_ID): cv.string
})

_LOGGER = logging.getLogger(__name__)

_URL = 'https://www.semsportal.com/api/v1/Common/CrossLogin'
_PowerStationURL = 'https://www.semsportal.com/api/v1/PowerStation/GetMonitorDetailByPowerstationId'
_RequestTimeout = 30 # seconds

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the GoodWe SEMS API sensor platform."""
    # Add devices
    add_devices([SemsSensor("SEMS Portal", config)], True)

class SemsSensor(Entity):
    """Representation of the SEMS portal."""

    def __init__(self, name, config):
        """Initialize a SEMS sensor."""
        # self.rest = rest
        self._name = name
        self._config = config
        self._attributes = {}

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._attributes['status']

    @property
    def device_state_attributes(self):
        """Return the state attributes of the monitored installation."""
        return self._attributes

    def update(self):
        """Get the latest data from the SEMS API and updates the state."""
        _LOGGER.debug("update called.")
        try:
        # Get our Authentication Token from SEMS Portal API
            _LOGGER.debug("SEMS - Getting API token")

            # Prepare Login Headers to retrieve Authentication Token
            login_headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'token': '{"version":"v2.1.0","client":"ios","language":"en"}',
            }

            # Prepare Login Data to retrieve Authentication Token
            login_data = '{"account":"'+self._config.get(CONF_USERNAME)+'","pwd":"'+self._config.get(CONF_PASSWORD)+'"}'

            # Make POST request to retrieve Authentication Token from SEMS API
            login_response = requests.post(_URL, headers=login_headers, data=login_data, timeout=_RequestTimeout)

            # Process response as JSON
            jsonResponse = json.loads(login_response.text)

            # Get all the details from our response, needed to make the next POST request (the one that really fetches the data)
            requestTimestamp = jsonResponse["data"]["timestamp"]
            requestUID = jsonResponse["data"]["uid"]
            requestToken = jsonResponse["data"]["token"]

            _LOGGER.debug("SEMS - API Token recieved: "+ requestToken)
        # Get the status of our SEMS Power Station
            _LOGGER.debug("SEMS - Making Power Station Status API Call")

            # Prepare Power Station status Headers
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'token': '{"version":"v2.1.0","client":"ios","language":"en","timestamp":"'+str(requestTimestamp)+'","uid":"'+requestUID+'","token":"'+requestToken+'"}',
            }

            data = '{"powerStationId":"'+self._config.get(CONF_STATION_ID)+'"}'            

            response = requests.post(_PowerStationURL, headers=headers, data=data, timeout=_RequestTimeout)

            # Process response as JSON
            jsonResponseFinal = json.loads(response.text)

            _LOGGER.debug("REST Response Recieved")

            for key, value in jsonResponseFinal["data"]["inverter"][0]["invert_full"].items():
                if(key is not None and value is not None):
                    self._attributes[key] = value
                    _LOGGER.debug("Updated attribute %s: %s", key, value)
        except Exception as exception:
            _LOGGER.error(
                "Unable to fetch data from SEMS. %s", exception)

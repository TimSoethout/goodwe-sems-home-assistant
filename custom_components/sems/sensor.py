"""
Support for power production statistics from Goodwe SEMS web portal.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

import json
import logging

import requests
import voluptuous as vol
from datetime import timedelta
from typing import NamedTuple
import async_timeout

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, DEVICE_CLASS_POWER, POWER_WATT
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

_LoginURL = 'https://www.semsportal.com/api/v1/Common/CrossLogin'
_PowerStationURL = 'https://www.semsportal.com/api/v1/PowerStation/GetMonitorDetailByPowerstationId'
_RequestTimeout = 30  # seconds


class SemsApiToken(NamedTuple):
    requestTimestamp: str
    requestUID: str
    requestToken: str


def getLoginToken(userName, password):
    """Get the login token for the SEMS API"""
    try:
        # Get our Authentication Token from SEMS Portal API
        _LOGGER.debug("SEMS - Getting API token")

        # Prepare Login Headers to retrieve Authentication Token
        login_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'token': '{"version":"","client":"web","language":"en"}'
        }

        # Prepare Login Data to retrieve Authentication Token
        login_data = '{"account":"'+userName+'","pwd":"' + \
            password+'", "agreement_agreement": 1}'

        # Make POST request to retrieve Authentication Token from SEMS API
        login_response = requests.post(
            _LoginURL, headers=login_headers, data=login_data, timeout=_RequestTimeout)

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
        _LOGGER.error(
            "Unable to fetch login token from SEMS API. %s", exception)


def getData(token, config):
    """Get the latest data from the SEMS API and updates the state."""
    _LOGGER.debug("update called.")
    try:
        # Get the status of our SEMS Power Station
        _LOGGER.debug("SEMS - Making Power Station Status API Call")

        # Prepare Power Station status Headers
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'token': '{"version":"","client":"web","language":"en","timestamp":"'+str(token.requestTimestamp)+'","uid":"'+token.requestUID+'","token":"'+token.requestToken+'"}',
        }

        data = '{"powerStationId":"'+config.get(CONF_STATION_ID)+'"}'

        response = requests.post(
            _PowerStationURL, headers=headers, data=data, timeout=_RequestTimeout)

        # Process response as JSON
        jsonResponseFinal = json.loads(response.text)

        _LOGGER.debug("REST Response Received")
        # _LOGGER.debug(jsonResponseFinal["data"]["inverter"])

        # return list of all inverters
        return jsonResponseFinal["data"]["inverter"]
        # for key, value in jsonResponseFinal["data"]["inverter"][0]["invert_full"].items():
        # if(key is not None and value is not None):
        # self._attributes[key] = value/
        # _LOGGER.debug("Updated attribute %s: %s", key, value)
    except Exception as exception:
        _LOGGER.error(
            "Unable to fetch data from SEMS. %s", exception)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    # assuming API object stored here by __init__.py
    # api = hass.data[DOMAIN][entry.entry_id]

    async def async_update_data():
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            # async with async_timeout.timeout(10):
            token = getLoginToken(config.get(CONF_USERNAME),
                                  config.get(CONF_PASSWORD))
            inverters = getData(token, config)
            # found = []
            data = {}
            for inverter in inverters:
                name = inverter["invert_full"]["name"]
                sn = inverter["invert_full"]["sn"]
                _LOGGER.debug("Found inverter attribute %s %s", name, sn)
                # TODO: construct name instead of serial number: goodwe_plantname_invertername
                data[sn] = inverter["invert_full"]
            return data
        # except ApiError as err:
        except Exception as err:
            # logging.exception("Something awful happened!")
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        # Name of the data. For logging purposes.
        name="SEMS Portal",
        update_method=async_update_data,
        # Polling interval. Will only be polled if there are subscribers.
        update_interval=timedelta(seconds=60),
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_refresh()

    # _LOGGER.debug("Initial coordinator data: %s", coordinator.data)

    async_add_entities(SemsSensor(coordinator, sn) for sn, ent
                       in coordinator.data.items())

class SemsSensor(Entity):
    def __init__(self, coordinator, sn):
        self.coordinator = coordinator
        self._sn = sn

    @property
    def device_class(self):
        return DEVICE_CLASS_POWER

    @property
    def unit_of_measurement(self):
        return POWER_WATT

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._sn

    @property
    def state(self):
        """Return the state of the device."""
        # _LOGGER.debug("state, coordinator data: %s", self.coordinator.data)
        # _LOGGER.debug("state, self data: %s", self.coordinator.data[self._sn])
        return self.coordinator.data[self._sn]['pac']

    # For backwards compatibility
    @property
    def device_state_attributes(self):
        """Return the state attributes of the monitored installation."""
        data = self.coordinator.data[self._sn]
        # _LOGGER.debug("state, self data: %s", data.items())
        return {k:v for k,v in data.items() if k is not None and v is not None}
        # for key, value in data.items:
        #     if(key is not None and value is not None):
        #         _LOGGER.debug("Returning attribute %s: %s", key, value)
        #         yield key, value

    @property
    def is_on(self):
        """Return entity status.
        """
        self.coordinator.data[self._sn]['status']

    @property
    def should_poll(self):
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(
                self.async_write_ha_state
            )
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self.coordinator.async_request_refresh()

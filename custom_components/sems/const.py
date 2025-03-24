"""Constants for the SEMS integration."""

from datetime import timedelta

import voluptuous as vol

from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
import homeassistant.helpers.config_validation as cv

DOMAIN = "sems"

PLATFORMS = ["sensor", "switch"]

CONF_STATION_ID = "powerstation_id"

DEFAULT_SCAN_INTERVAL = 60  # timedelta(seconds=60)

# Validation of the user's configuration
SEMS_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_STATION_ID): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, description={"suggested_value": 60}
        ): int,  # , default=DEFAULT_SCAN_INTERVAL
    }
)

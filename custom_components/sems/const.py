"""Constants for the sems integration."""

DOMAIN = "sems"

import voluptuous as vol
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DEVICE_CLASS_POWER,
    POWER_WATT,
)

CONF_STATION_ID = "powerstation_id"

# Validation of the user's configuration
SEMS_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_STATION_ID): str,
    }
)

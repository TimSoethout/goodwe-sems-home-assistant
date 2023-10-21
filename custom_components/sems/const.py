"""Constants for the sems integration."""

DOMAIN = "sems"

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_SCAN_INTERVAL

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

API_UPDATE_ERROR_MSG = "Error communicating with API, probably token could not be fetched, see debug logs"

AC_EMPTY = 6553.5
AC_CURRENT_EMPTY = 6553.5
AC_FEQ_EMPTY = 655.35

class GOODWE_SPELLING:
    battery = "bettery"
    homeKit = "homKit"
    temperature = "tempperature"
    hasEnergyStatisticsCharts = "hasEnergeStatisticsCharts"
    energyStatisticsCharts = "energeStatisticsCharts"
    energyStatisticsTotals = "energeStatisticsTotals"
    thisMonthTotalE = "thismonthetotle"
    lastMonthTotalE = "lastmonthetotle"

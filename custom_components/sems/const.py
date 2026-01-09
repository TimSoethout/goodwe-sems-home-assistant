"""Constants for the SEMS integration."""

import voluptuous as vol

from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME

DOMAIN = "sems"

PLATFORMS = ["sensor", "switch"]

CONF_STATION_ID = "powerstation_id"

DEFAULT_SCAN_INTERVAL = 60  # timedelta(seconds=60)

# Validation of the user's configuration
SEMS_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_STATION_ID): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, description={"suggested_value": 60}
        ): int,  # , default=DEFAULT_SCAN_INTERVAL
    }
)

AC_EMPTY = 6553.5
AC_CURRENT_EMPTY = 6553.5
AC_FEQ_EMPTY = 655.35


class GOODWE_SPELLING:
    """Constants for correcting GoodWe API spelling errors."""

    battery = "bettery"
    batteryStatus = "betteryStatus"
    homeKit = "homKit"
    temperature = "tempperature"
    hasEnergyStatisticsCharts = "hasEnergeStatisticsCharts"
    energyStatisticsCharts = "energeStatisticsCharts"
    energyStatisticsTotals = "energeStatisticsTotals"
    thisMonthTotalE = "thismonthetotle"
    lastMonthTotalE = "lastmonthetotle"

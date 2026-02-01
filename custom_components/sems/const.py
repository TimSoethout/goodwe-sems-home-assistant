"""Constants for the SEMS integration."""

import voluptuous as vol

from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME

DOMAIN = "sems"

PLATFORMS = ["sensor", "switch"]

CONF_STATION_ID = "powerstation_id"
CONF_NIGHT_MODE = "night_mode"
CONF_NIGHT_INTERVAL = "night_interval"
CONF_MIDNIGHT_SKIP = "midnight_skip"
CONF_STALE_THRESHOLD = "stale_threshold"
CONF_ALWAYS_POLL_POWERFLOW = "always_poll_powerflow"
CONF_API_SERVER = "api_server"

# Scan interval limits
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 300

DEFAULT_SCAN_INTERVAL = 60  # timedelta(seconds=60)

# API Server options
API_SERVERS = {
    "auto": "Auto-detect (recommended)",
    "global": "Global (semsportal.com)",
    "eu": "Europe (eu.semsportal.com)",
    "us": "USA (us.semsportal.com)",
    "au": "Australia (au.semsportal.com)",
    "cn": "China (semsportal.com.cn)",
}

DEFAULT_API_SERVER = "auto"
DEFAULT_NIGHT_INTERVAL = 300  # 5 minutes during night
DEFAULT_STALE_THRESHOLD = 300  # 5 minutes - data older than this is stale

# Staleness detection (in minutes for sensor display)
STALE_THRESHOLD_MINUTES = 5

# Midnight skip window (23:55-00:10) - avoid phantom data around midnight
MIDNIGHT_SKIP_START_HOUR = 23
MIDNIGHT_SKIP_START_MINUTE = 55
MIDNIGHT_SKIP_END_HOUR = 0
MIDNIGHT_SKIP_END_MINUTE = 10

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


STATUS_LABELS = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}


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

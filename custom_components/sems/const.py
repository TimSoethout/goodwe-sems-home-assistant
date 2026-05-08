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


def redact_value(value: str) -> str:
    """Return a partial redaction of a sensitive value for logging.

    Shows enough of the value to remain unique/recognizable while hiding
    the sensitive information.
    """
    if not value:
        return "<redacted>"

    # For email addresses, show domain but redact local part
    if "@" in value:
        parts = value.rsplit("@", 1)
        return f"<***@{parts[1]}>"

    # For UUIDs (8-4-4-4-12 pattern with hyphens)
    if value.count("-") == 4 and len(value) == 36:
        return f"<{value[:4]}...{value[-4:]}>"

    # For longer strings (SNs, IDs), show first and last few chars
    if len(value) > 8:
        return f"<{value[:3]}...{value[-3:]}>"

    # For short strings, just show pattern
    return f"<{value[0]}{'*' * (len(value) - 1)}>"

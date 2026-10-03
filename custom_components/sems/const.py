"""Constants for the SEMS integration."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_SCAN_INTERVAL

DOMAIN = "sems"

PLATFORMS = ["number", "select", "sensor", "switch"]

CONF_STATION_ID = "powerstation_id"

DEFAULT_SCAN_INTERVAL = 60  # seconds
# SEMS+ reports station data with a one-minute resolution (see `refreshTime`
# in api_examples/station_flow.json), so polling faster only repeats data while
# each refresh costs about 5-11 requests per station on the account's shared
# session.
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 3600


def scan_interval_seconds(data: Mapping[str, Any], options: Mapping[str, Any]) -> int:
    """Return the configured update interval, limited to the supported range.

    The options flow stores the interval in `options`; entries created before it
    existed keep the value from the setup form in `data`.
    """
    raw = options.get(CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL))
    try:
        seconds = int(raw)
    except TypeError, ValueError:
        return DEFAULT_SCAN_INTERVAL
    return min(max(seconds, MIN_SCAN_INTERVAL), MAX_SCAN_INTERVAL)


def account_key(username: str) -> str:
    """Return the key that identifies a SEMS account."""
    return username.strip().casefold()


# Serial that releases up to 11.12.0-beta.6 used for every station without a
# HomeKit/smart meter serial, which made the unique IDs collide across stations.
HOMEKIT_NO_SERIAL = "GW-HOMEKIT-NO-SERIAL"
# Device identifier that releases up to 11.12.0-beta.6 shared across stations.
LEGACY_HOMEKIT_DEVICE_ID = "homeKit"


def homekit_station_serial(station_id: str) -> str:
    """Return the powerflow serial for a station without a HomeKit serial."""
    return f"{station_id}-powerflow"


def homekit_device_id(station_id: str) -> str:
    """Return the identifier of a station's HomeKit/powerflow device."""
    return f"{station_id}-homekit"


AC_EMPTY = 6553.5
AC_CURRENT_EMPTY = 6553.5
AC_FEQ_EMPTY = 655.35


STATUS_LABELS = {
    -1: "Offline",
    0: "Waiting",
    1: "Normal",
    2: "Fault",
    3: "Waiting",
    5: "Normal",
}
GRID_STATUS_LABELS = {-1: "Offline", 0: "Waiting", 1: "Normal", 2: "Fault"}
INVERTER_ON_STATUSES = frozenset(
    status for status, label in STATUS_LABELS.items() if label == "Normal"
)


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


_SENSITIVE_LOG_KEYS = {
    "account",
    "pwd",
    "password",
    "token",
    "uid",
    "sn",
    "serialnum",
    "relationid",
    "relation_id",
    "pw_id",
    "powerstation_id",
    "owner_email",
    "owner_name",
    "owner_phone",
}

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SERIAL_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]{12,20}$")


def _matches_sensitive_pattern(value: str) -> bool:
    """Return whether a string looks sensitive by format."""
    return bool(
        _EMAIL_PATTERN.fullmatch(value)
        or _UUID_PATTERN.fullmatch(value)
        or _SERIAL_PATTERN.fullmatch(value)
    )


def _is_sensitive_label(key: Any) -> bool:
    """Return whether a dictionary key implies its value is sensitive."""
    return isinstance(key, str) and key.lower() in _SENSITIVE_LOG_KEYS


def _redact_sensitive_value(value: Any) -> Any:
    """Redact a value associated with a sensitive key."""
    if isinstance(value, str):
        return redact_value(value)

    if isinstance(value, dict):
        return {
            key: _redact_sensitive_value(sub_value) for key, sub_value in value.items()
        }

    if isinstance(value, list):
        return [_redact_sensitive_value(item) for item in value]

    # For non-string, non-container types (numbers, booleans, None, etc.), keep as-is
    return value


def redact_for_log(value: Any) -> Any:
    """Return a redacted structure suitable for debug logging."""
    if isinstance(value, str):
        return redact_value(value) if _matches_sensitive_pattern(value) else value

    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, sub_value in value.items():
            if isinstance(key, str) and _matches_sensitive_pattern(key):
                sanitized[redact_value(key)] = _redact_sensitive_value(sub_value)
            elif _is_sensitive_label(key):
                sanitized[key] = _redact_sensitive_value(sub_value)
            else:
                sanitized[key] = redact_for_log(sub_value)
        return sanitized

    if isinstance(value, list):
        return [redact_for_log(item) for item in value]

    # Handle dataclass instances by converting to dict and recursing
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return redact_for_log(dataclasses.asdict(value))

    return value

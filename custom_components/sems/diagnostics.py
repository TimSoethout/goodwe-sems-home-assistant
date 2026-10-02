"""Diagnostics support for the GoodWe SEMS integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import SemsConfigEntry
from .const import CONF_STATION_ID

TO_REDACT = {
    CONF_PASSWORD,
    CONF_STATION_ID,
    CONF_USERNAME,
    "email",
    "model_type",
    "name",
    "powerstation_id",
    "pwId",
    "sn",
    "stationId",
    "token",
    "uid",
}


def _collect_serials(value: Any, serials: set[str]) -> None:
    """Collect serial numbers from `sn` fields at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "sn" and isinstance(item, str) and item:
                serials.add(item)
            else:
                _collect_serials(item, serials)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_serials(item, serials)


def _replace_serials(value: Any, placeholders: dict[str, str]) -> Any:
    """Replace serials used as keys or values; make sets JSON friendly."""
    if isinstance(value, dict):
        return {
            placeholders.get(key, key) if isinstance(key, str) else key: (
                _replace_serials(item, placeholders)
            )
            for key, item in value.items()
        }
    if isinstance(value, (set, frozenset)):
        return sorted(_replace_serials(item, placeholders) for item in value)
    if isinstance(value, (list, tuple)):
        return [_replace_serials(item, placeholders) for item in value]
    if isinstance(value, str):
        return placeholders.get(value, value)
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SemsConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    del hass
    coordinator = entry.runtime_data.coordinator
    data = asdict(coordinator.data) if coordinator.data is not None else {}

    serials: set[str] = set(data.get("inverters") or {})
    _collect_serials(data, serials)
    placeholders = {
        serial: f"**REDACTED_DEVICE_{index}**"
        for index, serial in enumerate(sorted(serials), start=1)
    }

    return {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "data": async_redact_data(_replace_serials(data, placeholders), TO_REDACT),
    }

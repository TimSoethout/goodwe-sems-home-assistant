"""Diagnostics support for SEMS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import SemsDataUpdateCoordinator
from .const import DOMAIN

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "sn", "powerstation_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SemsDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Build coordinator state info
    coordinator_info = {
        "is_night": coordinator._is_night,
        "night_mode_enabled": coordinator._night_mode_enabled,
        "night_interval": coordinator._night_interval,
        "midnight_skip_enabled": coordinator._midnight_skip_enabled,
        "in_midnight_skip": coordinator._in_midnight_skip,
        "stale_threshold": coordinator._stale_threshold,
        "is_stale": coordinator.is_stale,
        "data_age_seconds": round(coordinator.data_age_seconds, 1),
        "last_successful_fetch": coordinator._last_successful_fetch,
        "last_detailed_fetch": coordinator._last_detailed_fetch,
        "update_interval_seconds": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
    }

    # Get current data
    data_info = {}
    if coordinator.data:
        data_info = {
            "inverter_count": len(coordinator.data.inverters),
            "inverter_sns": list(coordinator.data.inverters.keys()),
            "has_homekit": coordinator.data.homekit is not None,
            "currency": coordinator.data.currency,
            "last_updated": coordinator.data.last_updated,
        }

        # Add inverter status info (redacted)
        inverter_statuses = {}
        for sn, inv_data in coordinator.data.inverters.items():
            inverter_statuses[sn] = {
                "status": inv_data.get("status"),
                "pac": inv_data.get("pac"),
                "eday": inv_data.get("eday"),
                "etotal": inv_data.get("etotal"),
            }
        data_info["inverter_statuses"] = inverter_statuses

        # Add homekit/powerflow info if available
        if coordinator.data.homekit:
            powerflow = coordinator.data.homekit
            data_info["powerflow"] = {
                "pv": powerflow.get("pv"),
                "load": powerflow.get("load"),
                "grid": powerflow.get("grid"),
                "gridStatus": powerflow.get("gridStatus"),
                "battery": powerflow.get("bettery"),
                "batteryStatus": powerflow.get("betteryStatus"),
                "soc": powerflow.get("soc"),
            }

    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "data": dict(entry.data),
            },
            "coordinator": coordinator_info,
            "data": data_info,
        },
        TO_REDACT,
    )

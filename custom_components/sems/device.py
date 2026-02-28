"""Device helpers for the SEMS integration."""

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, GOODWE_SPELLING


def device_info_for_inverter(
    serial_number: str, inverter_data: dict[str, Any]
) -> DeviceInfo:
    """Build device info for an inverter.

    This is shared across platforms (sensor, switch, etc.) so entities for the
    same inverter are grouped under the same device and show a consistent name.
    """

    name = inverter_data.get("name") or serial_number

    # NOTE: We intentionally keep fallbacks here because not every SEMS payload
    # is guaranteed to contain `model_type`, `firmwareversion`, etc.
    return DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=f"Inverter {name}",
        manufacturer="GoodWe",
        model=inverter_data.get("model_type", "unknown"),
        sw_version=inverter_data.get("firmwareversion", "unknown"),
        configuration_url=(
            f"https://semsportal.com/PowerStation/PowerStatusSnMin/"
            f"{inverter_data.get('powerstation_id')}"
            if inverter_data.get("powerstation_id")
            else None
        ),
    )


def device_info_for_ev_charger(
    serial_number: str, ev_charger_data: dict[str, Any]
) -> DeviceInfo:
    """Build device info for an EV charger.

    Groups EV charger entities under the same device with a consistent name.
    """

    name = ev_charger_data.get("name") or serial_number

    return DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=f"EV Charger {name}",
        manufacturer="GoodWe",
        model=ev_charger_data.get("model") or "unknown",
        sw_version=ev_charger_data.get(GOODWE_SPELLING.firmware) or "unknown",
    )

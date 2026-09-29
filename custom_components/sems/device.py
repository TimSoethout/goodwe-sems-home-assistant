"""Device helpers for the SEMS integration."""

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, LEGACY_HOMEKIT_DEVICE_ID, homekit_device_id


def device_info_for_homekit(station_id: str | None) -> DeviceInfo:
    """Build device info for a station's HomeKit/powerflow sensors.

    The identifier is scoped to the station, so each station of a multi-station
    account gets its own device.
    """
    identifier = (
        homekit_device_id(station_id) if station_id else LEGACY_HOMEKIT_DEVICE_ID
    )
    return DeviceInfo(
        identifiers={(DOMAIN, identifier)},
        name="HomeKit",
        manufacturer="GoodWe",
    )


def device_info_for_inverter(
    serial_number: str, inverter_data: dict[str, Any]
) -> DeviceInfo:
    """Build device info for an inverter.

    This is shared across platforms (sensor, switch, etc.) so entities for the
    same inverter are grouped under the same device and show a consistent name.
    """

    name = inverter_data.get("name") or serial_number

    firmware_version = inverter_data.get("firmwareversion")
    if firmware_version in (None, ""):
        sw_version = "unknown"
    else:
        sw_version = str(firmware_version)

    # NOTE: We intentionally keep fallbacks here because not every SEMS payload
    # is guaranteed to contain `model_type`, `firmwareversion`, etc.
    return DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=f"Inverter {name}",
        manufacturer="GoodWe",
        model=inverter_data.get("model_type", "unknown"),
        sw_version=sw_version,
        configuration_url=(
            f"https://semsportal.com/PowerStation/PowerStatusSnMin/"
            f"{inverter_data.get('powerstation_id')}"
            if inverter_data.get("powerstation_id")
            else None
        ),
    )

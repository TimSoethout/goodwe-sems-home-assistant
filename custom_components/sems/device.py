"""Device helpers for the SEMS integration."""

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

SEMS_PLUS_URL = "https://semsplus.goodwe.com/"

# SEMS+ reports data loggers and battery racks in the same device list as
# inverters. They share the inverter entities but are not inverters.
_INVERTER_DEVICE_TYPES = {"INVERTER", "ENERGY_STORAGE_INTEGRATED_CABINET"}
_NON_INVERTER_DEVICE_LABELS = {
    "DONGLE": "Dongle",
    "BATTERY_RACK": "Battery Rack",
}
_SERIAL_SUFFIX_LENGTH = 4


def is_inverter(inverter_data: dict[str, Any]) -> bool:
    """Return whether the device is an inverter that accepts inverter commands.

    Data without a SEMS+ ``deviceType`` comes from the inverter list and is
    treated as an inverter.
    """
    device_type = inverter_data.get("deviceType")
    return device_type is None or device_type in _INVERTER_DEVICE_TYPES


def _device_name(serial_number: str, inverter_data: dict[str, Any]) -> str:
    name = str(inverter_data.get("name") or serial_number)
    label = _NON_INVERTER_DEVICE_LABELS.get(str(inverter_data.get("deviceType")))
    if label is None:
        return f"Inverter {name}"
    if not name.casefold().startswith(label.casefold()):
        name = f"{label} {name}"
    if inverter_data.get("deviceType") == "DONGLE" and serial_number not in name:
        # SEMS+ names every station's data logger "Dongle 1"; add the end of
        # the serial number so dongles of different stations can be told apart.
        name = f"{name} ({serial_number[-_SERIAL_SUFFIX_LENGTH:]})"
    return name


def device_info_for_inverter(
    serial_number: str, inverter_data: dict[str, Any]
) -> DeviceInfo:
    """Build device info for an inverter.

    This is shared across platforms (sensor, switch, etc.) so entities for the
    same inverter are grouped under the same device and show a consistent name.
    """

    firmware_version = inverter_data.get("firmwareversion")
    if firmware_version in (None, ""):
        sw_version = "unknown"
    else:
        sw_version = str(firmware_version)

    label = _NON_INVERTER_DEVICE_LABELS.get(str(inverter_data.get("deviceType")))

    # NOTE: We intentionally keep fallbacks here because not every SEMS payload
    # is guaranteed to contain `model_type`, `firmwareversion`, etc.
    return DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=_device_name(serial_number, inverter_data),
        manufacturer="GoodWe",
        # SEMS+ has no model for dongles and battery racks; the derived
        # `model_type` would only repeat the device name.
        model=label or inverter_data.get("model_type", "unknown"),
        sw_version=sw_version,
        # The legacy SEMS portal has been shut down.
        configuration_url=SEMS_PLUS_URL,
    )

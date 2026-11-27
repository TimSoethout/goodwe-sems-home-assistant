"""Pure normalization helpers for SEMS+ Web device records."""

from typing import Any


def normalize_battery_rack(device_data: dict[str, Any]) -> dict[str, Any]:
    """Move flat battery-rack factors into the legacy battery rollup shape."""
    battery_data = {
        key: device_data.pop(key)
        for key in (
            "pbattery",
            "vbattery",
            "ibattery",
            "soc",
            "soh",
            "bms_temperature",
            "bms_charge_i_max",
            "bms_discharge_i_max",
        )
        if key in device_data
    }
    if battery_data:
        device_data["battery_count"] = 1
        device_data["more_batterys"] = [battery_data]
    return device_data

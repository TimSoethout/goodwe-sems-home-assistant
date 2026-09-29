"""Tests for SEMS device helpers."""

from custom_components.sems.device import device_info_for_inverter, is_inverter


def test_device_info_sw_version_is_string_for_numeric_firmware() -> None:
    """Numeric firmware versions should be converted to strings."""
    device_info = device_info_for_inverter(
        "GW0000SN000TEST1",
        {"name": "Test Inverter", "model_type": "GW3000-NS", "firmwareversion": 1717.0},
    )

    assert device_info["sw_version"] == "1717.0"
    assert isinstance(device_info["sw_version"], str)


def test_device_info_sw_version_defaults_to_unknown_for_missing_firmware() -> None:
    """Missing firmware versions should use a string fallback."""
    device_info = device_info_for_inverter(
        "GW0000SN000TEST1",
        {"name": "Test Inverter", "model_type": "GW3000-NS"},
    )

    assert device_info["sw_version"] == "unknown"


def test_device_info_links_to_sems_plus() -> None:
    """The legacy SEMS portal is closed; link devices to SEMS+."""
    device_info = device_info_for_inverter(
        "GW0000SN000TEST1",
        {"name": "Test Inverter", "powerstation_id": "station"},
    )

    assert device_info["configuration_url"] == "https://semsplus.goodwe.com/"
    assert device_info["name"] == "Inverter Test Inverter"


def test_device_info_names_dongle_after_type_and_serial() -> None:
    """Generic dongle names get the serial suffix to stay distinguishable."""
    device_info = device_info_for_inverter(
        "GW0000SN000TEST2",
        {"name": "Dongle 1", "deviceType": "DONGLE", "model_type": "Dongle 1"},
    )

    assert device_info["name"] == "Dongle 1 (EST2)"
    assert device_info["model"] == "Dongle"


def test_device_info_prefixes_renamed_dongle() -> None:
    """A dongle renamed in SEMS+ keeps its name with the device type."""
    device_info = device_info_for_inverter(
        "GW0000SN000TEST2",
        {"name": "Garage", "deviceType": "DONGLE"},
    )

    assert device_info["name"] == "Dongle Garage (EST2)"


def test_device_info_names_battery_rack() -> None:
    """Battery racks are not named as inverters."""
    device_info = device_info_for_inverter(
        "GW0000SN000TEST3",
        {"name": "GW0000SN000TEST3", "deviceType": "BATTERY_RACK"},
    )

    assert device_info["name"] == "Battery Rack GW0000SN000TEST3"
    assert device_info["model"] == "Battery Rack"


def test_is_inverter() -> None:
    """Only real inverters, or data without a SEMS+ device type, are inverters."""
    assert is_inverter({})
    assert is_inverter({"deviceType": "INVERTER"})
    assert is_inverter({"deviceType": "ENERGY_STORAGE_INTEGRATED_CABINET"})
    assert not is_inverter({"deviceType": "DONGLE"})
    assert not is_inverter({"deviceType": "BATTERY_RACK"})

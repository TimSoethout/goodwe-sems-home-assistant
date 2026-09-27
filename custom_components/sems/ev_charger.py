"""GoodWe EV charger (e.g. HCA wallbox) entities controlled through SEMS+ Web."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SemsCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# `chargeLog.workStu` values from the SEMS+ Web UI.
EV_CHARGER_STATUS_LABELS = {
    0: "Offline",
    2: "Fault",
    6: "Charging",
    8: "Available",
    9: "Maintenance",
    10: "Available",
}
_EV_CHARGER_CHARGING_STATUS = 6

# SEMS+ charge modes, as listed by the Web UI mode selector.
EV_CHARGE_MODES = {0: "fast", 1: "pv", 2: "pv_battery"}

# Unit -> (device class, HA unit, state class) for dynamic factor sensors.
_UNIT_MAP: dict[str, tuple[SensorDeviceClass | None, str, SensorStateClass]] = {
    "w": (SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
    "kw": (
        SensorDeviceClass.POWER,
        UnitOfPower.KILO_WATT,
        SensorStateClass.MEASUREMENT,
    ),
    "wh": (
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.WATT_HOUR,
        SensorStateClass.TOTAL_INCREASING,
    ),
    "kwh": (
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorStateClass.TOTAL_INCREASING,
    ),
    "v": (
        SensorDeviceClass.VOLTAGE,
        UnitOfElectricPotential.VOLT,
        SensorStateClass.MEASUREMENT,
    ),
    "a": (
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
        SensorStateClass.MEASUREMENT,
    ),
    "hz": (
        SensorDeviceClass.FREQUENCY,
        UnitOfFrequency.HERTZ,
        SensorStateClass.MEASUREMENT,
    ),
    "℃": (
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
    ),
    "°c": (
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
    ),
    "%": (None, PERCENTAGE, SensorStateClass.MEASUREMENT),
}


def device_info_for_ev_charger(
    serial_number: str, charger: dict[str, Any]
) -> DeviceInfo:
    """Build device info for an EV charger."""
    model = (charger.get("mode_info") or {}).get("productModel") or charger.get(
        "subtype"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=f"EV Charger {charger.get('name') or serial_number}",
        manufacturer="GoodWe",
        model=model or "EV Charger",
        serial_number=serial_number,
    )


def _factor_name(code: str, alias: str) -> str:
    """Return a readable entity name for a SEMS+ factor."""
    text = alias if alias and alias != code else code
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text.replace(":", " "))
    return " ".join(part.capitalize() for part in re.split(r"[_\s-]+", text) if part)


class _EvChargerEntity(CoordinatorEntity[SemsCoordinator]):
    """Base entity for an EV charger."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SemsCoordinator, serial_number: str, key: str
    ) -> None:
        super().__init__(coordinator)
        self.serial_number = serial_number
        self._attr_unique_id = f"{serial_number}-ev-{key}"
        self._attr_device_info = device_info_for_ev_charger(
            serial_number, self._charger
        )

    @property
    def _charger(self) -> dict[str, Any]:
        return (self.coordinator.data.ev_chargers or {}).get(self.serial_number, {})

    @property
    def _work_status(self) -> int | None:
        try:
            return int(self._charger.get("charge_log", {}).get("workStu"))
        except (TypeError, ValueError):
            return None

    @property
    def _mode(self) -> int | None:
        # The current mode is reported by ev-charger/detail; fall back to the
        # mode settings response for older data.
        for source in ("detail", "mode_info"):
            value = self._charger.get(source, {}).get("chargeMode")
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    async def _async_command(self, method: Any, *args: Any) -> None:
        mode_info = self._charger.get("mode_info", {})
        product_model = mode_info.get("productModel")
        if not product_model:
            raise HomeAssistantError(
                f"Unable to control {self.entity_id}: charger model is unknown"
            )
        if not await self.hass.async_add_executor_job(
            method,
            self.coordinator.station_id,
            self.serial_number,
            product_model,
            *args,
        ):
            raise HomeAssistantError(f"SEMS rejected the command for {self.entity_id}")
        await self.coordinator.async_request_refresh()


class EvChargerStatusSensor(_EvChargerEntity, SensorEntity):
    """Charger working status (available, charging, fault, ...)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = sorted({*EV_CHARGER_STATUS_LABELS.values(), "Unknown"})

    def __init__(self, coordinator: SemsCoordinator, serial_number: str) -> None:
        super().__init__(coordinator, serial_number, "status")
        self._attr_name = "Status"

    @property
    def native_value(self) -> str | None:
        status = self._work_status
        if status is None:
            return None
        return EV_CHARGER_STATUS_LABELS.get(status, "Unknown")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        charge_log = self._charger.get("charge_log", {})
        return {
            "work_status_code": charge_log.get("workStu"),
            "plug_status_code": charge_log.get("status"),
        }


class EvChargerFactorSensor(_EvChargerEntity, SensorEntity):
    """Numeric SEMS+ telemetry/telecounting value of a charger."""

    def __init__(
        self,
        coordinator: SemsCoordinator,
        serial_number: str,
        code: str,
        factor: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, serial_number, code)
        self._code = code
        self._attr_name = _factor_name(code, factor.get("alias", code))
        unit = str(factor.get("unit") or "").strip()
        if mapped := _UNIT_MAP.get(unit.lower()):
            device_class, native_unit, state_class = mapped
            self._attr_device_class = device_class
            self._attr_native_unit_of_measurement = native_unit
            self._attr_state_class = state_class
        elif unit:
            self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float | None:
        factor = self._charger.get("factors", {}).get(self._code)
        return factor.get("value") if factor else None


class EvChargerChargingSwitch(_EvChargerEntity, SwitchEntity):
    """Start or stop charging."""

    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: SemsCoordinator, serial_number: str) -> None:
        super().__init__(coordinator, serial_number, "charging")
        self._attr_name = "Charging"

    @property
    def is_on(self) -> bool | None:
        status = self._work_status
        return None if status is None else status == _EV_CHARGER_CHARGING_STATUS

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_command(
            self.coordinator.sems_api.startEvCharging, self._mode or 0
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_command(
            self.coordinator.sems_api.stopEvCharging, self._mode or 0
        )


class EvChargeModeSelect(_EvChargerEntity, SelectEntity):
    """Charge mode: fast, PV only, or PV and battery."""

    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator: SemsCoordinator, serial_number: str) -> None:
        super().__init__(coordinator, serial_number, "charge-mode")
        self._attr_name = "Charge Mode"
        self._attr_options = list(EV_CHARGE_MODES.values())

    @property
    def current_option(self) -> str | None:
        mode = self._mode
        return None if mode is None else EV_CHARGE_MODES.get(mode)

    async def async_select_option(self, option: str) -> None:
        mode = next(key for key, value in EV_CHARGE_MODES.items() if value == option)
        await self._async_command(
            self.coordinator.sems_api.setEvChargeMode,
            mode,
            self._charger.get("detail", {}),
        )


# "More Control" switches: detail field -> name (sent as 0/1 like the Web UI).
EV_CHARGER_CONFIG_SWITCHES = {
    "ensureMinimumChargingPower": "Min Charging Power",
    "gridControlLimitSwitch": "Grid Compliance Limit",
    "dynamicLoad": "Dynamic Load Management",
    "phaseSwitch": "Single/Three-phase Switching",
    "lockChargingPlug": "Lock Charging Plug",
}

# "More Control" numbers: detail field -> (name, unit, SEMS range key, step).
EV_CHARGER_CONFIG_NUMBERS: dict[str, tuple[str, str, str | None, float]] = {
    "ratedMaxiChargePower": ("Output Power Limit", UnitOfPower.KILO_WATT, None, 0.1),
    "buyPwrLimit": (
        "Max Import Power Limit",
        UnitOfPower.KILO_WATT,
        "Buy_Pwr_Limit",
        0.1,
    ),
    "gridControlLimitValue": (
        "Grid Compliance Limit Value",
        UnitOfPower.KILO_WATT,
        "Grid_Control_Limit_Value",
        0.1,
    ),
    "currentLimit": (
        "Dynamic Load Import Current Limit",
        UnitOfElectricCurrent.AMPERE,
        "charge_pile_dynamic_load_import_current_limit",
        1,
    ),
}


class EvChargerConfigSwitch(_EvChargerEntity, SwitchEntity):
    """Toggle one EV charger "More Control" setting."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: SemsCoordinator, serial_number: str, field: str
    ) -> None:
        super().__init__(coordinator, serial_number, f"config-{field}")
        self._field = field
        self._attr_name = EV_CHARGER_CONFIG_SWITCHES[field]

    @property
    def is_on(self) -> bool | None:
        value = self._charger.get("detail", {}).get(self._field)
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_command(
            self.coordinator.sems_api.setEvChargerConfig, self._field, 1
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_command(
            self.coordinator.sems_api.setEvChargerConfig, self._field, 0
        )


class EvChargerConfigNumber(_EvChargerEntity, NumberEntity):
    """Set one numeric EV charger "More Control" setting."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: SemsCoordinator, serial_number: str, field: str
    ) -> None:
        super().__init__(coordinator, serial_number, f"config-{field}")
        self._field = field
        name, unit, range_key, step = EV_CHARGER_CONFIG_NUMBERS[field]
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_native_step = step
        self._attr_device_class = (
            NumberDeviceClass.CURRENT
            if unit == UnitOfElectricCurrent.AMPERE
            else NumberDeviceClass.POWER
        )
        self._attr_native_min_value, self._attr_native_max_value = self._range(
            range_key, unit
        )

    def _range(self, range_key: str | None, unit: str) -> tuple[float, float]:
        """Return the allowed range like the Web UI does."""
        mode_info = self._charger.get("mode_info", {})
        try:
            rated = float(mode_info.get("ratedPower") or 0)
        except (TypeError, ValueError):
            rated = 0.0
        if not rated:
            rated = 22.0
        if range_key is None:
            # Output power: 1.4 kW minimum for single-phase 7 kW chargers,
            # 4.2 kW for three-phase 11/22 kW ones.
            return (1.4 if rated == 7 else 4.2 if rated in (11, 22) else 0.0), rated
        ranges = (mode_info.get("controlItemRanges") or {}).get(range_key) or {}
        default_max = 63.0 if unit == UnitOfElectricCurrent.AMPERE else max(rated, 22.0)
        try:
            return float(ranges.get("min", 0)), float(ranges.get("max", default_max))
        except (TypeError, ValueError):
            return 0.0, default_max

    @property
    def native_value(self) -> float | None:
        value = self._charger.get("detail", {}).get(self._field)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._async_command(
            self.coordinator.sems_api.setEvChargerConfig,
            self._field,
            int(value) if self._attr_native_step == 1 else round(value, 1),
        )


def ev_charger_numbers(coordinator: SemsCoordinator) -> list[NumberEntity]:
    """Return "More Control" numbers reported by each charger."""
    return [
        EvChargerConfigNumber(coordinator, serial_number, field)
        for serial_number, charger in (coordinator.data.ev_chargers or {}).items()
        for field in EV_CHARGER_CONFIG_NUMBERS
        if charger.get("detail", {}).get(field) is not None
    ]


def ev_charger_sensors(coordinator: SemsCoordinator) -> list[SensorEntity]:
    """Return sensor entities for all discovered EV chargers."""
    sensors: list[SensorEntity] = []
    for serial_number, charger in (coordinator.data.ev_chargers or {}).items():
        sensors.append(EvChargerStatusSensor(coordinator, serial_number))
        for code, factor in charger.get("factors", {}).items():
            sensors.append(
                EvChargerFactorSensor(coordinator, serial_number, code, factor)
            )
    return sensors


def ev_charger_switches(coordinator: SemsCoordinator) -> list[SwitchEntity]:
    """Return charging switches for all discovered EV chargers."""
    switches: list[SwitchEntity] = []
    for serial_number, charger in (coordinator.data.ev_chargers or {}).items():
        switches.append(EvChargerChargingSwitch(coordinator, serial_number))
        switches.extend(
            EvChargerConfigSwitch(coordinator, serial_number, field)
            for field in EV_CHARGER_CONFIG_SWITCHES
            if charger.get("detail", {}).get(field) is not None
        )
    return switches


def ev_charger_selects(coordinator: SemsCoordinator) -> list[SelectEntity]:
    """Return charge mode selects for all discovered EV chargers."""
    return [
        EvChargeModeSelect(coordinator, serial_number)
        for serial_number in coordinator.data.ev_chargers or {}
    ]

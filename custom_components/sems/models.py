"""Typed domain and adapter records for the SEMS integration."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RawStationData:
    """Raw endpoint state assembled for one station refresh."""

    devices: tuple[dict[str, Any], ...]
    flow: dict[str, Any]
    flow_unavailable: bool
    device_inventory_unavailable: bool


@dataclass(frozen=True, slots=True)
class ParsedDeviceRecord:
    """One parsed SEMS+ device and its source availability."""

    serial_number: str
    device_type: str
    data: dict[str, Any]
    unavailable_sources: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ParsedStationData:
    """Parsed station devices before legacy-envelope assembly."""

    devices: tuple[ParsedDeviceRecord, ...]
    ev_chargers: dict[str, dict[str, Any]]
    unavailable_inverter_sources: dict[str, set[str]] = field(default_factory=dict)
    unavailable_homekit_sources: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class SemsData:
    """Runtime SEMS data returned by the coordinator."""

    inverters: dict[str, dict[str, Any]]
    batteries: dict[str, dict[str, dict[str, Any]]] | None = None
    immediate_charging: dict[str, dict[str, Any]] | None = None
    homekit: dict[str, Any] | None = None
    currency: str | None = None
    ev_chargers: dict[str, dict[str, Any]] | None = None
    unavailable_inverter_sources: dict[str, set[str]] = field(default_factory=dict)
    unavailable_homekit_sources: set[str] = field(default_factory=set)

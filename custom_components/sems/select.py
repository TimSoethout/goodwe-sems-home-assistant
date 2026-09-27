"""Select entities for the GoodWe SEMS integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .ev_charger import ev_charger_selects


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEMS select entities from a config entry."""
    async_add_entities(ev_charger_selects(config_entry.runtime_data.coordinator))

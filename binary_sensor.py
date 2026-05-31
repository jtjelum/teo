"""TEO binary_sensor-platform.

Eksponerer systemtilstande som til/fra-sensorer. Vigtigst: om TEO kører på
den regelbaserede fallback (designprincip #6) — synligt for brugeren.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TEOBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TEOFallbackActiveBinarySensor(coordinator)])


class TEOFallbackActiveBinarySensor(TEOBaseEntity, BinarySensorEntity):
    """Tændt når optimeringen er utilgængelig og regelmotoren styrer."""

    _attr_name = "Fallback aktiv"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:shield-alert"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "fallback_active")

    @property
    def is_on(self) -> bool:
        return bool(self.data.get("fallback_active"))

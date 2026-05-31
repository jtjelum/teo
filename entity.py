"""Fælles base for alle TEO-entiteter.

Knytter entiteterne til coordinatoren (push-opdatering) og samler dem under én
HA-enhed ("TEO") identificeret ved installations-ID'et.
"""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_NAME, TEO_VERSION
from .coordinator import TEODataUpdateCoordinator


class TEOBaseEntity(CoordinatorEntity[TEODataUpdateCoordinator]):
    """Basisklasse: device-info + unik-ID-konvention for alle TEO-entiteter."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TEODataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        install_id = coordinator.config.installation_id or coordinator.entry.entry_id
        self._attr_unique_id = f"{install_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, install_id)},
            name=INTEGRATION_NAME,
            manufacturer="Tjelum",
            model="Tjelums Energy Optimisation",
            sw_version=TEO_VERSION,
        )

    @property
    def data(self) -> dict:
        """Genvej til coordinatorens seneste datasæt (aldrig None efter setup)."""
        return self.coordinator.data or {}

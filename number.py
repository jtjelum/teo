"""TEO number-platform — konfigurerbare parametre med write-back.

To regulatorer under "Batteristyring" i dashboardet:

* ``number.teo_batteri_minimum_soc`` — minimum-SOC (5-50 %, trin 5). Skrives til
  teo_config.yaml og respekteres straks af LP-optimizeren (gulv for batteriet).
* ``number.teo_enphase_reserve_soc`` — manuel Envoy-reserve (5-95 %). Skrives
  direkte til Envoy via den pålidelige opt_schedules=false-vej.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ENPHASE_RESERVE_MAX,
    ENPHASE_RESERVE_MIN,
    ENPHASE_RESERVE_STEP,
    MIN_SOC_SELECTABLE_MAX,
    MIN_SOC_SELECTABLE_MIN,
    MIN_SOC_SELECTABLE_STEP,
)
from .entity import TEOBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        TEOMinSocNumber(coordinator),
        TEOEnphaseReserveNumber(coordinator),
    ])


class TEOMinSocNumber(TEOBaseEntity, NumberEntity):
    """Minimum-SOC — gulv brugt af LP-optimizeren (skrives til config)."""

    _attr_name = "Batteri minimum-SOC"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = MIN_SOC_SELECTABLE_MIN
    _attr_native_max_value = MIN_SOC_SELECTABLE_MAX
    _attr_native_step = MIN_SOC_SELECTABLE_STEP
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "battery_minimum_soc")
        self.entity_id = "number.teo_batteri_minimum_soc"

    @property
    def native_value(self) -> float:
        return float(self.coordinator.config.min_soc_pct)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.set_min_soc(value)
        self.async_write_ha_state()


class TEOEnphaseReserveNumber(TEOBaseEntity, NumberEntity):
    """Manuel Envoy-reserve — skriver tariffen med opt_schedules=false."""

    _attr_name = "Enphase reserve-SOC"
    _attr_icon = "mdi:battery-lock"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = ENPHASE_RESERVE_MIN
    _attr_native_max_value = ENPHASE_RESERVE_MAX
    _attr_native_step = ENPHASE_RESERVE_STEP
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "enphase_reserve_soc")
        self.entity_id = "number.teo_enphase_reserve_soc"

    @property
    def native_value(self) -> float:
        # Read from config (persisted value)
        rsv = self.coordinator.config.raw.get("battery", {}).get("reserve_soc_percent")
        if rsv is not None:
            return float(rsv)
        # Fallback to last actuation
        rsv = (self.coordinator.last_actuation or {}).get("reserved_soc")
        if rsv is not None:
            return float(rsv)
        # Final fallback to min_soc
        return float(self.coordinator.config.min_soc_pct)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.set_reserve_soc(value)
        self.async_write_ha_state()

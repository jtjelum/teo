"""Enphase batteri-aktuering via HA entity services (firmware 8.x kompatibel).

Fra firmware 8.2.4225 ignorerer Envoy direkte tariff API-kald. Denne module
bruger i stedet HA's officielle Enphase integration services som virker på
alle firmware-versioner:
  - select.select_option → storage mode (backup / self_consumption)
  - number.set_value     → reserve battery level
  - switch.turn_on/off   → charge from grid

Kun to modes bruges (savings virker ikke via HA services på firmware 8.x):
  - self_consumption: Enphase oplader batteriet fra sol og net
  - backup:           Enphase holder batteriet på reserve-niveau (stop opladning)

Brugt af coordinator._actuate() og _ev_protection_check().
"""

from __future__ import annotations

import logging
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

# Enphase entity IDs — faste for denne installation
_STORAGE_MODE_ENTITY   = "select.envoy_122328094789_storage_mode"
_RESERVE_LEVEL_ENTITY  = "number.envoy_122328094789_reserve_battery_level"
_CHARGE_FROM_GRID_ENTITY = "switch.envoy_122328094789_charge_from_grid"

# Gyldige modes der virker på firmware 8.x
MODE_SELF_CONSUMPTION = "self_consumption"
MODE_BACKUP           = "backup"


class EnphaseBatteryActuator:
    """Skriver Envoy batteri-indstillinger via HA entity services."""

    def __init__(self, hass) -> None:
        self.hass = hass

    def available(self) -> bool:
        """Returnerer True hvis Enphase entiteterne er tilgængelige."""
        st = self.hass.states.get(_STORAGE_MODE_ENTITY)
        return st is not None and st.state not in ("unavailable", "unknown")

    async def current_state(self) -> Optional[dict[str, Any]]:
        """Læs nuværende Enphase storage state fra HA entities."""
        try:
            mode_st    = self.hass.states.get(_STORAGE_MODE_ENTITY)
            reserve_st = self.hass.states.get(_RESERVE_LEVEL_ENTITY)
            grid_st    = self.hass.states.get(_CHARGE_FROM_GRID_ENTITY)
            if mode_st is None:
                return None
            return {
                "mode":             mode_st.state,
                "reserved_soc":     float(reserve_st.state) if reserve_st else None,
                "charge_from_grid": grid_st.state == "on" if grid_st else False,
                # opt_schedules er ikke relevant for HA services — sæt altid False
                "opt_schedules":    False,
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Kunne ikke læse Enphase state: %s", err)
            return None

    async def apply(self, *,
                    reserve_pct: Optional[float] = None,
                    mode: Optional[str] = None,
                    charge_from_grid: Optional[bool] = None) -> dict[str, Any]:
        """Anvend batteri-indstillinger via HA entity services.

        mode-mapping (kun self_consumption og backup virker på firmware 8.x):
          ENPHASE_MODE_SELF_CONSUMPTION → self_consumption
          ENPHASE_MODE_BACKUP           → backup
          ENPHASE_MODE_SAVINGS          → self_consumption (savings virker ikke)
        """
        try:
            applied = False

            # Normalisér mode — savings findes ikke på firmware 8.x
            if mode == "savings":
                mode = MODE_SELF_CONSUMPTION

            # Sæt storage mode
            if mode is not None:
                ha_mode = MODE_BACKUP if mode == "backup" else MODE_SELF_CONSUMPTION
                await self.hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": _STORAGE_MODE_ENTITY, "option": ha_mode},
                    blocking=True)
                applied = True

            # Sæt reserve level
            if reserve_pct is not None:
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": _RESERVE_LEVEL_ENTITY,
                     "value": round(float(reserve_pct), 1)},
                    blocking=True)
                applied = True

            # Sæt charge from grid
            if charge_from_grid is not None:
                service = "turn_on" if charge_from_grid else "turn_off"
                await self.hass.services.async_call(
                    "switch", service,
                    {"entity_id": _CHARGE_FROM_GRID_ENTITY},
                    blocking=True)
                applied = True

            if applied:
                _LOGGER.info(
                    "Batteri-aktuering: mode=%s reserve=%.1f%% grid=%s",
                    mode, reserve_pct or 0, charge_from_grid)

            # Læs faktisk state efter skrivning
            state = await self.current_state() or {}
            return {
                "applied":        applied,
                "mode":           state.get("mode"),
                "reserved_soc":   state.get("reserved_soc"),
                "charge_from_grid": state.get("charge_from_grid"),
                "opt_schedules":  False,
            }

        except Exception as err:  # noqa: BLE001 — må aldrig vælte drift
            _LOGGER.warning("Batteri-aktuering fejlede: %s", err)
            return {"applied": False, "reason": str(err)}

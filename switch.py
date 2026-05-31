"""TEO switch-platform.

* ``switch.teo_automatik_aktiv`` — pause al aktiv styring (optimeringen kører
  stadig, men anvendes ikke på enheder).
* ``switch.teo_enphase_charge_from_grid`` — manuel netladning til/fra (skriver
  Envoy via opt_schedules=false).
* ``switch.teo_sell_at_negative_price`` — HÅRD LP-begrænsning: stop salg til net
  i timer med negativ spotpris.
* ``switch.teo_charge_from_grid_allowed`` — HÅRD LP-begrænsning: tillad/forbyd
  netladning af batteriet i optimeringen.

De to sidste persisteres i teo_config.yaml (sektion ``control``) og respekteres
som hårde grænser i LP'en — ikke vejledende.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([
        TEOAutomationSwitch(coordinator),
        TEOEnphaseChargeFromGridSwitch(coordinator),
        TEOSellAtNegativePriceSwitch(coordinator),
        TEOChargeFromGridAllowedSwitch(coordinator),
        TEOEVProtectionSwitch(coordinator),
    ])


class TEOAutomationSwitch(TEOBaseEntity, SwitchEntity):
    """Slår TEO's aktive styring til/fra (optimeringen kører altid)."""

    _attr_name = "Automatik aktiv"
    _attr_icon = "mdi:robot"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "automation_enabled")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.automation_enabled)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.automation_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.automation_enabled = False
        self.async_write_ha_state()


class TEOEnphaseChargeFromGridSwitch(TEOBaseEntity, SwitchEntity):
    """Manuel netladning af batteriet (skriver Envoy via opt_schedules=false)."""

    _attr_name = "Enphase netladning"
    _attr_icon = "mdi:transmission-tower-import"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "enphase_charge_from_grid")
        self.entity_id = "switch.teo_enphase_charge_from_grid"

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.last_actuation or {}).get("charge_from_grid"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.manual_actuate(charge_from_grid=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.manual_actuate(charge_from_grid=False)
        self.async_write_ha_state()


class TEOSellAtNegativePriceSwitch(TEOBaseEntity, SwitchEntity):
    """HÅRD LP-grænse: sælg overskud til net selv ved negativ pris (til = sælg)."""

    _attr_name = "Sælg ved negativ pris"
    _attr_icon = "mdi:cash-refund"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sell_at_negative_price")
        self.entity_id = "switch.teo_sell_at_negative_price"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.allow_negative_export)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_control(sell_at_negative=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_control(sell_at_negative=False)
        self.async_write_ha_state()


class TEOChargeFromGridAllowedSwitch(TEOBaseEntity, SwitchEntity):
    """HÅRD LP-grænse: tillad netladning af batteriet i optimeringen."""

    _attr_name = "Netladning tilladt"
    _attr_icon = "mdi:battery-charging-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "charge_from_grid_allowed")
        self.entity_id = "switch.teo_charge_from_grid_allowed"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.allow_grid_charge)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_control(grid_charge_allowed=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_control(grid_charge_allowed=False)
        self.async_write_ha_state()


class TEOEVProtectionSwitch(TEOBaseEntity, SwitchEntity):
    """EV lader kun fra sol og net (beskytter batteriet)."""

    _attr_name = "EV kun sol og net"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "ev_protection")
        self.entity_id = "switch.teo_ev_kun_sol_og_net"

    @property
    def is_on(self) -> bool:
        # When ON: EV only charges from solar+grid (battery protected)
        # This corresponds to ev_protection_soc being set to 100%
        return bool(self.coordinator.config.ev_protection_soc_pct >= 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Set ev_protection_soc to 100% (EV never uses battery)
        await self.coordinator.set_ev_protection(100)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Set ev_protection_soc to default (EV can use battery)
        await self.coordinator.set_ev_protection(30)
        self.async_write_ha_state()

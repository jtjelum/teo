"""TEO switch-platform.

* ``switch.teo_automatik_aktiv`` ??? pause al aktiv styring (optimeringen k??rer
  stadig, men anvendes ikke p?? enheder).
* ``switch.teo_enphase_charge_from_grid`` ??? manuel netladning til/fra (skriver
  Envoy via opt_schedules=false).
* ``switch.teo_sell_at_negative_price`` ??? H??RD LP-begr??nsning: stop salg til net
  i timer med negativ spotpris.
* ``switch.teo_charge_from_grid_allowed`` ??? H??RD LP-begr??nsning: tillad/forbyd
  netladning af batteriet i optimeringen.
* ``switch.teo_ev_kun_sol_og_net`` ??? EV lader kun fra sol og net (ikke batteri).
  S??tter Easee dynamic limit til 0A (ON=beskyt batteri, OFF=tillad batteri).

De to LP-begr??nsninger persisteres i teo_config.yaml (sektion ``control``) og
respekteres som h??rde gr??nser i LP'en ??? ikke vejledende.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TEOBaseEntity

_LOGGER = logging.getLogger(__name__)

# Easee charger IDs (master/slave p?? 20A kredsl??b)
EASEE_DEVICE_IDS = ["1aee5bbe2ace36ba9b2bf16ae5d8ba60", "f551d94994611181870c80b378f176a8"]
EASEE_MAX_CURRENT = 16  # A ??? normal ladning


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
    """Sl??r TEO's aktive styring til/fra (optimeringen k??rer altid)."""

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
        try:
            from . import user_settings
            from .const import USER_SETTING_CHARGE_FROM_GRID
            await self.hass.async_add_executor_job(
                user_settings.set_value, USER_SETTING_CHARGE_FROM_GRID, True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke gemme charge_from_grid: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.manual_actuate(charge_from_grid=False)
        try:
            from . import user_settings
            from .const import USER_SETTING_CHARGE_FROM_GRID
            await self.hass.async_add_executor_job(
                user_settings.set_value, USER_SETTING_CHARGE_FROM_GRID, False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke gemme charge_from_grid: %s", err)
        self.async_write_ha_state()


class TEOSellAtNegativePriceSwitch(TEOBaseEntity, SwitchEntity):
    """H??RD LP-gr??nse: s??lg overskud til net selv ved negativ pris (til = s??lg)."""

    _attr_name = "S??lg ved negativ pris"
    _attr_icon = "mdi:cash-refund"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sell_at_negative_price")
        self.entity_id = "switch.teo_sell_at_negative_price"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.allow_negative_export)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_control(sell_at_negative=True)
        try:
            from . import user_settings
            from .const import USER_SETTING_SELL_AT_NEGATIVE
            await self.hass.async_add_executor_job(
                user_settings.set_value, USER_SETTING_SELL_AT_NEGATIVE, True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke gemme sell_at_negative: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_control(sell_at_negative=False)
        try:
            from . import user_settings
            from .const import USER_SETTING_SELL_AT_NEGATIVE
            await self.hass.async_add_executor_job(
                user_settings.set_value, USER_SETTING_SELL_AT_NEGATIVE, False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke gemme sell_at_negative: %s", err)
        self.async_write_ha_state()


class TEOChargeFromGridAllowedSwitch(TEOBaseEntity, SwitchEntity):
    """H??RD LP-gr??nse: tillad netladning af batteriet i optimeringen."""

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
        try:
            from . import user_settings
            from .const import USER_SETTING_GRID_CHARGE_ALLOWED
            await self.hass.async_add_executor_job(
                user_settings.set_value, USER_SETTING_GRID_CHARGE_ALLOWED, True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke gemme grid_charge_allowed: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_control(grid_charge_allowed=False)
        try:
            from . import user_settings
            from .const import USER_SETTING_GRID_CHARGE_ALLOWED
            await self.hass.async_add_executor_job(
                user_settings.set_value, USER_SETTING_GRID_CHARGE_ALLOWED, False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke gemme grid_charge_allowed: %s", err)
        self.async_write_ha_state()


class TEOEVProtectionSwitch(TEOBaseEntity, SwitchEntity):
    """EV lader kun fra sol og net ??? beskytter batteriet.

    ON  ??? s??tter Easee dynamic limit til 0A (stopper EV-ladning ??jeblikkeligt)
          OG s??tter ev_protection_soc_pct=100 i LP s?? planen heller ikke tillader det.
    OFF ??? s??tter Easee dynamic limit til 16A (normal ladning tilladt)
          OG s??tter ev_protection_soc_pct=30 i LP.
    """

    _attr_name = "EV kun sol og net"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "ev_protection")
        self.entity_id = "switch.teo_ev_kun_sol_og_net"

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        try:
            return bool(self.coordinator.config.ev_protection_soc_pct >= 100)
        except Exception:
            return False

    async def _set_easee_limit(self, current_a: int) -> None:
        """S??t dynamic limit p?? begge Easee-ladere. Fejl stopper aldrig switchen."""
        for device_id in EASEE_DEVICE_IDS:
            try:
                await self.hass.services.async_call(
                    "easee",
                    "set_charger_dynamic_limit",
                    {"device_id": device_id, "current": current_a},
                    blocking=True,
                )
                _LOGGER.info("Easee %s dynamic limit sat til %dA", device_id, current_a)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Easee %s limit fejlede: %s", device_id, err)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """ON = EV beskyttet ??? stop ladning ??jeblikkeligt."""
        # 1. Stop Easee ??jeblikkeligt
        await self._set_easee_limit(0)
        # 2. Opdater LP-config
        try:
            self.coordinator.config.ev_protection_soc_pct = 100.0
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke s??tte ev_protection_soc_pct: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """OFF = EV tilladt ??? genoptag normal ladning."""
        # 1. Genoptag Easee ladning
        await self._set_easee_limit(EASEE_MAX_CURRENT)
        # 2. Opdater LP-config
        try:
            self.coordinator.config.ev_protection_soc_pct = 30.0
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke s??tte ev_protection_soc_pct: %s", err)
        self.async_write_ha_state()

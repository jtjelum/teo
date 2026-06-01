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
  ON  ??? s??tter Envoy reserve til 100% s?? batteriet ikke aflades til EV.
  OFF ??? s??tter Envoy reserve tilbage til brugerens indstilling.
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
    """EV lader kun fra sol og net ??? batteriet beskyttes via Envoy reserve.

    ON  ??? s??tter Envoy reserve til 100% s?? batteriet ikke aflades overhovedet.
          EV forts??tter med at lade men KUN fra sol og net.
    OFF ??? s??tter Envoy reserve tilbage til brugerens indstilling (ev_protection_soc_pct).
          EV kan igen tr??kke fra batteriet.
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """ON = s??t Envoy reserve til 100% ??? batteriet aflades ikke til EV."""
        try:
            # S??t Envoy reserve til 100% via battery_actuator
            await self.coordinator.manual_actuate(reserve_pct=100.0)
            # Opdater LP-config
            self.coordinator.config.ev_protection_soc_pct = 100.0
            _LOGGER.info("EV beskyttelse ON ??? Envoy reserve sat til 100%%")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("EV beskyttelse ON fejlede: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """OFF = gendan Envoy reserve til brugerens indstilling."""
        try:
            # Hent brugerens reserve-indstilling
            user_reserve = self.coordinator.config.min_soc_pct
            # Gendan Envoy reserve
            await self.coordinator.manual_actuate(reserve_pct=user_reserve)
            # Opdater LP-config
            self.coordinator.config.ev_protection_soc_pct = 30.0
            _LOGGER.info("EV beskyttelse OFF ??? Envoy reserve genoprettet til %.0f%%", user_reserve)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("EV beskyttelse OFF fejlede: %s", err)
        self.async_write_ha_state()

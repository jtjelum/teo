"""Opsætnings-wizard — HA ConfigFlow (spec §3.2).

Trin: (1) sprog + valgfri gendannelse, (2) elzone, (3) tilstand,
(4) enhedsopdagelse, (5) parametre, (6) installation.

Al brugervendt tekst hentes fra translations/<lang>.json (designprincip #7):
feltetiketter via HA's "config"-sektion i sprogfilerne, dynamiske beskeder via
get_string(). Wizarden skriver til sidst teo_config.yaml — som brugeren aldrig
redigerer manuelt (spec §5.1).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_AREA,
    CONF_AZIMUTH,
    CONF_BATTERY,
    CONF_CHARGE_FROM_GRID_BELOW_ORE,
    CONF_CREATED,
    CONF_DEGRADATION_COST,
    CONF_EV_PROTECTION_SOC_PCT,
    CONF_GRID,
    CONF_ID,
    CONF_INSTALLATION,
    CONF_LANGUAGE,
    CONF_MIN_SOC_PCT,
    CONF_MODE,
    CONF_OPTIMISATION,
    CONF_PEAK_KWP,
    CONF_SOLAR,
    CONF_SOLCAST_API_KEY,
    CONF_TEO_VERSION,
    CONF_TILT,
    CONF_USE_BATTERY_ABOVE_ORE,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_BATTERY_MIN_SOC_PCT,
    DEFAULT_CHARGE_FROM_GRID_BELOW_ORE,
    DEFAULT_DEGRADATION_COST_DKK_PER_KWH,
    DEFAULT_EV_PROTECTION_SOC_PCT,
    DEFAULT_GRID_AREA,
    DEFAULT_LANGUAGE,
    DEFAULT_SOLAR_AZIMUTH_DEG,
    DEFAULT_SOLAR_PEAK_KWP,
    DEFAULT_SOLAR_TILT_DEG,
    DEFAULT_USE_BATTERY_ABOVE_ORE,
    DOMAIN,
    GRID_AREAS,
    LANGUAGES,
    MODE_LOCAL,
    MODE_SELF_HOSTED,
    MODES,
    TEO_VERSION,
)
from .installation_id import (
    get_installation_id,
    is_valid_uuid,
    restore_from_id,
)

_LOGGER = logging.getLogger(__name__)


class TEOConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Wizard til opsætning af TEO."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._restored: Optional[dict[str, Any]] = None
        self._discovered: list[dict[str, Any]] = []

    # ----------------------------------------------------------------
    # Trin 1 — sprog (+ valgfri gendannelse via tidligere installations-ID)
    # ----------------------------------------------------------------
    async def async_step_user(self, user_input: Optional[dict] = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_LANGUAGE] = user_input[CONF_LANGUAGE]
            restore_id = (user_input.get("restore_id") or "").strip()
            if restore_id:
                if not is_valid_uuid(restore_id):
                    errors["restore_id"] = "invalid_id"
                else:
                    self._restored = await restore_from_id(restore_id)
                    if self._restored is None:
                        errors["restore_id"] = "id_not_found"
                    else:
                        self._data[CONF_ID] = restore_id
            if not errors:
                return await self.async_step_zone()

        schema = vol.Schema({
            vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): vol.In(LANGUAGES),
            vol.Optional("restore_id"): cv.string,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # ----------------------------------------------------------------
    # Trin 2 — elzone
    # ----------------------------------------------------------------
    async def async_step_zone(self, user_input: Optional[dict] = None) -> FlowResult:
        if user_input is not None:
            self._data[CONF_AREA] = user_input[CONF_AREA]
            return await self.async_step_mode()

        default_zone = (
            (self._restored or {}).get(CONF_GRID, {}).get(CONF_AREA, DEFAULT_GRID_AREA)
        )
        schema = vol.Schema({
            vol.Required(CONF_AREA, default=default_zone): vol.In(list(GRID_AREAS)),
        })
        return self.async_show_form(step_id="zone", data_schema=schema)

    # ----------------------------------------------------------------
    # Trin 3 — tilstand (Local vs Self-Hosted)
    # ----------------------------------------------------------------
    async def async_step_mode(self, user_input: Optional[dict] = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_MODE] = user_input[CONF_MODE]
            if user_input[CONF_MODE] == MODE_SELF_HOSTED:
                email = (user_input.get("email") or "").strip()
                if "@" not in email:
                    errors["email"] = "invalid_email"
                else:
                    self._data["email"] = email
            if not errors:
                return await self.async_step_discovery()

        schema = vol.Schema({
            vol.Required(CONF_MODE, default=MODE_LOCAL): vol.In(list(MODES)),
            vol.Optional("email"): cv.string,
        })
        return self.async_show_form(step_id="mode", data_schema=schema, errors=errors)

    # ----------------------------------------------------------------
    # Trin 4 — enhedsopdagelse (netværksscan)
    # ----------------------------------------------------------------
    async def async_step_discovery(self, user_input: Optional[dict] = None) -> FlowResult:
        if user_input is None:
            # Kør scanningen og vis resultatet til valg.
            self._discovered = await self._scan_network()
            if not self._discovered:
                # Intet fundet — lad brugeren springe videre (manuel opsætning senere).
                schema = vol.Schema({vol.Optional("continue", default=True): bool})
                return self.async_show_form(step_id="discovery", data_schema=schema)

            options = {
                self._device_key(d): self._device_label(d) for d in self._discovered
            }
            schema = vol.Schema({
                vol.Optional("selected_devices", default=list(options.keys())):
                    cv.multi_select(options),
            })
            return self.async_show_form(step_id="discovery", data_schema=schema)

        selected = user_input.get("selected_devices", [])
        self._data["devices"] = [
            d for d in self._discovered if self._device_key(d) in selected
        ]
        return await self.async_step_parameters()

    async def _scan_network(self) -> list[dict[str, Any]]:
        from . import network_scanner
        try:
            zeroconf = await self._get_zeroconf()
            return await network_scanner.scan_all(zeroconf=zeroconf)
        except Exception as err:  # noqa: BLE001 — scanning må aldrig blokere wizarden
            _LOGGER.warning("Netværksscanning fejlede: %s", err)
            return []

    async def _get_zeroconf(self) -> Any:
        try:
            from homeassistant.components import zeroconf
            return await zeroconf.async_get_async_instance(self.hass)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _device_key(device: dict[str, Any]) -> str:
        return f"{device['category']}:{device['brand']}:{device['ip']}"

    @staticmethod
    def _device_label(device: dict[str, Any]) -> str:
        return f"{device['brand']} ({device['category']}) — {device['ip']}"

    # ----------------------------------------------------------------
    # Trin 5 — systemparametre
    # ----------------------------------------------------------------
    async def async_step_parameters(self, user_input: Optional[dict] = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_install()

        r_bat = (self._restored or {}).get(CONF_BATTERY, {})
        r_opt = (self._restored or {}).get(CONF_OPTIMISATION, {})
        r_sol = (self._restored or {}).get(CONF_SOLAR, {})

        schema = vol.Schema({
            vol.Required(CONF_MIN_SOC_PCT,
                         default=r_bat.get(CONF_MIN_SOC_PCT, DEFAULT_BATTERY_MIN_SOC_PCT)):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            vol.Required(CONF_EV_PROTECTION_SOC_PCT,
                         default=r_bat.get(CONF_EV_PROTECTION_SOC_PCT, DEFAULT_EV_PROTECTION_SOC_PCT)):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            vol.Required(CONF_CHARGE_FROM_GRID_BELOW_ORE,
                         default=r_opt.get(CONF_CHARGE_FROM_GRID_BELOW_ORE, DEFAULT_CHARGE_FROM_GRID_BELOW_ORE)):
                vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required(CONF_USE_BATTERY_ABOVE_ORE,
                         default=r_opt.get(CONF_USE_BATTERY_ABOVE_ORE, DEFAULT_USE_BATTERY_ABOVE_ORE)):
                vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional(CONF_SOLCAST_API_KEY,
                         default=r_sol.get(CONF_SOLCAST_API_KEY, "")): cv.string,
            vol.Required(CONF_AZIMUTH,
                         default=r_sol.get(CONF_AZIMUTH, DEFAULT_SOLAR_AZIMUTH_DEG)):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=360)),
            vol.Required(CONF_TILT,
                         default=r_sol.get(CONF_TILT, DEFAULT_SOLAR_TILT_DEG)):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=90)),
            vol.Required(CONF_PEAK_KWP,
                         default=r_sol.get(CONF_PEAK_KWP, DEFAULT_SOLAR_PEAK_KWP)):
                vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Required(CONF_DEGRADATION_COST,
                         default=r_bat.get(CONF_DEGRADATION_COST, DEFAULT_DEGRADATION_COST_DKK_PER_KWH)):
                vol.All(vol.Coerce(float), vol.Range(min=0)),
        })
        return self.async_show_form(step_id="parameters", data_schema=schema)

    # ----------------------------------------------------------------
    # Trin 6 — installation
    # ----------------------------------------------------------------
    async def async_step_install(self, user_input: Optional[dict] = None) -> FlowResult:
        installation_id = self._data.get(CONF_ID) or await self.hass.async_add_executor_job(
            get_installation_id
        )
        self._data[CONF_ID] = installation_id
        await self.async_set_unique_id(installation_id)
        self._abort_if_unique_id_configured()

        config = self._assemble_config(installation_id)
        await self.hass.async_add_executor_job(self._write_config_file, config)

        return self.async_create_entry(
            title=f"TEO ({self._data.get(CONF_AREA, DEFAULT_GRID_AREA)})",
            data=config,
        )

    def _assemble_config(self, installation_id: str) -> dict[str, Any]:
        """Byg teo_config.yaml-strukturen (spec §5.1)."""
        return {
            CONF_INSTALLATION: {
                CONF_ID: installation_id,
                CONF_MODE: self._data.get(CONF_MODE, MODE_LOCAL),
                CONF_LANGUAGE: self._data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                CONF_TEO_VERSION: TEO_VERSION,
                CONF_CREATED: date.today().isoformat(),
            },
            CONF_GRID: {
                CONF_AREA: self._data.get(CONF_AREA, DEFAULT_GRID_AREA),
            },
            CONF_BATTERY: {
                CONF_MIN_SOC_PCT: self._data.get(CONF_MIN_SOC_PCT, DEFAULT_BATTERY_MIN_SOC_PCT),
                CONF_EV_PROTECTION_SOC_PCT: self._data.get(
                    CONF_EV_PROTECTION_SOC_PCT, DEFAULT_EV_PROTECTION_SOC_PCT),
                CONF_DEGRADATION_COST: self._data.get(
                    CONF_DEGRADATION_COST, DEFAULT_DEGRADATION_COST_DKK_PER_KWH),
            },
            CONF_SOLAR: {
                CONF_SOLCAST_API_KEY: self._data.get(CONF_SOLCAST_API_KEY, ""),
                CONF_AZIMUTH: self._data.get(CONF_AZIMUTH, DEFAULT_SOLAR_AZIMUTH_DEG),
                CONF_TILT: self._data.get(CONF_TILT, DEFAULT_SOLAR_TILT_DEG),
                CONF_PEAK_KWP: self._data.get(CONF_PEAK_KWP, DEFAULT_SOLAR_PEAK_KWP),
            },
            CONF_OPTIMISATION: {
                CONF_CHARGE_FROM_GRID_BELOW_ORE: self._data.get(
                    CONF_CHARGE_FROM_GRID_BELOW_ORE, DEFAULT_CHARGE_FROM_GRID_BELOW_ORE),
                CONF_USE_BATTERY_ABOVE_ORE: self._data.get(
                    CONF_USE_BATTERY_ABOVE_ORE, DEFAULT_USE_BATTERY_ABOVE_ORE),
            },
            "devices": self._data.get("devices", []),
        }

    def _write_config_file(self, config: dict[str, Any]) -> None:
        import yaml
        path = Path(CONFIG_DIR) / CONFIG_FILE
        header = (
            "# TEO Konfiguration — version 1.0\n"
            "# Genereret af opsætnings-wizarden. Redigeres via TEO dashboard,\n"
            "# ikke manuelt.\n"
        )
        path.write_text(header + yaml.safe_dump(config, allow_unicode=True,
                                                sort_keys=False), encoding="utf-8")

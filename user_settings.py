"""Persistent brugerindstillinger (teo_user_settings.yaml).

Lad brugeren ændre TEO's indstillinger via HA-UI og få dem gemt permanent, så de
overlever genstart. Kritisk princip: vi overskriver ALDRIG værdier brugeren allerede
har sat — kun defaults ved første oprettelse.

Fejlhåndtering er paranoid: enhver fejl logges men crasher ALDRIG TEO's opstart.
Funktionerne er synkrone (kør via ``hass.async_add_executor_job``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .const import (
    CONFIG_DIR,
    DEFAULT_USER_CHARGE_FROM_GRID,
    DEFAULT_USER_EV_SOLAR_NET_ONLY,
    DEFAULT_USER_GRID_CHARGE_ALLOWED,
    DEFAULT_USER_MIN_SOC,
    DEFAULT_USER_RESERVE_SOC,
    DEFAULT_USER_SELL_AT_NEGATIVE,
    USER_SETTINGS_FILE,
    USER_SETTING_CHARGE_FROM_GRID,
    USER_SETTING_EV_SOLAR_NET_ONLY,
    USER_SETTING_GRID_CHARGE_ALLOWED,
    USER_SETTING_MIN_SOC,
    USER_SETTING_RESERVE_SOC,
    USER_SETTING_SELL_AT_NEGATIVE,
)

_LOGGER = logging.getLogger(__name__)


def _path(config_dir: str = CONFIG_DIR) -> Path:
    """Returnér sti til user settings filen."""
    return Path(config_dir) / USER_SETTINGS_FILE


def _get_defaults() -> dict[str, Any]:
    """Returnér default-værdier for alle brugerindstillinger."""
    return {
        USER_SETTING_MIN_SOC: DEFAULT_USER_MIN_SOC,
        USER_SETTING_RESERVE_SOC: DEFAULT_USER_RESERVE_SOC,
        USER_SETTING_CHARGE_FROM_GRID: DEFAULT_USER_CHARGE_FROM_GRID,
        USER_SETTING_SELL_AT_NEGATIVE: DEFAULT_USER_SELL_AT_NEGATIVE,
        USER_SETTING_GRID_CHARGE_ALLOWED: DEFAULT_USER_GRID_CHARGE_ALLOWED,
        USER_SETTING_EV_SOLAR_NET_ONLY: DEFAULT_USER_EV_SOLAR_NET_ONLY,
    }


def load(config_dir: str = CONFIG_DIR) -> dict[str, Any]:
    """Læs user settings fra YAML. Returnér tom dict ved fejl (graceful degradation).

    Hvis filen ikke findes, oprettes den med defaults. Hvis den findes men mangler
    nøgler, tilføjes kun de manglende (eksisterende værdier bevares).
    """
    p = _path(config_dir)
    defaults = _get_defaults()

    try:
        if not p.exists():
            # Første gang — opret fil med defaults
            _LOGGER.info("Opretter %s med standardindstillinger", USER_SETTINGS_FILE)
            save(defaults, config_dir)
            return defaults.copy()

        # Læs eksisterende fil
        import yaml
        existing = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

        if not isinstance(existing, dict):
            _LOGGER.warning("%s har ugyldigt format — bruger defaults", USER_SETTINGS_FILE)
            return defaults.copy()

        # Tilføj manglende nøgler (ALDRIG overskriv eksisterende)
        updated = False
        for key, default_val in defaults.items():
            if key not in existing:
                existing[key] = default_val
                updated = True

        # Gem tilbage hvis vi tilføjede manglende nøgler
        if updated:
            _LOGGER.info("Tilføjer manglende nøgler til %s", USER_SETTINGS_FILE)
            save(existing, config_dir)

        return existing

    except Exception as err:  # noqa: BLE001 — graceful degradation
        _LOGGER.warning("Kunne ikke læse %s: %s — bruger defaults",
                       USER_SETTINGS_FILE, err)
        return defaults.copy()


def save(settings: dict[str, Any], config_dir: str = CONFIG_DIR) -> None:
    """Gem user settings til YAML. Logger fejl men crasher aldrig."""
    try:
        import yaml
        p = _path(config_dir)
        p.write_text(
            yaml.safe_dump(settings, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    except Exception as err:  # noqa: BLE001 — må aldrig crashe TEO
        _LOGGER.error("Kunne ikke skrive %s: %s", USER_SETTINGS_FILE, err)


def set_value(key: str, value: Any, config_dir: str = CONFIG_DIR) -> None:
    """Sæt én nøgle i user settings og gem. Logger fejl men crasher aldrig."""
    try:
        settings = load(config_dir)
        settings[key] = value
        save(settings, config_dir)
    except Exception as err:  # noqa: BLE001 — må aldrig crashe TEO
        _LOGGER.error("Kunne ikke opdatere %s.%s: %s", USER_SETTINGS_FILE, key, err)

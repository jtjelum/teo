"""Læsning/skrivning af teo_config.yaml (config write-back til GUI-justeringer).

Wizardens config er hidtil kun blevet skrevet ved opsætning. Number-/switch-
entiteterne (minimum-SOC, salg ved negativ pris, netladning tilladt) skal kunne
persistere ændringer, så de overlever genstart og kan læses af coordinatoren.

Bemærk: PyYAML's ``safe_dump`` bevarer ikke kommentarer. Filen genskrives derfor
uden de oprindelige kommentarer ved første write-back — et bevidst, lille
kompromis for at undgå en tung ruamel-afhængighed på Raspberry Pi'en.
Funktionerne er synkrone (kør via ``hass.async_add_executor_job``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .const import CONFIG_DIR, CONFIG_FILE

_LOGGER = logging.getLogger(__name__)


def _path(config_dir: str = CONFIG_DIR) -> Path:
    return Path(config_dir) / CONFIG_FILE


def load(config_dir: str = CONFIG_DIR) -> dict[str, Any]:
    p = _path(config_dir)
    if not p.exists():
        return {}
    import yaml
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save(cfg: dict[str, Any], config_dir: str = CONFIG_DIR) -> None:
    import yaml
    _path(config_dir).write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def set_value(section: str, key: str, value: Any,
              config_dir: str = CONFIG_DIR) -> dict[str, Any]:
    """Sæt ``cfg[section][key] = value`` og gem. Returnerer den nye config."""
    cfg = load(config_dir)
    cfg.setdefault(section, {})
    if not isinstance(cfg[section], dict):
        cfg[section] = {}
    cfg[section][key] = value
    try:
        save(cfg, config_dir)
    except Exception as err:  # noqa: BLE001 — skrivefejl må ikke vælte entiteten
        _LOGGER.warning("Kunne ikke skrive %s.%s til teo_config.yaml: %s",
                        section, key, err)
    return cfg

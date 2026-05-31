"""Global model-distribution — spec DEL 7.4 (dagligt kl. 04:00).

Henter den nyeste kollektive model fra TEO-serveren og gemmer den som
*afventende* — den anvendes ALDRIG automatisk. Designprincip #4: ingen
installation opdateres uden brugerens bekræftelse. Brugeren ser en notifikation
og kan godkende via servicen ``teo.apply_model`` (eller dashboardet).

Ved godkendelse skrives modellens kalibrering (solfaktorer pr. vejrtype,
prisbuffer pr. time, cold-start lastprofiler) ind i teo_config.yaml under
nøglen ``model_calibration``, og hver ændring logges i ``calibration_log`` med
``source = "global_model"`` for fuld sporbarhed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .const import (
    API_PATH_MODEL_LATEST,
    API_TIMEOUT_SEC,
    CONFIG_DIR,
    CONFIG_FILE,
    DATA_DB_FILE,
    PENDING_MODEL_FILE,
    TEO_API_BASE_URL,
)

_LOGGER = logging.getLogger(__name__)


class ModelUpdater:
    """Henter, gemmer og (efter bekræftelse) anvender den globale model."""

    def __init__(self, config_dir: str = CONFIG_DIR) -> None:
        self._config_dir = config_dir
        self._pending_path = Path(config_dir) / PENDING_MODEL_FILE
        self._config_path = Path(config_dir) / CONFIG_FILE
        self._db_path = str(Path(config_dir) / DATA_DB_FILE)

    # -- hentning -------------------------------------------------------
    async def fetch_latest(self, hass) -> dict[str, Any]:
        """Hent model/latest og gem som afventende. Returnerer status-dict."""
        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(hass)
            async with asyncio.timeout(API_TIMEOUT_SEC):
                resp = await session.get(TEO_API_BASE_URL + API_PATH_MODEL_LATEST)
                if resp.status >= 400:
                    return {"available": False, "reason": f"HTTP {resp.status}"}
                model = await resp.json()
        except Exception as err:  # noqa: BLE001 — server evt. ikke oppe endnu
            _LOGGER.debug("Modelhentning fejlede: %s", err)
            return {"available": False, "reason": str(err)}

        version = model.get("version")
        current = await hass.async_add_executor_job(self._current_version)
        if version and version == current:
            return {"available": False, "reason": "allerede nyeste", "version": version}

        await hass.async_add_executor_job(self._save_pending, model)
        self._notify(hass, model)
        return {"available": True, "version": version, "pending": True}

    def _save_pending(self, model: dict[str, Any]) -> None:
        self._pending_path.write_text(json.dumps(model, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    def _current_version(self) -> Optional[str]:
        cfg = self._load_config()
        return (cfg.get("model_calibration", {}) or {}).get("version")

    def _notify(self, hass, model: dict[str, Any]) -> None:
        """Persistent notifikation — brugeren bekræfter selv (princip #4)."""
        version = model.get("version", "?")
        changelog = model.get("changelog_da") or model.get("changelog_en") or ""
        try:
            hass.async_create_task(hass.services.async_call(
                "persistent_notification", "create",
                {
                    "notification_id": "teo_model_update",
                    "title": f"TEO: ny model {version} tilgængelig",
                    "message": (f"{changelog}\n\nGodkend via tjenesten "
                                f"`teo.apply_model` for at anvende den."),
                },
            ))
        except Exception as err:  # noqa: BLE001 — notifikation er ikke kritisk
            _LOGGER.debug("Kunne ikke oprette notifikation: %s", err)

    # -- anvendelse (kun efter bekræftelse) -----------------------------
    def apply_pending(self, zone: str, now: Optional[datetime] = None
                      ) -> dict[str, Any]:
        """Anvend den afventende model på teo_config.yaml + log ændringerne."""
        now = now or datetime.now()
        if not self._pending_path.exists():
            return {"applied": False, "reason": "ingen afventende model"}
        try:
            model = json.loads(self._pending_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as err:
            return {"applied": False, "reason": f"kunne ikke læse model: {err}"}

        zone_cal = (model.get("calibration", {}) or {}).get(zone)
        if zone_cal is None:
            return {"applied": False, "reason": f"ingen kalibrering for zone {zone}"}

        cfg = self._load_config()
        old = cfg.get("model_calibration", {}) or {}
        new_cal = {"version": model.get("version"), "zone": zone, **zone_cal}
        cfg["model_calibration"] = new_cal
        self._save_config(cfg)
        self._log_calibration(now, old.get("version"), model.get("version"), zone_cal)
        try:
            self._pending_path.unlink()
        except OSError:
            pass
        return {"applied": True, "version": model.get("version"), "zone": zone}

    def _log_calibration(self, now, old_version, new_version, zone_cal) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT INTO calibration_log
                       (timestamp, calibration_type, parameter_changed,
                        old_value, new_value, reason, data_points_used,
                        confidence, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (now.isoformat(), "global_model", "model_calibration",
                     str(old_version), str(new_version),
                     "brugergodkendt global model", None, None, "global_model"),
                )
        except sqlite3.Error as err:
            _LOGGER.debug("Kunne ikke logge kalibrering: %s", err)

    # -- config-I/O -----------------------------------------------------
    def _load_config(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return {}
        import yaml
        return yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}

    def _save_config(self, cfg: dict[str, Any]) -> None:
        import yaml
        self._config_path.write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
            encoding="utf-8")

"""Anonym cloud-upload — spec DEL 6 (dagligt kl. 04:30, opt-in).

Sender et stærkt aggregeret, anonymiseret døgnresumé til TEO-serveren, så den
kollektive model kan forbedres. Upload sker KUN når begge betingelser er sande
(designprincip #6 — privacy by design):

* ``data_sharing.opt_in = true`` i teo_config.yaml, og
* installationen kører i Self-Hosted-tilstand.

ALDRIG med i payloaden: IP, adresse, serienumre, navn, e-mail, rå 5-min-data
eller absolutte kWh pr. rum/apparat. Kun normaliserede profiler (0-1), zone og
døgnaggregater. Selve payload-bygningen er adskilt fra afsendelsen, så den kan
inspiceres/enhedstestes uden at sende noget.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import statistics
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .const import (
    API_PATH_TELEMETRY,
    API_TIMEOUT_SEC,
    CONF_AREA,
    CONF_DATA_SHARING,
    CONF_EV_CHARGERS,
    CONF_GRID,
    CONF_OPT_IN,
    CONF_PEAK_KWP,
    CONF_SOLAR,
    CONFIG_DIR,
    DATA_DB_FILE,
    DEFAULT_GRID_AREA,
    DEFAULT_SOLAR_UNCERTAINTY_FACTOR,
    DEFAULT_SYSTEM_BATTERY_KWH,
    DEFAULT_SYSTEM_SOLAR_KWP,
    MODE_SELF_HOSTED,
    PATTERN_SEASON_MONTH,
    PROFILE_HOLIDAY,
    PROFILE_WEEKDAY,
    PROFILE_WEEKEND,
    TEO_API_BASE_URL,
    TEO_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")


class CloudUploader:
    """Bygger og (ved opt-in) sender det anonyme døgnresumé."""

    def __init__(self, config: dict[str, Any], db_path: Optional[str] = None,
                 config_dir: str = CONFIG_DIR) -> None:
        self._config = config or {}
        self._path = db_path or str(Path(config_dir) / DATA_DB_FILE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- gating ---------------------------------------------------------
    def is_enabled(self, mode: str) -> bool:
        opt_in = bool((self._config.get(CONF_DATA_SHARING, {}) or {}).get(CONF_OPT_IN))
        return opt_in and mode == MODE_SELF_HOSTED

    # -- payload --------------------------------------------------------
    def build_payload(self, installation_id: str, mode: str,
                      for_date: date) -> dict[str, Any]:
        """Byg det anonyme telemetri-payload for ét døgn (DEL 6)."""
        grid = self._config.get(CONF_GRID, {}) or {}
        solar = self._config.get(CONF_SOLAR, {}) or {}
        ev = self._config.get(CONF_EV_CHARGERS, []) or []
        zone = grid.get(CONF_AREA, DEFAULT_GRID_AREA)

        with self._connect() as conn:
            energy = self._energy_summary(conn, zone, for_date)
            weather = self._weather_summary(conn, for_date)
            perf = self._model_performance(conn, zone, for_date)
            load_profiles = self._normalized_load_profiles(conn)
            seasonal = self._seasonal_factors(conn)
            scenario = self._day_scenario(conn, zone, for_date)

        return {
            "installation_id": installation_id,
            "date": for_date.isoformat(),
            "teo_version": TEO_VERSION,
            "zone": zone,
            "system_config": {
                "battery_kwh": DEFAULT_SYSTEM_BATTERY_KWH,
                "solar_kwp": solar.get(CONF_PEAK_KWP, DEFAULT_SYSTEM_SOLAR_KWP),
                "has_ev_charger": len(ev) > 0,
                "ev_charger_count": len(ev),
            },
            "energy_summary": energy,
            "weather_summary": weather,
            "model_performance": perf,
            "calibration_state": self._calibration_state(),
            "normalized_load_profile": load_profiles,
            "seasonal_factors": seasonal,
            "day_scenario": scenario,
        }

    def _energy_summary(self, conn, zone, for_date) -> dict[str, Any]:
        r = conn.execute(
            """SELECT solar_total_kwh, grid_import_total_kwh, grid_export_total_kwh,
                      battery_charged_kwh, battery_discharged_kwh,
                      battery_cycles_count, ev_charged_kwh, house_base_kwh
               FROM daily_summary WHERE date = ? AND zone = ?""",
            (for_date.isoformat(), zone),
        ).fetchone()
        d = dict(r) if r else {}
        return {
            "solar_produced_kwh": d.get("solar_total_kwh") or 0.0,
            "grid_imported_kwh": d.get("grid_import_total_kwh") or 0.0,
            "grid_exported_kwh": d.get("grid_export_total_kwh") or 0.0,
            "battery_charged_kwh": d.get("battery_charged_kwh") or 0.0,
            "battery_discharged_kwh": d.get("battery_discharged_kwh") or 0.0,
            "battery_cycles": d.get("battery_cycles_count") or 0.0,
            "ev_charged_kwh": d.get("ev_charged_kwh") or 0.0,
            "house_base_kwh": d.get("house_base_kwh") or 0.0,
        }

    def _day_rows(self, conn, for_date: date):
        start = datetime.combine(for_date, datetime.min.time())
        end = start + timedelta(days=1)
        return conn.execute(
            """SELECT temp_outdoor_c, cloud_cover_pct, precipitation_mm_h,
                      wind_speed_ms, solar_irradiance_wm2, weather_category,
                      optimizer_ran, fallback_active
               FROM measurements WHERE timestamp >= ? AND timestamp < ?""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def _weather_summary(self, conn, for_date) -> dict[str, Any]:
        rows = self._day_rows(conn, for_date)

        def avg(col):
            vals = [r[col] for r in rows if r[col] is not None]
            return round(statistics.mean(vals), 2) if vals else 0.0

        precip = [r["precipitation_mm_h"] for r in rows
                  if r["precipitation_mm_h"] is not None]
        cats = [r["weather_category"] for r in rows if r["weather_category"]]
        day_type = Counter(cats).most_common(1)[0][0] if cats else None
        return {
            "avg_cloud_cover_pct": round(avg("cloud_cover_pct")),
            "total_precipitation_mm": round(sum(precip), 2),
            "avg_temp_c": avg("temp_outdoor_c"),
            "avg_irradiance_wm2": round(avg("solar_irradiance_wm2")),
            "avg_wind_speed_ms": avg("wind_speed_ms"),
            "weather_day_type": day_type,
        }

    def _model_performance(self, conn, zone, for_date) -> dict[str, Any]:
        rows = self._day_rows(conn, for_date)
        opt = sum(1 for r in rows if r["optimizer_ran"])
        fb = sum(1 for r in rows if r["fallback_active"])
        saving = conn.execute(
            "SELECT estimated_saving_dkk FROM daily_summary WHERE date=? AND zone=?",
            (for_date.isoformat(), zone),
        ).fetchone()
        # decision_quality_good_pct fra decision_outcomes (tom → None).
        q = conn.execute(
            """SELECT AVG(CASE WHEN decision_quality='good' THEN 1.0 ELSE 0.0 END)*100 p,
                      COUNT(*) n FROM decision_outcomes""").fetchone()
        good_pct = round(q["p"], 1) if q and q["n"] else None
        return {
            "solcast_error_pct": None,   # afventer Solcast-wiring
            "load_forecast_error_pct": None,
            "optimizer_decisions": opt,
            "fallback_activations": fb,
            "estimated_saving_dkk": (saving["estimated_saving_dkk"]
                                     if saving and saving["estimated_saving_dkk"] is not None
                                     else 0.0),
            "decision_quality_good_pct": good_pct,
        }

    def _calibration_state(self) -> dict[str, Any]:
        """Aktuelle solfaktorer pr. vejrtype (defaults indtil kalibreret)."""
        f = DEFAULT_SOLAR_UNCERTAINTY_FACTOR
        by_weather = (self._config.get(CONF_SOLAR, {}) or {}).get(
            "uncertainty_by_weather", {})
        return {
            "solar_factor_sunny": by_weather.get("sunny", f),
            "solar_factor_cloudy": by_weather.get("cloudy", f),
            "solar_factor_rain": by_weather.get("rain", f),
            "solar_factor_snow": by_weather.get("snow", f),
        }

    def _normalized_load_profiles(self, conn) -> dict[str, list[float]]:
        """24-timers profiler normaliseret til 0-1 pr. dagstype."""
        out: dict[str, list[float]] = {}
        for key, ptype in (("weekday", PROFILE_WEEKDAY),
                           ("weekend", PROFILE_WEEKEND),
                           ("holiday", PROFILE_HOLIDAY)):
            rows = conn.execute(
                """SELECT context_key, avg_consumption_kw FROM family_patterns
                   WHERE pattern_type = ?""", (ptype,)).fetchall()
            hourly = {int(r["context_key"]): (r["avg_consumption_kw"] or 0.0)
                      for r in rows}
            series = [hourly.get(h, 0.0) for h in range(24)]
            peak = max(series) if series else 0.0
            out[key] = [round(v / peak, 4) if peak else 0.0 for v in series]
        return out

    def _seasonal_factors(self, conn) -> dict[str, float]:
        rows = conn.execute(
            """SELECT context_key, confidence FROM family_patterns
               WHERE pattern_type = ?""", (PATTERN_SEASON_MONTH,)).fetchall()
        # confidence-kolonnen bærer månedsfaktoren (sat af family_learner).
        by_month = {int(r["context_key"]): r["confidence"] for r in rows}
        return {name: round(by_month.get(i + 1, 0.0) or 0.0, 4)
                for i, name in enumerate(_MONTHS)}

    def _day_scenario(self, conn, zone, for_date) -> Optional[str]:
        r = conn.execute(
            "SELECT day_scenario FROM daily_summary WHERE date=? AND zone=?",
            (for_date.isoformat(), zone)).fetchone()
        return r["day_scenario"] if r else None

    # -- upload ---------------------------------------------------------
    async def upload(self, hass, installation_id: str, mode: str,
                     for_date: Optional[date] = None) -> dict[str, Any]:
        """Byg og send døgnresuméet hvis opt-in. Returnerer status-dict."""
        if not self.is_enabled(mode):
            return {"sent": False, "reason": "ikke opt-in eller ikke Self-Hosted"}
        for_date = for_date or (datetime.now().date() - timedelta(days=1))
        payload = await hass.async_add_executor_job(
            self.build_payload, installation_id, mode, for_date)
        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(hass)
            async with asyncio.timeout(API_TIMEOUT_SEC):
                resp = await session.post(
                    TEO_API_BASE_URL + API_PATH_TELEMETRY, json=payload)
            return {"sent": resp.status < 400, "status": resp.status}
        except Exception as err:  # noqa: BLE001 — server evt. ikke oppe endnu
            _LOGGER.warning("Cloud-upload fejlede: %s", err)
            return {"sent": False, "reason": str(err)}

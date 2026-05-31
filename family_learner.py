"""Familiespecifik læring — spec DEL 2 (kører dagligt kl. 02:00).

Bygger familiens normalprofil ud af de indsamlede measurements:

* **168-punkts ugeprofil** (ugedag × time): median + spredning af husforbruget.
  Medianen er bevidst valgt (spec 2.1) — den er robust over for enkeltstående
  anomalier (julefrokost, gæster), så de ikke forurener normalbilledet.
* **Aggregerede profiler** pr. dagstype: hverdag, weekend, helligdag og
  skoleferie-hverdag (24 timepunkter hver).
* **Sæsonprofil**: månedsfaktor = månedens gennemsnit / årsgennemsnit.
* **Solcast-kalibrering pr. vejrtype** (spec 2.4): median af solcast_error_pct.
  Springes over så længe Solcast ikke leverer data (TODO i optimizeren).

Resultatet skrives til ``family_patterns`` (fuld genberegning, så tabellen
altid afspejler det aktuelle vindue). Modulet er synkront og bør køres via
``hass.async_add_executor_job``.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .anomaly_detector import profile_for, weekday_hour_key
from .const import (
    CONFIG_DIR,
    CONFIG_FILE,
    DATA_DB_FILE,
    FAMILY_LEARN_LOOKBACK_DAYS,
    FAMILY_MIN_SAMPLES,
    PATTERN_SEASON_MONTH,
    PATTERN_WEEKDAY_HOUR,
    SEASON_LOOKBACK_DAYS,
    SOLCAST_CALIBRATION_LOOKBACK_DAYS,
)

_LOGGER = logging.getLogger(__name__)

# Mål for hvornår en profil regnes "fuldt lært" (≈ ét datapunkt pr. uge i 90
# dages vinduet) — bruges til en blød confidence 0..1.
_CONFIDENCE_TARGET_SAMPLES = 10


def _confidence(n: int) -> float:
    return round(min(1.0, n / _CONFIDENCE_TARGET_SAMPLES), 2)


def _std(values: list[float]) -> float:
    return round(statistics.pstdev(values), 4) if len(values) >= 2 else 0.0


class FamilyLearner:
    """Genberegner lastprofiler og sæsonmønstre fra measurements."""

    def __init__(self, db_path: Optional[str] = None,
                 config_dir: str = CONFIG_DIR) -> None:
        self._path = db_path or str(Path(config_dir) / DATA_DB_FILE)
        self._config_path = str(Path(config_dir) / CONFIG_FILE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- offentligt API -------------------------------------------------
    def run(self, now: Optional[datetime] = None) -> dict[str, Any]:
        """Kør hele lærings-batchen. Returnerer et resumé til logning."""
        now = now or datetime.now()
        summary: dict[str, Any] = {}
        try:
            with self._connect() as conn:
                weekly = self._learn_weekly(conn, now)
                profiles = self._learn_profiles(conn, now)
                seasonal = self._learn_seasonal(conn, now)
            summary = {
                "weekday_hour_cells": weekly,
                "profile_cells": profiles,
                "season_months": seasonal,
                "solcast": self._calibrate_solcast(now),
            }
        except sqlite3.Error as err:
            _LOGGER.warning("Familielæring fejlede: %s", err)
            summary = {"error": str(err)}
        return summary

    # -- 2.1 ugeprofil (ugedag × time) ----------------------------------
    def _learn_weekly(self, conn: sqlite3.Connection, now: datetime) -> int:
        since = (now - timedelta(days=FAMILY_LEARN_LOOKBACK_DAYS)).isoformat()
        rows = conn.execute(
            """SELECT weekday, hour, house_consumption_kw
               FROM measurements
               WHERE timestamp >= ? AND house_consumption_kw IS NOT NULL
                 AND weekday IS NOT NULL AND hour IS NOT NULL""",
            (since,),
        ).fetchall()

        groups: dict[tuple[int, int], list[float]] = {}
        for r in rows:
            groups.setdefault((r["weekday"], r["hour"]), []).append(
                r["house_consumption_kw"])

        self._replace_pattern(conn, PATTERN_WEEKDAY_HOUR, [
            (weekday_hour_key(wd, hr), round(statistics.median(v), 4),
             _std(v), len(v), _confidence(len(v)), now.isoformat())
            for (wd, hr), v in groups.items()
        ])
        return len(groups)

    # -- 2.1 aggregerede dagstype-profiler ------------------------------
    def _learn_profiles(self, conn: sqlite3.Connection, now: datetime) -> int:
        since = (now - timedelta(days=FAMILY_LEARN_LOOKBACK_DAYS)).isoformat()
        rows = conn.execute(
            """SELECT hour, weekday, house_consumption_kw,
                      is_public_holiday_dk, is_school_holiday_dk
               FROM measurements
               WHERE timestamp >= ? AND house_consumption_kw IS NOT NULL
                 AND hour IS NOT NULL AND weekday IS NOT NULL""",
            (since,),
        ).fetchall()

        # profile_type -> hour -> [values]
        groups: dict[str, dict[int, list[float]]] = {}
        for r in rows:
            ptype = profile_for(
                r["weekday"],
                bool(r["is_public_holiday_dk"]) if r["is_public_holiday_dk"] is not None else None,
                bool(r["is_school_holiday_dk"]) if r["is_school_holiday_dk"] is not None else None,
            )
            groups.setdefault(ptype, {}).setdefault(r["hour"], []).append(
                r["house_consumption_kw"])

        total = 0
        for ptype, by_hour in groups.items():
            self._replace_pattern(conn, ptype, [
                (str(hr), round(statistics.median(v), 4), _std(v), len(v),
                 _confidence(len(v)), now.isoformat())
                for hr, v in by_hour.items()
            ])
            total += len(by_hour)
        return total

    # -- 2.2 sæsonprofil ------------------------------------------------
    def _learn_seasonal(self, conn: sqlite3.Connection, now: datetime) -> int:
        since = (now - timedelta(days=SEASON_LOOKBACK_DAYS)).isoformat()
        rows = conn.execute(
            """SELECT month, house_consumption_kw
               FROM measurements
               WHERE timestamp >= ? AND house_consumption_kw IS NOT NULL
                 AND month IS NOT NULL""",
            (since,),
        ).fetchall()
        by_month: dict[int, list[float]] = {}
        for r in rows:
            by_month.setdefault(r["month"], []).append(r["house_consumption_kw"])
        if not by_month:
            self._replace_pattern(conn, PATTERN_SEASON_MONTH, [])
            return 0

        all_vals = [v for vals in by_month.values() for v in vals]
        yearly_avg = statistics.mean(all_vals) if all_vals else 0.0
        records = []
        for month, vals in by_month.items():
            month_avg = statistics.mean(vals)
            factor = round(month_avg / yearly_avg, 4) if yearly_avg else 1.0
            # avg_consumption_kw = månedsgns, confidence bærer månedsfaktoren.
            records.append((str(month), round(month_avg, 4), _std(vals),
                            len(vals), factor, now.isoformat()))
        self._replace_pattern(conn, PATTERN_SEASON_MONTH, records)
        return len(records)

    # -- 2.4 Solcast-kalibrering ---------------------------------------
    def _calibrate_solcast(self, now: datetime) -> dict[str, Any]:
        """Median solcast_error_pct pr. vejrtype. No-op uden Solcast-data."""
        since = (now - timedelta(days=SOLCAST_CALIBRATION_LOOKBACK_DAYS)).isoformat()
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT weather_category, solcast_forecast_kwh,
                              solar_production_kw
                       FROM measurements
                       WHERE timestamp >= ? AND solcast_forecast_kwh IS NOT NULL""",
                    (since,),
                ).fetchall()
        except sqlite3.Error:
            return {"calibrated": False, "reason": "db-fejl"}
        if not rows:
            # Forventet indtil Solcast er wiret i optimizeren.
            return {"calibrated": False, "reason": "ingen Solcast-data endnu"}
        # (Reel kalibrering aktiveres når Solcast leverer forecast+actual.)
        return {"calibrated": False, "reason": "afventer actual-vs-forecast wiring"}

    # -- persistens -----------------------------------------------------
    def _replace_pattern(self, conn: sqlite3.Connection, pattern_type: str,
                         records: list[tuple]) -> None:
        """Erstat alle rækker for én pattern_type (fuld genberegning).

        records: (context_key, avg_kw, std_kw, sample_count, confidence, ts).
        Rækker under FAMILY_MIN_SAMPLES gemmes også, men markeres lav-confidence
        så anomaly_detector kan filtrere dem fra.
        """
        conn.execute("DELETE FROM family_patterns WHERE pattern_type = ?",
                     (pattern_type,))
        conn.executemany(
            """INSERT INTO family_patterns
               (pattern_type, context_key, avg_consumption_kw, std_consumption_kw,
                sample_count, confidence, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(pattern_type, *rec) for rec in records],
        )

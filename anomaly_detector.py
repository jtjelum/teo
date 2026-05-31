"""Anomali-detektion — spec DEL 2.3.

To opgaver, begge lokale og defensive:

1. **Punkt-anomali**: er det aktuelle forbrug større end ``forventet +
   ANOMALY_STD_MULTIPLIER × std`` for konteksten (ugedag × time)? Så flagges
   det og holdes UDEN FOR modeltræningen — en julefrokost med gæster skal ikke
   forurene familiens normalprofil (designprincip #3 i SAMLET_V2).

2. **Fraværstilstand**: er forbruget konsekvent lavt i mere end
   ABSENT_MODE_MIN_DAYS dage? Så er familien sandsynligvis bortrejst, og
   optimeringen bør gøres mindre aggressiv.

Baseline-profilerne (``family_patterns``) skrives af ``family_learner`` (Trin
3). Findes der endnu ingen baseline, returnerer detektoren "ingen vurdering"
frem for falske udslag.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .const import (
    ABSENT_MODE_LOW_FACTOR,
    ABSENT_MODE_MIN_DAYS,
    ANOMALY_STD_MULTIPLIER,
    CONFIG_DIR,
    DATA_DB_FILE,
    FAMILY_MIN_SAMPLES,
    PATTERN_WEEKDAY_HOUR,
    PROFILE_HOLIDAY,
    PROFILE_SCHOOL_HOLIDAY,
    PROFILE_WEEKDAY,
    PROFILE_WEEKEND,
)

_LOGGER = logging.getLogger(__name__)


def weekday_hour_key(weekday: int, hour: int) -> str:
    """Nøgle for 168-punkts profilen — delt format med family_learner."""
    return f"{weekday}_{hour}"


def profile_for(weekday: int, is_holiday: Optional[bool],
                is_school_holiday: Optional[bool]) -> str:
    """Vælg den aggregerede profiltype for en given dagskontekst."""
    if is_holiday:
        return PROFILE_HOLIDAY
    is_weekend = weekday >= 5
    if is_school_holiday and not is_weekend:
        return PROFILE_SCHOOL_HOLIDAY
    return PROFILE_WEEKEND if is_weekend else PROFILE_WEEKDAY


class AnomalyDetector:
    """Læser baseline-profiler og vurderer forbrug mod dem."""

    def __init__(self, db_path: Optional[str] = None,
                 config_dir: str = CONFIG_DIR) -> None:
        self._path = db_path or str(Path(config_dir) / DATA_DB_FILE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- baseline-opslag ------------------------------------------------
    def expected(self, weekday: int, hour: int,
                 is_holiday: Optional[bool] = None,
                 is_school_holiday: Optional[bool] = None
                 ) -> Optional[dict[str, Any]]:
        """Forventet forbrug for konteksten.

        Foretrækker den specifikke ugedag×time-profil; falder ellers tilbage til
        den aggregerede dagstype-profil. Returnerer ``None`` hvis ingen profil
        har nok datapunkter endnu.
        """
        specific = self._lookup(PATTERN_WEEKDAY_HOUR, weekday_hour_key(weekday, hour))
        if specific is not None:
            return specific
        profile = profile_for(weekday, is_holiday, is_school_holiday)
        return self._lookup(profile, str(hour))

    def _lookup(self, pattern_type: str, context_key: str) -> Optional[dict[str, Any]]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT avg_consumption_kw, std_consumption_kw, sample_count,
                              confidence
                       FROM family_patterns
                       WHERE pattern_type = ? AND context_key = ?
                       ORDER BY last_updated DESC LIMIT 1""",
                    (pattern_type, context_key),
                ).fetchone()
        except sqlite3.Error as err:
            _LOGGER.debug("family_patterns-opslag fejlede: %s", err)
            return None
        if row is None or row["avg_consumption_kw"] is None:
            return None
        if (row["sample_count"] or 0) < FAMILY_MIN_SAMPLES:
            return None
        return {
            "avg_kw": row["avg_consumption_kw"],
            "std_kw": row["std_consumption_kw"] or 0.0,
            "sample_count": row["sample_count"],
            "confidence": row["confidence"],
        }

    # -- punkt-anomali --------------------------------------------------
    def check(self, consumption_kw: Optional[float], weekday: int, hour: int,
              is_holiday: Optional[bool] = None,
              is_school_holiday: Optional[bool] = None) -> dict[str, Any]:
        """Vurder ét forbrugspunkt. ``is_anomaly`` er False uden baseline."""
        if consumption_kw is None:
            return {"is_anomaly": False, "reason": None, "baseline": None}
        baseline = self.expected(weekday, hour, is_holiday, is_school_holiday)
        if baseline is None:
            return {"is_anomaly": False, "reason": None, "baseline": None}
        threshold = baseline["avg_kw"] + ANOMALY_STD_MULTIPLIER * baseline["std_kw"]
        if consumption_kw > threshold:
            reason = (
                f"forbrug {consumption_kw:.2f} kW > grænse {threshold:.2f} kW "
                f"(forventet {baseline['avg_kw']:.2f} ± {baseline['std_kw']:.2f})"
            )
            return {"is_anomaly": True, "reason": reason, "baseline": baseline,
                    "threshold_kw": round(threshold, 3)}
        return {"is_anomaly": False, "reason": None, "baseline": baseline,
                "threshold_kw": round(threshold, 3)}

    # -- fraværstilstand ------------------------------------------------
    def detect_absent_mode(self, now: Optional[datetime] = None) -> dict[str, Any]:
        """Er forbruget konsekvent lavt i > ABSENT_MODE_MIN_DAYS dage?

        Sammenligner hver af de seneste dages gennemsnitsforbrug med det samlede
        baseline-gennemsnit (fra family_patterns). Returnerer ``absent``=True
        kun hvis ALLE de seneste dage ligger under ABSENT_MODE_LOW_FACTOR.
        """
        now = now or datetime.now()
        baseline_avg = self._overall_baseline_avg()
        if baseline_avg is None:
            return {"absent": False, "days_evaluated": 0, "reason": None}

        threshold = baseline_avg * ABSENT_MODE_LOW_FACTOR
        low_days = 0
        try:
            with self._connect() as conn:
                for day_offset in range(ABSENT_MODE_MIN_DAYS):
                    day_end = now - timedelta(days=day_offset)
                    day_start = day_end - timedelta(days=1)
                    row = conn.execute(
                        """SELECT AVG(house_consumption_kw) AS avg_kw, COUNT(*) AS n
                           FROM measurements
                           WHERE timestamp >= ? AND timestamp < ?
                             AND house_consumption_kw IS NOT NULL""",
                        (day_start.isoformat(), day_end.isoformat()),
                    ).fetchone()
                    if row is None or row["n"] == 0 or row["avg_kw"] is None:
                        # Manglende data → kan ikke bekræfte fravær.
                        return {"absent": False, "days_evaluated": day_offset,
                                "reason": "utilstrækkelige data"}
                    if row["avg_kw"] < threshold:
                        low_days += 1
                    else:
                        return {"absent": False, "days_evaluated": day_offset + 1,
                                "reason": None}
        except sqlite3.Error as err:
            _LOGGER.debug("fraværsopslag fejlede: %s", err)
            return {"absent": False, "days_evaluated": 0, "reason": None}

        absent = low_days >= ABSENT_MODE_MIN_DAYS
        return {
            "absent": absent,
            "days_evaluated": low_days,
            "threshold_kw": round(threshold, 3),
            "reason": (f"lavt forbrug < {threshold:.2f} kW i {low_days} dage"
                       if absent else None),
        }

    def _overall_baseline_avg(self) -> Optional[float]:
        """Vægtet gennemsnit af alle ugedag×time-profiler (samlet normalforbrug)."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT AVG(avg_consumption_kw) AS a
                       FROM family_patterns
                       WHERE pattern_type = ? AND avg_consumption_kw IS NOT NULL
                         AND sample_count >= ?""",
                    (PATTERN_WEEKDAY_HOUR, FAMILY_MIN_SAMPLES),
                ).fetchone()
        except sqlite3.Error:
            return None
        return row["a"] if row and row["a"] is not None else None

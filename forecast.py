"""Last-prognose til optimizeren — forbruger lokal læring + global model.

Erstatter den tidligere flade last-antagelse med en time-for-time-prognose:

1. **Lokal familieprofil** (family_patterns, lært af family_learner) bruges
   først — den specifikke ugedag×time-profil, ellers dagstype-profilen.
2. **Cold-start** fra den globale models ``load_cold_start`` (normaliseret 0-1)
   bruges som fallback for timer hvor den lokale profil endnu mangler data
   (designprincip #5: hjælp nye brugere, glid gradvist over i familiens profil).
3. Som sidste udvej det aktuelle husforbrug (fladt).

Cold-start-kurven (0-1) skaleres så dens gennemsnit matcher husstandens
nuværende forbrugsniveau (``anchor_kw``), så den normaliserede form bevares.
Modulet er HA-frit og synkront (kalderen leverer tidskonteksten).
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Optional

from .const import (
    CONFIG_DIR,
    DATA_DB_FILE,
    FAMILY_MIN_SAMPLES,
    PATTERN_WEEKDAY_HOUR,
)

_LOGGER = logging.getLogger(__name__)


def _family_lookup(conn: sqlite3.Connection, weekday: int, hour: int,
                   profile: str) -> Optional[float]:
    """Lokal lært last for (ugedag,time); ellers dagstype-profilen. kW eller None."""
    for ptype, key in ((PATTERN_WEEKDAY_HOUR, f"{weekday}_{hour}"),
                       (profile, str(hour))):
        row = conn.execute(
            """SELECT avg_consumption_kw, sample_count FROM family_patterns
               WHERE pattern_type=? AND context_key=? ORDER BY last_updated DESC
               LIMIT 1""", (ptype, key)).fetchone()
        if (row and row["avg_consumption_kw"] is not None
                and (row["sample_count"] or 0) >= FAMILY_MIN_SAMPLES):
            return float(row["avg_consumption_kw"])
    return None


def _cold_start_scale(curve: list[float], anchor_kw: float) -> float:
    """Skaleringsfaktor så den normaliserede kurves gennemsnit = anchor_kw."""
    vals = [v for v in curve if v is not None]
    mean = statistics.mean(vals) if vals else 0.0
    return (anchor_kw / mean) if mean > 0 else 0.0


def build_load_forecast(
    contexts: list[tuple[Any, int, int, str]],
    model_calibration: Optional[dict[str, Any]],
    anchor_kw: float,
    db_path: Optional[str] = None,
    config_dir: str = CONFIG_DIR,
) -> dict[Any, float]:
    """Byg ``{tid: kW}`` for hver (tid, ugedag, time, profil) i ``contexts``."""
    path = db_path or str(Path(config_dir) / DATA_DB_FILE)
    cold = (model_calibration or {}).get("load_cold_start", {}) or {}
    cold_scale = {p: _cold_start_scale(curve, anchor_kw)
                  for p, curve in cold.items() if isinstance(curve, list)}

    out: dict[Any, float] = {}
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as err:
        _LOGGER.debug("forecast db utilgængelig (%s) — flad last", err)
        return {t: round(anchor_kw, 3) for (t, *_rest) in contexts}

    with conn:
        for (t, weekday, hour, profile) in contexts:
            kw = _family_lookup(conn, weekday, hour, profile)
            if kw is None:
                curve = cold.get(profile)
                if isinstance(curve, list) and 0 <= hour < len(curve) \
                        and curve[hour] is not None:
                    kw = curve[hour] * cold_scale.get(profile, 0.0)
            if kw is None:
                kw = anchor_kw
            out[t] = round(max(kw, 0.0), 3)
    return out

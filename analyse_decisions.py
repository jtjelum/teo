"""Daglig rapport (kl. 06:00).

Genererer simpel daglig rapport baseret på measurements-tabellen:
  - Antal målinger per handling (charge/discharge/idle)
  - Gennemsnitlig, højeste og laveste spotpris
  - Batteri SOC ved dagens start og slut

Gemmer til /config/teo_reports/YYYY-MM-DD.txt (én fil per dag).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DATA_DB_FILE

_LOGGER = logging.getLogger(__name__)


async def run_daily_analysis(hass: HomeAssistant) -> dict[str, Any]:
    """Kør daglig rapport og gem til fil.

    Returnerer:
      {
        "success": bool,
        "report_text": str,
        "error": str (hvis fejl),
      }
    """
    try:
        report_text = await hass.async_add_executor_job(_generate_report)

        # Gem rapport til dateret fil i /config/teo_reports/
        report_dir = Path("/config/teo_reports")
        report_dir.mkdir(exist_ok=True)
        report_file = report_dir / f"{datetime.now().strftime('%Y-%m-%d')}.txt"

        # Overskriv aldrig eksisterende filer
        if not report_file.exists():
            report_file.write_text(report_text, encoding="utf-8")
            _LOGGER.warning("TEO rapport gemt: %s", report_file)
        else:
            _LOGGER.info("Rapport-fil eksisterer allerede: %s", report_file)

        # Send rapport som persistent notification
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "TEO Daglig Rapport",
                "message": report_text,
                "notification_id": "teo_daily_report",
            },
        )

        return {
            "success": True,
            "report_text": report_text,
        }

    except Exception as err:
        _LOGGER.error("Daglig rapport fejlede: %s", err, exc_info=True)
        return {
            "success": False,
            "error": str(err),
        }


def _generate_report() -> str:
    """Generer daglig rapport baseret på measurements-tabel."""
    db_path = Path(DATA_DB_FILE)
    if not db_path.exists():
        return "Ingen data tilgængelig — measurements.db findes ikke."

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Hent data for seneste 24 timer
    cutoff = datetime.now() - timedelta(hours=24)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    # Tjek om measurements-tabellen har de nødvendige kolonner
    cursor.execute("PRAGMA table_info(measurements)")
    columns = {row[1] for row in cursor.fetchall()}

    if not {"timestamp", "teo_action", "battery_soc_pct", "nordpool_price_ore"}.issubset(columns):
        conn.close()
        return "Measurements-tabel mangler nødvendige kolonner."

    # Query: Hent målinger fra seneste 24 timer
    cursor.execute(
        """
        SELECT
            teo_action,
            battery_soc_pct,
            nordpool_price_ore
        FROM measurements
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (cutoff_str,),
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "Ingen målinger fundet for de seneste 24 timer."

    # Analyse: tæl handlinger
    charge_count = sum(1 for r in rows if r[0] == "BATTERY_CHARGE_GRID")
    discharge_count = sum(1 for r in rows if r[0] == "BATTERY_DISCHARGE")
    idle_count = sum(1 for r in rows if r[0] == "BATTERY_IDLE")
    total_count = len(rows)

    # Analyse: priser (filtrér None-værdier)
    prices = [r[2] for r in rows if r[2] is not None]
    avg_price = sum(prices) / len(prices) if prices else 0.0
    max_price = max(prices) if prices else 0.0
    min_price = min(prices) if prices else 0.0

    # Analyse: SOC start og slut (filtrér None-værdier)
    socs = [r[1] for r in rows if r[1] is not None]
    start_soc = socs[0] if socs else 0.0
    end_soc = socs[-1] if socs else 0.0

    # Formatér rapport
    now = datetime.now()
    report_lines = [
        f"TEO Daglig Rapport — {now.strftime('%Y-%m-%d %H:%M')}",
        f"Periode: Seneste 24 timer ({total_count} målinger)",
        "",
        f"Opladning (net): {charge_count} målinger",
        f"Afladning: {discharge_count} målinger",
        f"Idle: {idle_count} målinger",
        "",
        f"Gns. spotpris: {avg_price:.1f} øre/kWh",
        f"Højeste pris: {max_price:.1f} øre/kWh | Laveste pris: {min_price:.1f} øre/kWh",
        f"Batteri SOC: Start {start_soc:.1f}% → Slut {end_soc:.1f}%",
    ]

    return "\n".join(report_lines)

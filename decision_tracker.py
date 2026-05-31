"""Decision Tracker — sporing og analyse af TEO-beslutninger.

Logsystem DEL 1+2:
- Kontinuerlig logging af faktisk vs. planlagt handling (hvert 5. minut)
- Daglig analyse af afvigelser (kl. 06:00)
- API-data til dashboard-widget

Arkitektur:
- Lazy-loadet fra data_collector.py og analyse_decisions.py
- Fejl blokerer ALDRIG LP-optimizeren (robust error-handling)
- Bruger eksisterende measurements-tabel + ny decisions_log-tabel
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Database schema for decisions_log
DECISIONS_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    -- Planlagt handling (fra LP-optimizer)
    planned_action          TEXT,          -- idle/charging_grid/charging_solar/discharging
    planned_reasoning       TEXT,          -- Dansk forklaring
    -- Faktisk handling (aflæst fra enheder)
    actual_action           TEXT,          -- samme kategorier som planned
    battery_power_kw        REAL,          -- Positiv=lader, negativ=aflader
    battery_soc_pct         REAL,
    charge_from_grid_switch INTEGER,       -- 0/1
    solar_production_kw     REAL,
    -- Afvigelse
    deviation_detected      INTEGER,       -- 0/1
    deviation_reason        TEXT,          -- Dansk forklaring hvis afvigelse
    enphase_override        INTEGER        -- 0/1 cloud overskrev TEO
);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions_log (timestamp);
"""

# Klassificering af batterihåndtering
ACTION_IDLE = "idle"
ACTION_CHARGING_GRID = "charging_grid"
ACTION_CHARGING_SOLAR = "charging_solar"
ACTION_DISCHARGING = "discharging"


class DecisionTracker:
    """Tracker for TEO-beslutninger med analyse og API-data."""

    def __init__(self, db_path: str | Path):
        """Initialisér tracker med database-sti."""
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        """Context manager for SQLite forbindelse."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self):
        """Sikr decisions_log-tabellen eksisterer."""
        with self._lock, self._connect() as conn:
            conn.executescript(DECISIONS_LOG_SCHEMA)

    async def log_decision(
        self,
        hass: HomeAssistant,
        planned_action: str | None,
        planned_reasoning: str | None,
    ) -> bool:
        """Log én beslutning (kaldes fra data_collector hver 5. minut).

        Args:
            hass: HomeAssistant instance
            planned_action: Planlagt handling fra LP (idle/charging_grid/etc)
            planned_reasoning: Dansk forklaring fra optimizer

        Returns:
            True hvis logning lykkedes, False ved fejl
        """
        try:
            # Aflæs faktisk tilstand fra entities
            actual_action = await self._get_actual_action(hass)
            battery_power = await self._get_entity_float(
                hass, "sensor.enphase_envoy_battery_power", 0.0
            )
            # Enphase konvention: negativ = lader, positiv = aflader
            # Konverter til kW og inverter fortegn for konsistens
            battery_power_kw = -battery_power / 1000.0

            battery_soc = await self._get_entity_float(
                hass, "sensor.teo_batteriniveau", None
            )
            charge_from_grid = await self._get_entity_bool(
                hass, "switch.teo_enphase_charge_from_grid", False
            )
            solar_production = await self._get_entity_float(
                hass, "sensor.teo_solproduktion", 0.0
            )

            # Detektér afvigelse
            deviation, reason, enphase_override = self._detect_deviation(
                planned_action, actual_action, charge_from_grid
            )

            # Skriv til database
            row = {
                "timestamp": datetime.now().isoformat(),
                "planned_action": planned_action,
                "planned_reasoning": planned_reasoning,
                "actual_action": actual_action,
                "battery_power_kw": battery_power_kw,
                "battery_soc_pct": battery_soc,
                "charge_from_grid_switch": int(charge_from_grid),
                "solar_production_kw": solar_production,
                "deviation_detected": int(deviation),
                "deviation_reason": reason,
                "enphase_override": int(enphase_override),
            }

            await hass.async_add_executor_job(self._write_decision, row)
            return True

        except Exception as err:
            _LOGGER.exception("Kunne ikke logge beslutning: %s", err)
            return False

    async def _get_actual_action(self, hass: HomeAssistant) -> str:
        """Klassificér faktisk batterihåndling baseret på sensorer."""
        battery_power = await self._get_entity_float(
            hass, "sensor.enphase_envoy_battery_power", 0.0
        )
        charge_from_grid = await self._get_entity_bool(
            hass, "switch.teo_enphase_charge_from_grid", False
        )
        solar_production = await self._get_entity_float(
            hass, "sensor.teo_solproduktion", 0.0
        )

        # Enphase konvention: negativ effekt = lader
        is_charging = battery_power < -100  # >100W ladning
        is_discharging = battery_power > 100  # >100W afladning

        if is_charging:
            if charge_from_grid:
                return ACTION_CHARGING_GRID
            elif solar_production > 0.5:  # >500W sol
                return ACTION_CHARGING_SOLAR
            else:
                return ACTION_CHARGING_GRID  # Lader uden sol = grid

        if is_discharging:
            return ACTION_DISCHARGING

        return ACTION_IDLE

    async def _get_entity_float(
        self, hass: HomeAssistant, entity_id: str, default: float | None
    ) -> float | None:
        """Hent float-værdi fra entity (returnerer default ved fejl)."""
        try:
            state = hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                return default
            return float(state.state)
        except (ValueError, TypeError):
            return default

    async def _get_entity_bool(
        self, hass: HomeAssistant, entity_id: str, default: bool
    ) -> bool:
        """Hent bool-værdi fra entity (returnerer default ved fejl)."""
        try:
            state = hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                return default
            return state.state == "on"
        except (ValueError, TypeError):
            return default

    def _detect_deviation(
        self,
        planned: str | None,
        actual: str,
        charge_from_grid: bool,
    ) -> tuple[bool, str | None, bool]:
        """Detektér om faktisk handling afviger fra planlagt.

        Returns:
            (deviation_detected, reason, enphase_override)
        """
        if planned is None:
            return (False, None, False)

        # Eksakt match
        if planned == actual:
            return (False, None, False)

        # Enphase-cloud override: TEO planlagde idle/discharge men batteriet lader fra net
        enphase_override = (
            planned in (ACTION_IDLE, ACTION_DISCHARGING)
            and actual == ACTION_CHARGING_GRID
            and charge_from_grid
        )

        if enphase_override:
            return (
                True,
                "☁️ Enphase-cloud overtog kontrollen og startede netladning",
                True,
            )

        # Anden afvigelse
        reason = f"Planlagt: {planned}, faktisk: {actual}"
        return (True, reason, False)

    def _write_decision(self, row: dict[str, Any]) -> int:
        """Skriv beslutning til database (synkron)."""
        import threading

        with self._lock, self._connect() as conn:
            columns = ", ".join(row.keys())
            placeholders = ", ".join("?" * len(row))
            cur = conn.execute(
                f"INSERT INTO decisions_log ({columns}) VALUES ({placeholders})",
                tuple(row.values()),
            )
            return cur.lastrowid

    async def analyze_last_24h(self, hass: HomeAssistant) -> dict[str, Any]:
        """Analysér afvigelser de seneste 24 timer.

        Returns:
            Dict med:
            - total_decisions: Antal beslutninger
            - plan_match_rate: % hvor faktisk = planlagt
            - deviations: Antal afvigelser
            - enphase_overrides: Antal cloud-overskrivninger
            - report: Dansk rapport (max 10 linjer)
        """
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()

        def _query():
            with self._lock, self._connect() as conn:
                # Hent alle beslutninger seneste 24h
                cur = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN deviation_detected = 0 THEN 1 ELSE 0 END) as matches,
                        SUM(CASE WHEN deviation_detected = 1 THEN 1 ELSE 0 END) as deviations,
                        SUM(CASE WHEN enphase_override = 1 THEN 1 ELSE 0 END) as overrides
                    FROM decisions_log
                    WHERE timestamp >= ?
                    """,
                    (cutoff,),
                )
                row = cur.fetchone()

                # Hent eksempler på afvigelser
                cur2 = conn.execute(
                    """
                    SELECT timestamp, planned_action, actual_action, deviation_reason
                    FROM decisions_log
                    WHERE timestamp >= ? AND deviation_detected = 1
                    ORDER BY timestamp DESC
                    LIMIT 5
                    """,
                    (cutoff,),
                )
                deviation_examples = [dict(r) for r in cur2.fetchall()]

                return dict(row), deviation_examples

        stats, examples = await hass.async_add_executor_job(_query)

        total = stats["total"] or 0
        matches = stats["matches"] or 0
        deviations = stats["deviations"] or 0
        overrides = stats["overrides"] or 0

        # Beregn match-rate
        match_rate = (matches / total * 100) if total > 0 else 0.0

        # Generer dansk rapport
        report_lines = [
            f"📊 TEO Beslutningsanalyse (seneste 24 timer)",
            f"",
            f"✅ Plan-match: {match_rate:.1f}% ({matches}/{total})",
            f"⚠️  Afvigelser: {deviations}",
        ]

        if overrides > 0:
            report_lines.append(
                f"☁️  Enphase-cloud overskrivninger: {overrides} — overvej at slå cloud-optimering FRA"
            )

        if examples:
            report_lines.append("")
            report_lines.append("📋 Seneste afvigelser:")
            for ex in examples[:3]:  # Max 3 eksempler
                ts = ex["timestamp"][:16]  # YYYY-MM-DD HH:MM
                reason = ex["deviation_reason"] or "Ukendt årsag"
                report_lines.append(f"  • {ts}: {reason}")

        report = "\n".join(report_lines)

        return {
            "total_decisions": total,
            "plan_match_rate": match_rate,
            "deviations": deviations,
            "enphase_overrides": overrides,
            "report": report,
        }

    async def get_soc_timeline(
        self, hass: HomeAssistant, hours: int = 24
    ) -> list[dict[str, Any]]:
        """Hent SOC timeline-data til dashboard-widget.

        Args:
            hass: HomeAssistant instance
            hours: Antal timer tilbage i tid

        Returns:
            Liste af datapunkter med timestamp, SOC, planned_action
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        def _query():
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    """
                    SELECT
                        timestamp,
                        battery_soc_pct,
                        planned_action,
                        actual_action,
                        deviation_detected
                    FROM decisions_log
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC
                    """,
                    (cutoff,),
                )
                return [dict(row) for row in cur.fetchall()]

        return await hass.async_add_executor_job(_query)

    def purge_old(self, retention_days: int = 30) -> int:
        """Slet beslutninger ældre end opbevaringsgrænsen."""
        import threading

        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM decisions_log WHERE timestamp < ?",
                (cutoff,),
            )
            return cur.rowcount

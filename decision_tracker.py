"""DEL 1/2/3 — Logsystem til kontinuerlig datalogning og afvigelses-analyse.

DEL 1: Kontinuerlig datalogning (hvert 5. minut)
  Udvider measurements-tabellen med:
    - teo_actual_action: hvad Envoy/Easee faktisk gør (læst fra entiteter)
    - teo_reasoning: kort begrundelse for planlagt handling

  Sammenligningslogik:
    teo_planned_action = teo_action (fra optimizer/fallback)
    teo_actual_action = aflæst fra HA-entiteter:
      - sensor.enphase_envoy_battery_mode (charge/discharge/idle)
      - switch.teo_charge_from_grid (on/off)
      - sensor.easee_master_power (>0.5kW = charging)

DEL 2: Daglig afvigelses-analyse (kl. 06:00)
  Kører analyse_decisions.py der:
    1. Henter seneste 24 timers log
    2. Sammenligner planlagt vs. faktisk handling per time
    3. Identificerer uforklarede SOC-ændringer
    4. Identificerer Enphase-cloud overskrivninger
    5. Genererer dansk klartekst-rapport
    6. Sender rapport som HA persistent notification

DEL 3: Live SOC-tracking dashboard-widget
  (Implementeres separat som Lovelace-kort; denne fil leverer data-API)

Designprincipper:
  - Analysen må ALDRIG blokere LP-optimizeren
  - Data gemmes fra nu af — ingen historik før i dag
  - Rapporter max 10 linjer — kort og præcist
  - Alt på dansk
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from homeassistant.core import HomeAssistant

from .const import CONFIG_DIR, DATA_DB_FILE

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DEL 1 — Databaseudvidelse
# ---------------------------------------------------------------------------

_SCHEMA_EXTENSIONS = """
-- Tilføj de to nye kolonner til measurements hvis de ikke findes
"""

_ADDED_COLUMNS = (
    ("teo_actual_action", "TEXT"),
    ("teo_reasoning", "TEXT"),
)


class DecisionTracker:
    """Tracker planlagte vs. faktiske beslutninger og SOC-afvigelser."""

    def __init__(self, db_path: Optional[str] = None,
                 config_dir: str = CONFIG_DIR) -> None:
        self._path = db_path or str(Path(config_dir) / DATA_DB_FILE)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Tilføj tracking-kolonner til measurements hvis de mangler."""
        with self._lock, self._connect() as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(measurements)")}
            for col_name, col_type in _ADDED_COLUMNS:
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE measurements ADD COLUMN {col_name} {col_type}")
                    _LOGGER.info("Tilføjet kolonne %s til measurements-tabel", col_name)

    async def record_actual_action(
        self,
        hass: HomeAssistant,
        timestamp: datetime,
        planned_action: Optional[str],
        reasoning: Optional[str],
    ) -> None:
        """Læs faktisk handling fra HA-entiteter og opdater seneste measurement.

        Køres hver gang dataindsamlingen kører (hvert 5. minut).
        """
        # Aflæs faktisk tilstand fra HA-entiteter
        actual_action = await self._read_actual_action(hass)

        # Opdater seneste measurement-række med actual_action + reasoning
        await hass.async_add_executor_job(
            self._update_latest_measurement,
            timestamp,
            planned_action,
            actual_action,
            reasoning,
        )

    async def _read_actual_action(self, hass: HomeAssistant) -> str:
        """Aflæs hvad Envoy/Easee faktisk gør lige nu.

        Returnerer:
          "charging_grid"  — lader fra net
          "charging_solar" — lader fra sol
          "discharging"    — aflader
          "idle"           — idle
          "unknown"        — kan ikke fastslå
        """
        try:
            # 1. Tjek om batteri lader fra net (TEO's charge_from_grid switch)
            charge_from_grid_state = hass.states.get("switch.teo_enphase_charge_from_grid")
            charge_from_grid_on = (
                charge_from_grid_state is not None
                and charge_from_grid_state.state == "on"
            )

            # 2. Læs batteri-effekt (aggregeret fra Encharge-enheder)
            # Negativ værdi = lader (Enphase konvention)
            battery_power_kw = self._aggregate_battery_power_kw(hass)
            if battery_power_kw is None:
                return "unknown"

            # 3. Læs solproduktion (til at skelne sol-ladning fra net-ladning)
            solar_kw = self._envoy_power_kw(hass, "_current_power_production")
            if solar_kw is None:
                solar_kw = 0.0

            # Klassificér
            # BEMÆRK: Enphase bruger negativ effekt for ladning
            CHARGE_THRESHOLD = 0.1  # kW

            if battery_power_kw < -CHARGE_THRESHOLD:
                # Lader (negativ effekt) — fra net eller sol?
                if charge_from_grid_on:
                    return "charging_grid"
                elif solar_kw > 0.5:  # Sol producerer nok til at forklare ladningen
                    return "charging_solar"
                else:
                    return "charging_grid"  # Lader uden sol = må være net
            elif battery_power_kw > CHARGE_THRESHOLD:
                # Aflader (positiv effekt)
                return "discharging"
            else:
                return "idle"

        except Exception as err:
            _LOGGER.debug("Kunne ikke aflæse faktisk handling: %s", err)
            return "unknown"

    def _aggregate_battery_power_kw(self, hass: HomeAssistant) -> Optional[float]:
        """Samlet batterieffekt (kW) — samme logik som coordinator."""
        total = 0.0
        found = False
        for st in hass.states.async_all("sensor"):
            if (st.entity_id.startswith("sensor.encharge")
                    and st.attributes.get("device_class") == "power"):
                kw = self._normalise_power_kw(st)
                if kw is not None:
                    total += kw
                    found = True
        return round(total, 3) if found else None

    def _envoy_power_kw(self, hass: HomeAssistant, suffix: str) -> Optional[float]:
        """Find første sensor.envoy_*<suffix> — samme logik som coordinator."""
        for st in hass.states.async_all("sensor"):
            if st.entity_id.startswith("sensor.envoy_") and st.entity_id.endswith(suffix):
                return self._normalise_power_kw(st)
        return None

    def _normalise_power_kw(self, state) -> Optional[float]:
        """Konvertér effekt-sensor til kW (W → kW)."""
        try:
            val = float(state.state)
        except (ValueError, TypeError):
            return None
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        return round(val / 1000.0, 3) if unit == "w" else round(val, 3)

    def _update_latest_measurement(
        self,
        timestamp: datetime,
        planned_action: Optional[str],
        actual_action: str,
        reasoning: Optional[str],
    ) -> None:
        """Opdater seneste measurement med tracking-data (synkron SQLite-skrivning)."""
        ts_iso = timestamp.isoformat()

        # Find seneste measurement inden for ±2 min af timestamp
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT id FROM measurements
                   WHERE timestamp BETWEEN ? AND ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (
                    (timestamp - timedelta(minutes=2)).isoformat(),
                    (timestamp + timedelta(minutes=2)).isoformat(),
                )
            ).fetchone()

            if row is None:
                _LOGGER.debug("Ingen measurement fundet for %s — skipper tracking", ts_iso)
                return

            # Opdater rækken med tracking-data
            conn.execute(
                """UPDATE measurements
                   SET teo_actual_action = ?, teo_reasoning = ?
                   WHERE id = ?""",
                (actual_action, reasoning, row["id"])
            )
            _LOGGER.debug(
                "Tracking opdateret: planned=%s actual=%s",
                planned_action or "(ingen plan)",
                actual_action,
            )

    # -----------------------------------------------------------------------
    # DEL 2 — Daglig afvigelses-analyse
    # -----------------------------------------------------------------------

    def analyze_last_24h(self, now: Optional[datetime] = None) -> dict[str, Any]:
        """Analysér seneste 24 timer og returner rapport-data.

        Returnerer:
          {
            "total_measurements": int,
            "plan_matches": int,
            "plan_mismatches": int,
            "unexplained_soc_changes": list[dict],  # [{timestamp, soc_change_pct, reason}, ...]
            "enphase_overrides": list[dict],        # [{timestamp, planned, actual}, ...]
            "report_lines": list[str],              # Dansk klartekst (max 10 linjer)
          }
        """
        now = now or datetime.now()
        since = now - timedelta(hours=24)

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT timestamp, battery_soc_pct, battery_power_kw,
                          solar_production_kw, grid_import_kw, ev_total_kw,
                          teo_action, teo_actual_action, teo_reasoning,
                          nordpool_price_ore
                   FROM measurements
                   WHERE timestamp >= ?
                   ORDER BY timestamp ASC""",
                (since.isoformat(),)
            ).fetchall()

        if not rows:
            return {
                "total_measurements": 0,
                "plan_matches": 0,
                "plan_mismatches": 0,
                "unexplained_soc_changes": [],
                "enphase_overrides": [],
                "report_lines": ["Ingen data tilgængelig for de seneste 24 timer."],
            }

        total = len(rows)
        matches = 0
        mismatches = 0
        unexplained_soc = []
        enphase_overrides = []

        prev_soc = None
        for i, row in enumerate(rows):
            ts = row["timestamp"]
            soc = row["battery_soc_pct"]
            planned = row["teo_action"]
            actual = row["teo_actual_action"]

            # 1. Sammenlign planlagt vs. faktisk
            if planned and actual and actual != "unknown":
                # Map teo_action til actual_action-format
                planned_norm = self._normalize_action(planned)
                if planned_norm == actual:
                    matches += 1
                else:
                    mismatches += 1
                    # Er det en Enphase-overskrivning?
                    if self._is_enphase_override(planned, actual, row):
                        enphase_overrides.append({
                            "timestamp": ts,
                            "planned": planned,
                            "actual": actual,
                        })

            # 2. Identificer uforklarede SOC-ændringer
            if prev_soc is not None and soc is not None:
                soc_change = soc - prev_soc
                # Signifikant ændring (>5% på 5 min) uden planlagt handling?
                if abs(soc_change) > 5.0:
                    if not planned or planned == "BATTERY_IDLE":
                        unexplained_soc.append({
                            "timestamp": ts,
                            "soc_change_pct": round(soc_change, 1),
                            "reason": "Ingen planlagt handling",
                        })

            prev_soc = soc

        # Generér dansk rapport (max 10 linjer)
        report = self._build_report(
            now, total, matches, mismatches, unexplained_soc, enphase_overrides
        )

        return {
            "total_measurements": total,
            "plan_matches": matches,
            "plan_mismatches": mismatches,
            "unexplained_soc_changes": unexplained_soc,
            "enphase_overrides": enphase_overrides,
            "report_lines": report,
        }

    def _normalize_action(self, teo_action: str) -> str:
        """Map teo_action-konstanter til actual_action-format."""
        mapping = {
            "BATTERY_CHARGE_GRID": "charging_grid",
            "BATTERY_CHARGE_SOLAR": "charging_solar",
            "BATTERY_DISCHARGE": "discharging",
            "BATTERY_IDLE": "idle",
            "NO_GRID_CHARGE_SOLAR": "charging_solar",
        }
        return mapping.get(teo_action, "unknown")

    def _is_enphase_override(self, planned: str, actual: str, row: sqlite3.Row) -> bool:
        """Tjek om Enphase-cloud overskrev TEO.

        Kendetegn:
          - TEO planlagde idle/discharge
          - Faktisk handling var charging_grid
          - charge_from_grid-switch blev slået til uden TEO's OK
        """
        # Simpel heuristik: TEO ville idle/discharge, men batteriet lader fra net
        if planned in ("BATTERY_IDLE", "BATTERY_DISCHARGE"):
            if actual == "charging_grid":
                return True
        return False

    def _build_report(
        self,
        now: datetime,
        total: int,
        matches: int,
        mismatches: int,
        unexplained_soc: list[dict],
        enphase_overrides: list[dict],
    ) -> list[str]:
        """Byg dansk klartekst-rapport (max 10 linjer)."""
        lines = []
        lines.append(f"TEO Afvigelses-analyse — {now.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"Periode: Seneste 24 timer ({total} målinger)")

        if total > 0:
            match_pct = 100.0 * matches / total
            lines.append(f"Plan fulgt: {matches}/{total} ({match_pct:.0f}%)")

        if mismatches > 0:
            lines.append(f"⚠️  Afvigelser: {mismatches} tilfælde")

        if enphase_overrides:
            lines.append(f"☁️  Enphase-cloud overskrev TEO: {len(enphase_overrides)} gange")
            # Vis seneste overskrivning
            latest = enphase_overrides[-1]
            ts = datetime.fromisoformat(latest["timestamp"]).strftime("%H:%M")
            lines.append(f"   Seneste kl. {ts}: planlagt {latest['planned']}, blev {latest['actual']}")

        if unexplained_soc:
            lines.append(f"🔍 Uforklarede SOC-ændringer: {len(unexplained_soc)}")
            # Vis største ændring
            biggest = max(unexplained_soc, key=lambda x: abs(x["soc_change_pct"]))
            ts = datetime.fromisoformat(biggest["timestamp"]).strftime("%H:%M")
            change = biggest["soc_change_pct"]
            lines.append(f"   Kl. {ts}: {change:+.1f}% uden planlagt handling")

        if not mismatches and not enphase_overrides and not unexplained_soc:
            lines.append("✅ Ingen afvigelser fundet — TEO fulgte planen perfekt")

        # Trim til max 10 linjer
        return lines[:10]

    # -----------------------------------------------------------------------
    # DEL 3 — Data-API til dashboard-widget
    # -----------------------------------------------------------------------

    def get_soc_timeline(
        self,
        hours: int = 24,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Hent SOC-tidslinje + planlagte handlinger til dashboard-graf.

        Returnerer:
          {
            "timestamps": [iso-string, ...],
            "soc_pct": [float, ...],
            "planned_actions": [str, ...],     # teo_action for hvert tidspunkt
            "actual_actions": [str, ...],      # teo_actual_action
            "battery_power_kw": [float, ...],  # til at vise lad/aflad-intensitet
          }
        """
        now = now or datetime.now()
        since = now - timedelta(hours=hours)

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT timestamp, battery_soc_pct, battery_power_kw,
                          teo_action, teo_actual_action
                   FROM measurements
                   WHERE timestamp >= ?
                   ORDER BY timestamp ASC""",
                (since.isoformat(),)
            ).fetchall()

        return {
            "timestamps": [r["timestamp"] for r in rows],
            "soc_pct": [r["battery_soc_pct"] for r in rows],
            "planned_actions": [r["teo_action"] for r in rows],
            "actual_actions": [r["teo_actual_action"] for r in rows],
            "battery_power_kw": [r["battery_power_kw"] for r in rows],
        }

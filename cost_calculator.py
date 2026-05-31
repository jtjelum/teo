"""Besparelsesberegning — spec DEL 4 / DEL 5.2.

Beregner hvad husstanden faktisk betalte kontra en baseline uden TEO
(batteri/sol/optimering), så dashboardet kan vise besparelsen i klartekst.

Metode (spec 5.2):
* **Faktisk omkostning** = nettoudgift til nettet: importeret energi gange
  importprisen (spot + tarif + moms) minus indtjening fra eksport.
* **Baseline** = alt husforbrug gange den gennemsnitlige importpris i perioden —
  altså som om hver kWh var købt fra nettet uden eget system.
* **Besparelse** = baseline − faktisk.

Energien integreres fra 5-minutters-snapshots ved at gange effekten med tiden
til forrige måling (begrænset, så et hul i data ikke giver en kæmpe "kWh").
Modulet er synkront og køres via ``hass.async_add_executor_job``.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .const import (
    CONFIG_DIR,
    DATA_COLLECTION_INTERVAL_MINUTES,
    DATA_DB_FILE,
    DEFAULT_NETWORK_TARIFF_ORE,
    DEFAULT_VAT_PERCENT,
)

_LOGGER = logging.getLogger(__name__)

# Maksimal tid ét snapshot må "dække" ved energiintegration (2× kadencen),
# så et datahul ikke fejlagtigt tæller som timelangt forbrug.
_MAX_INTERVAL_H = (DATA_COLLECTION_INTERVAL_MINUTES * 2) / 60.0
_NOMINAL_INTERVAL_H = DATA_COLLECTION_INTERVAL_MINUTES / 60.0


def import_price_ore(spot_ore: float) -> float:
    """Importpris: spot + nettarif, plus moms."""
    return (spot_ore + DEFAULT_NETWORK_TARIFF_ORE) * (1 + DEFAULT_VAT_PERCENT / 100.0)


def export_price_ore(spot_ore: float) -> float:
    """Salgspris ved eksport (forenklet: rå spotpris)."""
    return spot_ore


class CostCalculator:
    """Beregner faktisk omkostning, baseline og besparelse pr. periode."""

    def __init__(self, db_path: Optional[str] = None,
                 config_dir: str = CONFIG_DIR) -> None:
        self._path = db_path or str(Path(config_dir) / DATA_DB_FILE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- offentligt API -------------------------------------------------
    def run(self, zone: Optional[str] = None,
            now: Optional[datetime] = None,
            upsert_daily=None) -> dict[str, Any]:
        """Beregn dag + måned. Skriver dagens tal til daily_summary hvis
        ``upsert_daily`` (DataCollector.upsert_daily) gives med."""
        now = now or datetime.now()
        today = now.date()
        month_start = today.replace(day=1)

        today_stats = self.compute_period(
            datetime.combine(today, datetime.min.time()), now)
        month_stats = self.compute_period(
            datetime.combine(month_start, datetime.min.time()), now)

        if upsert_daily is not None and today_stats.get("samples"):
            try:
                upsert_daily(today.isoformat(), zone, {
                    "estimated_cost_dkk": today_stats["actual_cost_dkk"],
                    "baseline_cost_dkk": today_stats["baseline_cost_dkk"],
                    "estimated_saving_dkk": today_stats["saving_dkk"],
                    "solar_total_kwh": today_stats["solar_kwh"],
                    "grid_import_total_kwh": today_stats["grid_import_kwh"],
                    "grid_export_total_kwh": today_stats["grid_export_kwh"],
                    "battery_charged_kwh": today_stats["battery_charged_kwh"],
                    "battery_discharged_kwh": today_stats["battery_discharged_kwh"],
                    "ev_charged_kwh": today_stats["ev_charged_kwh"],
                    "house_base_kwh": today_stats["house_kwh"],
                })
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Kunne ikke skrive daily_summary: %s", err)

        return {"today": today_stats, "month": month_stats}

    def compute_period(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Integrér energi og omkostning mellem to tidspunkter."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT timestamp, solar_production_kw, house_consumption_kw,
                              battery_power_kw, grid_import_kw, grid_export_kw,
                              ev_total_kw, nordpool_price_ore
                       FROM measurements
                       WHERE timestamp >= ? AND timestamp <= ?
                       ORDER BY timestamp ASC""",
                    (start.isoformat(), end.isoformat()),
                ).fetchall()
        except sqlite3.Error as err:
            _LOGGER.debug("cost compute_period db-fejl: %s", err)
            rows = []

        solar = house = batt_chg = batt_dis = grid_imp = grid_exp = ev = 0.0
        actual_cost_ore = earnings_ore = grid_cost_ore = 0.0
        import_prices: list[float] = []
        prev_ts: Optional[datetime] = None

        for r in rows:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
            except (ValueError, TypeError):
                continue
            if prev_ts is None:
                dt_h = _NOMINAL_INTERVAL_H
            else:
                dt_h = min((ts - prev_ts).total_seconds() / 3600.0, _MAX_INTERVAL_H)
            prev_ts = ts

            solar += (r["solar_production_kw"] or 0.0) * dt_h
            house += (r["house_consumption_kw"] or 0.0) * dt_h
            ev += (r["ev_total_kw"] or 0.0) * dt_h
            bp = r["battery_power_kw"]
            if bp is not None:
                if bp > 0:
                    batt_chg += bp * dt_h
                else:
                    batt_dis += -bp * dt_h
            imp_kwh = (r["grid_import_kw"] or 0.0) * dt_h
            exp_kwh = (r["grid_export_kw"] or 0.0) * dt_h
            grid_imp += imp_kwh
            grid_exp += exp_kwh

            spot = r["nordpool_price_ore"]
            if spot is not None:
                ip = import_price_ore(spot)
                import_prices.append(ip)
                grid_cost_ore += imp_kwh * ip
                earnings_ore += exp_kwh * export_price_ore(spot)

        actual_cost_ore = grid_cost_ore - earnings_ore
        avg_import_price = statistics.mean(import_prices) if import_prices else None
        baseline_cost_ore = (house * avg_import_price
                             if avg_import_price is not None else None)
        saving_ore = (baseline_cost_ore - actual_cost_ore
                      if baseline_cost_ore is not None else None)
        avg_paid = (actual_cost_ore / house) if house > 0 else None

        return {
            "samples": len(rows),
            "solar_kwh": round(solar, 3),
            "house_kwh": round(house, 3),
            "ev_charged_kwh": round(ev, 3),
            "battery_charged_kwh": round(batt_chg, 3),
            "battery_discharged_kwh": round(batt_dis, 3),
            "grid_import_kwh": round(grid_imp, 3),
            "grid_export_kwh": round(grid_exp, 3),
            "actual_cost_dkk": round(actual_cost_ore / 100.0, 2),
            "baseline_cost_dkk": (round(baseline_cost_ore / 100.0, 2)
                                  if baseline_cost_ore is not None else None),
            "saving_dkk": (round(saving_ore / 100.0, 2)
                           if saving_ore is not None else None),
            "earnings_dkk": round(earnings_ore / 100.0, 2),
            "grid_cost_dkk": round(grid_cost_ore / 100.0, 2),
            "avg_price_paid_ore": (round(avg_paid, 2) if avg_paid is not None else None),
            "avg_price_baseline_ore": (round(avg_import_price, 2)
                                       if avg_import_price is not None else None),
        }

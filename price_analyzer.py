"""Prisarbitrage-analyse — spec DEL 3 (kører dagligt kl. 13:30).

Køres ~30 min efter Nord Pool offentliggør morgendagens priser og lægger en
strategi for det kommende døgn:

* 3.1 Aftenspris-index — er kl. 17-21 markant dyrere end dagsgennemsnittet?
* 3.2 Natte-ladningsvindue — billigste sammenhængende 3-timers vindue kl. 00-07,
  kombineret med morgendagens solprognose (Solcast; valgfri).
* 3.3 Multi-dag — er morgendagen billigere end i dag? Så vent med dyr ladning.
* 3.4 Vind-pris — høj vind giver typisk lav DK-pris (modifikator).
* 3.6 Dag-scenarie A-E.
* 3.7 Rebound — høj pris der pludselig falder; undgå at købe dyrt lige inden.

Analysen er ren (ingen I/O): den får prisserien + valgfri sol/vind ind og
returnerer et struktureret resultat, som kalderen persisterer i daily_summary.
Det gør logikken let at enhedsteste og uafhængig af Solcast-status.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from .const import (
    DEFAULT_RECALCULATE_ON_PRICE_SPIKE_ORE,
    EVENING_PEAK_END_HOUR,
    EVENING_PEAK_INDEX_THRESHOLD,
    EVENING_PEAK_START_HOUR,
    EVENING_TARGET_SOC_PCT,
    HIGH_WIND_MS,
    NIGHT_WINDOW_END_HOUR,
    NIGHT_WINDOW_HOURS,
    NIGHT_WINDOW_START_HOUR,
    SCENARIO_A,
    SCENARIO_B,
    SCENARIO_C,
    SCENARIO_D,
    SCENARIO_E,
    SOLAR_TOMORROW_HIGH_KWH,
    SOLAR_TOMORROW_LOW_KWH,
)

_LOGGER = logging.getLogger(__name__)


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


class PriceAnalyzer:
    """Analyserer en prisserie og udleder en dagsstrategi."""

    def __init__(self, charge_below_ore: float, use_battery_above_ore: float) -> None:
        self._charge_below = charge_below_ore
        self._use_above = use_battery_above_ore

    def analyze(
        self,
        prices: dict[datetime, float],
        planning_date: date,
        *,
        today_date: Optional[date] = None,
        tomorrow_solar_kwh: Optional[float] = None,
        wind_ms: Optional[float] = None,
    ) -> dict[str, Any]:
        """Returnér dagsstrategi for ``planning_date`` (typisk i morgen)."""
        by_hour = {dt.hour: p for dt, p in prices.items()
                   if dt.date() == planning_date}
        if not by_hour:
            return {"available": False, "reason": "ingen priser for planlægningsdato"}

        values = list(by_hour.values())
        day_avg = _mean(values)
        day_min = round(min(values), 2)
        day_max = round(max(values), 2)
        volatility = round(max(values) - min(values), 2)

        result: dict[str, Any] = {
            "available": True,
            "planning_date": planning_date.isoformat(),
            "day_avg_ore": day_avg,
            "day_min_ore": day_min,
            "day_max_ore": day_max,
            "volatility_ore": volatility,
        }
        result.update(self._evening_index(by_hour, day_avg))
        result.update(self._night_window(by_hour, tomorrow_solar_kwh))
        result.update(self._multi_day(prices, planning_date, today_date, day_avg))
        result["rebound"] = self._rebound(prices)
        result["day_scenario"] = self._scenario(
            day_avg, result.get("night_window_avg_ore"),
            tomorrow_solar_kwh, wind_ms)
        return result

    # 3.1 ----------------------------------------------------------------
    def _evening_index(self, by_hour: dict[int, float],
                       day_avg: Optional[float]) -> dict[str, Any]:
        evening = [p for h, p in by_hour.items()
                   if EVENING_PEAK_START_HOUR <= h <= EVENING_PEAK_END_HOUR]
        evening_avg = _mean(evening)
        if evening_avg is None or not day_avg:
            return {"evening_avg_ore": evening_avg, "evening_index": None,
                    "evening_expensive": False, "target_soc_pct": None}
        index = round(evening_avg / day_avg, 2)
        expensive = index > EVENING_PEAK_INDEX_THRESHOLD
        return {
            "evening_avg_ore": evening_avg,
            "evening_index": index,
            "evening_expensive": expensive,
            # Lad batteriet op til mål-SOC inden aftenperioden hvis den er dyr.
            "target_soc_pct": EVENING_TARGET_SOC_PCT if expensive else None,
        }

    # 3.2 ----------------------------------------------------------------
    def _night_window(self, by_hour: dict[int, float],
                      tomorrow_solar_kwh: Optional[float]) -> dict[str, Any]:
        night_hours = [h for h in range(NIGHT_WINDOW_START_HOUR, NIGHT_WINDOW_END_HOUR)
                       if h in by_hour]
        best_start: Optional[int] = None
        best_avg: Optional[float] = None
        # Glidende vindue af NIGHT_WINDOW_HOURS sammenhængende timer.
        for start in night_hours:
            window = [by_hour[start + i] for i in range(NIGHT_WINDOW_HOURS)
                      if (start + i) in by_hour]
            if len(window) < NIGHT_WINDOW_HOURS:
                continue
            avg = sum(window) / NIGHT_WINDOW_HOURS
            if best_avg is None or avg < best_avg:
                best_avg, best_start = avg, start

        # Kombiner med solprognose (spec 3.2). Ukendt sol → neutral anbefaling.
        if tomorrow_solar_kwh is None:
            recommendation = "normal"
        elif tomorrow_solar_kwh > SOLAR_TOMORROW_HIGH_KWH:
            recommendation = "reducer"        # masser af sol i morgen
        elif tomorrow_solar_kwh < SOLAR_TOMORROW_LOW_KWH:
            recommendation = "aggressiv"       # lidt sol → lad om natten
        else:
            recommendation = "normal"
        return {
            "night_window_start_hour": best_start,
            "night_window_avg_ore": round(best_avg, 2) if best_avg is not None else None,
            "night_charge_recommendation": recommendation,
        }

    # 3.3 ----------------------------------------------------------------
    def _multi_day(self, prices: dict[datetime, float], planning_date: date,
                   today_date: Optional[date], planning_avg: Optional[float]
                   ) -> dict[str, Any]:
        if today_date is None or today_date == planning_date:
            return {"multi_day_wait": False, "today_avg_ore": None}
        today_vals = [p for dt, p in prices.items() if dt.date() == today_date]
        today_avg = _mean(today_vals)
        if today_avg is None or planning_avg is None:
            return {"multi_day_wait": False, "today_avg_ore": today_avg}
        # Er det kommende døgn billigere end i dag? Så undgå dyr ladning nu.
        return {
            "multi_day_wait": planning_avg < today_avg,
            "today_avg_ore": today_avg,
        }

    # 3.7 ----------------------------------------------------------------
    def _rebound(self, prices: dict[datetime, float]) -> dict[str, Any]:
        """Find en høj pris der efterfølges af et markant fald (rebound)."""
        ordered = [p for _, p in sorted(prices.items())]
        for i in range(len(ordered) - 1):
            if ordered[i] > self._use_above:
                drop = ordered[i] - ordered[i + 1]
                if drop >= DEFAULT_RECALCULATE_ON_PRICE_SPIKE_ORE:
                    return {"detected": True, "from_ore": round(ordered[i], 2),
                            "to_ore": round(ordered[i + 1], 2),
                            "drop_ore": round(drop, 2)}
        return {"detected": False}

    # 3.6 ----------------------------------------------------------------
    def _scenario(self, day_avg: Optional[float], night_avg: Optional[float],
                  tomorrow_solar_kwh: Optional[float],
                  wind_ms: Optional[float]) -> Optional[str]:
        low_price = day_avg is not None and day_avg < self._charge_below
        high_price = day_avg is not None and day_avg > self._use_above
        has_solar = (tomorrow_solar_kwh is not None
                     and tomorrow_solar_kwh >= SOLAR_TOMORROW_LOW_KWH)
        surplus_solar = (tomorrow_solar_kwh is not None
                         and tomorrow_solar_kwh > SOLAR_TOMORROW_HIGH_KWH)
        high_wind = wind_ms is not None and wind_ms > HIGH_WIND_MS

        if surplus_solar:
            return SCENARIO_D            # Sol-overskud
        if has_solar and low_price:
            return SCENARIO_A            # Sol + lav pris
        if high_wind:
            return SCENARIO_E            # Høj vind → forvent lav pris
        if not has_solar and high_price:
            return SCENARIO_C            # Ingen sol + høj dag
        if not has_solar:
            return SCENARIO_B            # Ingen sol + (typisk) lav nat
        return None

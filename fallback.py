"""Regelbaseret fallback — failsafe ved optimeringsfejl.

Spec §3.4. Designprincip #6 (Failsafe): hvis LP-optimering fejler, falder
systemet tilbage til denne enkle, deterministiske regelmotor. Den producerer
ALTID et sikkert resultat — aldrig en ukontrolleret tilstand.

Modulet er ren logik uden brugervendt tekst (designprincip #7): det returnerer
strukturerede beslutninger med ``action_type`` + kontekst, og decision_log.py
oversætter dem til dansk/engelsk klartekst. Beslutninger herfra markeres
``fallback=True`` så loggen kan tilføje "[FALLBACK]"-mærket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .const import (
    ACTION_BATTERY_CHARGE_GRID,
    ACTION_BATTERY_DISCHARGE,
    ACTION_BATTERY_IDLE,
    ACTION_EV_ALLOWED,
    ACTION_EV_PAUSE_SOC,
    BATTERY_ACTION_CHARGE,
    BATTERY_ACTION_DISCHARGE,
    BATTERY_ACTION_IDLE,
)


@dataclass
class FallbackInputs:
    """Minimal input som fallback har brug for. Alle felter er øjebliksværdier."""

    current_price_ore: float
    battery_soc_pct: float
    ev_protection_soc_pct: float
    charge_from_grid_below_ore: float
    use_battery_above_ore: float
    min_soc_pct: float


@dataclass
class FallbackDecision:
    """Sikker øjebliksbeslutning. Kortlægges 1:1 til en beslutningslog-entry."""

    battery_action: str            # charge | discharge | idle
    charge_from_grid: bool         # True = aktiver netladning af batteri
    ev_allowed: bool               # False = pause EV-ladning (0 A)
    battery_action_type: str       # ACTION_BATTERY_* til loggen
    ev_action_type: str            # ACTION_EV_* til loggen
    context: dict = field(default_factory=dict)
    fallback: bool = True          # altid True — dette ER fald-tilbage-motoren


def run_fallback(inputs: FallbackInputs) -> FallbackDecision:
    """Beregn en sikker beslutning ud fra de prioriterede regler i spec §3.4.

    Rækkefølge (vigtig — batteribeskyttelse vinder altid):
      1. Batteribeskyttelse: SOC < ev_protection  → EV = 0 A
      2. Pristærskler:       pris < charge_below   → lad batteri fra net
                             pris > use_above       → aflad batteri
                             ellers                 → idle (inverter styrer selv)
      3. EV-ladning:         SOC >= ev_protection   → fuld strøm tilladt
                             ellers                 → 0 A (følger regel 1)
    """
    # --- Regel 1 + 3: EV-beskyttelse baseret på SOC ---------------------
    ev_protected = inputs.battery_soc_pct < inputs.ev_protection_soc_pct
    ev_allowed = not ev_protected
    ev_action_type = ACTION_EV_PAUSE_SOC if ev_protected else ACTION_EV_ALLOWED

    # --- Regel 2: simple pristærskler -----------------------------------
    if inputs.current_price_ore < inputs.charge_from_grid_below_ore:
        battery_action = BATTERY_ACTION_CHARGE
        charge_from_grid = True
        battery_action_type = ACTION_BATTERY_CHARGE_GRID
    elif inputs.current_price_ore > inputs.use_battery_above_ore:
        battery_action = BATTERY_ACTION_DISCHARGE
        charge_from_grid = False
        battery_action_type = ACTION_BATTERY_DISCHARGE
    else:
        battery_action = BATTERY_ACTION_IDLE
        charge_from_grid = False
        battery_action_type = ACTION_BATTERY_IDLE

    # Aflad aldrig under min-SOC, selv i fallback (ekstra sikkerhedsspærre).
    if (
        battery_action == BATTERY_ACTION_DISCHARGE
        and inputs.battery_soc_pct <= inputs.min_soc_pct
    ):
        battery_action = BATTERY_ACTION_IDLE
        battery_action_type = ACTION_BATTERY_IDLE

    return FallbackDecision(
        battery_action=battery_action,
        charge_from_grid=charge_from_grid,
        ev_allowed=ev_allowed,
        battery_action_type=battery_action_type,
        ev_action_type=ev_action_type,
        context={
            "soc_pct": inputs.battery_soc_pct,
            "price_ore": inputs.current_price_ore,
            "fallback": True,
            "solver_used": None,
        },
    )


def build_fallback_result(decision: FallbackDecision, timestamp) -> dict:
    """Pak en fallback-beslutning ind i samme form som ``optimizer.run()``.

    Lader coordinatoren behandle optimering og fallback ens. Planen er ét
    skridt ("nu"), da fallback er rent reaktiv og ikke planlægger frem.
    """
    return {
        "plan": [
            {
                "timestamp": timestamp,
                "battery_action": decision.battery_action,
                "battery_power_kw": None,
                "grid_import_kw": None,
                "ev_allowed": decision.ev_allowed,
                "reasoning": None,  # genereres tosproget i decision_log
            }
        ],
        "summary": {
            "estimated_cost_dkk": None,
            "estimated_saving_dkk": None,
            "battery_cycles_today": None,
            "degradation_cost_dkk": None,
            "net_gain_dkk": None,
        },
        "solver_status": "failed",
        "fallback_used": True,
        "decision": decision,
    }

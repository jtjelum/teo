"""Optimeringsmotor — LP-model for batteri/net/EV (spec §3.3).

Implementerer TEO's lineære program med ``scipy.optimize.linprog`` og
HiGHS-solveren (``method="highs"``). HiGHS er præcis den solver spec'en kalder
på, og scipy/HiGHS er væsentligt lettere at installere på en Raspberry Pi
(aarch64-wheels) end CVXPY — derfor kan optimeringen køre direkte i HA-kernen.

Mål (minimering, i øre):
    Σ ( (spotpris[t]+tarif) · net_import[t] · Δt  +  degradering · (lad+aflad)[t] · Δt )

Begrænsninger:
    sol + net_import + aflad − net_eksport − lad − ev = forbrug      (ligevægt)
    SOC[t] = SOC[t−1] + η_lad·P_lad·Δt − (1/η_aflad)·P_aflad·Δt        (dynamik)
    SOC_min ≤ SOC[t] ≤ SOC_max,  0 ≤ P ≤ P_max                        (grænser)
    Σ ev·Δt ≥ ev_energibehov                                          (EV)

Fejler solveren (eller mangler scipy) kastes ``OptimizerUnavailable`` så
coordinatoren aktiverer den regelbaserede fallback (designprincip #6).

Designprincip #7: returnerer strukturerede beslutninger med ``action_type`` —
aldrig færdig tekst. decision_log oversætter.
"""

from __future__ import annotations

import logging
from typing import Any

from .const import (
    ACTION_BATTERY_CHARGE_GRID,
    ACTION_BATTERY_DISCHARGE,
    ACTION_BATTERY_IDLE,
    BATTERY_ACTION_CHARGE,
    BATTERY_ACTION_DISCHARGE,
    BATTERY_ACTION_IDLE,
    SOLVER_HIGHS,
    SOLVER_STATUS_OPTIMAL,
)

_LOGGER = logging.getLogger(__name__)

_POWER_EPS_KW = 0.05  # tærskel for at klassificere lad/aflad/idle


class OptimizerUnavailable(Exception):
    """Kastes når LP'en ikke kan løses (manglende scipy, infeasible, fejl)."""


class SolverFailed(OptimizerUnavailable):
    """Solveren returnerede ikke en optimal/feasible løsning."""


def run(inputs: dict[str, Any]) -> dict[str, Any]:
    """Kør optimeringen. Returnerer plan + summary i spec §3.3-format."""
    try:
        import numpy as np
        from scipy.optimize import linprog
    except ImportError as err:
        raise OptimizerUnavailable(f"scipy/numpy ikke installeret: {err}") from err
    return _solve(inputs, np, linprog)


def _timeline(inputs: dict[str, Any]) -> list:
    return sorted(inputs["spot_prices"].keys())


def _solve(inputs: dict[str, Any], np, linprog) -> dict[str, Any]:  # noqa: ANN001
    times = _timeline(inputs)
    n = len(times)
    if n == 0:
        raise OptimizerUnavailable("ingen prisdata")

    dt = inputs.get("timestep_minutes", 60) / 60.0
    prices = [float(inputs["spot_prices"][t]) for t in times]   # øre/kWh
    tariff = float(inputs.get("network_tariff_ore", 0.0))
    eff_c = float(inputs.get("battery_charge_efficiency", 0.95))
    eff_d = float(inputs.get("battery_discharge_efficiency", 0.95))
    degr = float(inputs.get("degradation_cost_dkk_per_kwh", 0.04)) * 100.0  # → øre/kWh

    soc0 = float(inputs["battery_soc_kwh"])
    soc_min = float(inputs["battery_min_soc_kwh"])
    soc_max = float(inputs["battery_max_soc_kwh"])
    pc_max = float(inputs.get("battery_max_charge_kw", 3.84))
    pd_max = float(inputs.get("battery_max_discharge_kw", 3.84))

    unc = float(inputs.get("solar_uncertainty_factor", 0.85))
    solar = [float(inputs.get("solar_forecast_p50", {}).get(t, 0.0)) * unc for t in times]
    load = [float(inputs.get("load_forecast_kw", {}).get(t, 0.0)) for t in times]
    ev_demand = float(inputs.get("ev_energy_demand_kwh", 0.0))
    ev_max = float(inputs.get("ev_max_power_kw", 0.0))

    # Variabel-layout: [pc(n) | pd(n) | gimp(n) | gexp(n) | ev(n) | soc(n)]
    PC, PD, GI, GE, EV, SOC = (k * n for k in range(6))
    nv = 6 * n

    c = np.zeros(nv)
    for i in range(n):
        c[GI + i] = (prices[i] + tariff) * dt    # importomkostning (spot + tarif)
        c[GE + i] = -prices[i] * dt              # eksportindtægt (rå spotpris)
        c[PC + i] = degr * dt                    # slid ved ladning
        c[PD + i] = degr * dt                    # slid ved afladning

    # Ligheder: energibalance (n) + SOC-dynamik (n)
    A_eq = np.zeros((2 * n, nv))
    b_eq = np.zeros(2 * n)
    for i in range(n):
        # Balance: gimp + pd - gexp - pc - ev = load - solar
        A_eq[i, GI + i] = 1.0
        A_eq[i, PD + i] = 1.0
        A_eq[i, GE + i] = -1.0
        A_eq[i, PC + i] = -1.0
        A_eq[i, EV + i] = -1.0
        b_eq[i] = load[i] - solar[i]
        # SOC-dynamik: soc[i] - soc[i-1] - eff_c*pc*dt + pd*dt/eff_d = (soc0 hvis i==0)
        r = n + i
        A_eq[r, SOC + i] = 1.0
        A_eq[r, PC + i] = -eff_c * dt
        A_eq[r, PD + i] = dt / eff_d
        if i == 0:
            b_eq[r] = soc0
        else:
            A_eq[r, SOC + i - 1] = -1.0
            b_eq[r] = 0.0

    # Uligheder samles i en liste ( funktioner kan tilføje hårde begrænsninger).
    ub_rows: list = []
    ub_b: list = []

    # EV-energibehov dækkes:  -Σ ev*dt <= -ev_demand
    if ev_demand > 0 and ev_max > 0:
        row = np.zeros(nv)
        for i in range(n):
            row[EV + i] = -dt
        ub_rows.append(row)
        ub_b.append(-ev_demand)

    # HÅRD: netladning af batteri forbudt (switch.teo_charge_from_grid_allowed=off).
    # gimp[i] - ev[i] <= load[i]  ⇒  netimport dækker kun forbrug+EV, aldrig
    # batteriladning (afledt: pc[i] <= sol[i] + aflad − eksport).
    if not bool(inputs.get("allow_grid_charge", True)):
        for i in range(n):
            row = np.zeros(nv)
            row[GI + i] = 1.0
            row[EV + i] = -1.0
            ub_rows.append(row)
            ub_b.append(load[i])

    A_ub = np.array(ub_rows) if ub_rows else None
    b_ub = np.array(ub_b) if ub_b else None

    # HÅRD: salg ved negativ pris forbudt (switch.teo_sell_at_negative_price=off):
    # luk netto-eksport i de timer hvor spotprisen er negativ.
    allow_neg = bool(inputs.get("allow_negative_export", True))
    ge_bounds = [
        (0.0, 0.0) if (not allow_neg and prices[i] < 0) else (0.0, None)
        for i in range(n)
    ]

    bounds = (
        [(0.0, pc_max)] * n
        + [(0.0, pd_max)] * n
        + [(0.0, None)] * n
        + ge_bounds
        + [(0.0, ev_max)] * n
        + [(soc_min, soc_max)] * n
    )

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method="highs")
    if not res.success:
        raise SolverFailed(f"linprog: {res.message}")

    x = res.x
    return _build_result(
        times, dt, prices,
        pc=x[PC:PC + n], pd=x[PD:PD + n], gimp=x[GI:GI + n], gexp=x[GE:GE + n],
        soc=x[SOC:SOC + n], ev=x[EV:EV + n], degr_ore=degr,
    )


def _build_result(times, dt, prices, pc, pd, gimp, gexp, soc, ev, degr_ore) -> dict[str, Any]:
    plan: list[dict[str, Any]] = []
    total_cost_ore = 0.0
    cycles = 0.0

    for i, t in enumerate(times):
        charge_kw = float(pc[i])
        discharge_kw = float(pd[i])
        cycles += charge_kw * dt

        if charge_kw > _POWER_EPS_KW and charge_kw >= discharge_kw:
            action, action_type = BATTERY_ACTION_CHARGE, ACTION_BATTERY_CHARGE_GRID
        elif discharge_kw > _POWER_EPS_KW:
            action, action_type = BATTERY_ACTION_DISCHARGE, ACTION_BATTERY_DISCHARGE
        else:
            action, action_type = BATTERY_ACTION_IDLE, ACTION_BATTERY_IDLE

        total_cost_ore += float(gimp[i]) * prices[i] * dt
        plan.append({
            "timestamp": t,
            "battery_action": action,
            "battery_action_type": action_type,
            "battery_power_kw": round(charge_kw - discharge_kw, 3),
            "grid_import_kw": round(float(gimp[i]), 3),
            "grid_export_kw": round(float(gexp[i]), 3),
            "ev_allowed": float(ev[i]) > _POWER_EPS_KW,
            "soc_kwh": round(float(soc[i]), 3),
            "price_ore": round(prices[i], 2),
            "reasoning": None,
        })

    degradation_dkk = degr_ore / 100.0 * cycles
    return {
        "plan": plan,
        "summary": {
            "estimated_cost_dkk": round(total_cost_ore / 100.0, 2),
            "estimated_saving_dkk": None,   # udfyldes af coordinator (vs. baseline)
            "battery_cycles_today": round(cycles, 3),
            "degradation_cost_dkk": round(degradation_dkk, 2),
            "net_gain_dkk": None,
        },
        "solver_status": SOLVER_STATUS_OPTIMAL,
        "solver_used": SOLVER_HIGHS,
        "fallback_used": False,
    }

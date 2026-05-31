"""Solprognose fra Solcast — fodrer optimizerens energibalance (spec §3.3, DEL 3).

Læser den (HACS-)installerede Solcast Solar-integrations time-prognose og
omsætter den til ``{tid: kW}`` (P50), som optimizeren ganger med den
vejr-kalibrerede usikkerhedsfaktor (model_calibration.solar_factors). Findes
Solcast ikke, returneres en tom prognose, og optimeringen kører videre på ren
prisarbitrage (solar=0) — TEO må aldrig stoppe fordi en valgfri kilde mangler.

Solcast-integrationen eksponerer prognosen som attributten ``detailedHourly``
(eller ``detailedForecast`` i 30-min opløsning) på sine forecast-sensorer, en
liste af ``{"period_start": <ISO/dt>, "pv_estimate": <kWh>}``. pv_estimate i kWh
pr. time ≈ gennemsnitlig kW i timen, så vi kan bruge den direkte.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

_ATTR_CANDIDATES = ("detailedHourly", "detailedForecast")


def _to_utc_hour(value: Any) -> Optional[datetime]:
    """Normalisér et period_start (ISO-streng eller datetime) til hel UTC-time."""
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    elif isinstance(value, datetime):
        dt = value
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


def parse_hourly(detailed: list[dict[str, Any]]) -> dict[datetime, float]:
    """Omsæt en detailedHourly/Forecast-liste til ``{UTC-time: kW}`` (sum pr. time)."""
    buckets: dict[datetime, float] = {}
    for row in detailed or []:
        if not isinstance(row, dict):
            continue
        hour = _to_utc_hour(row.get("period_start"))
        est = row.get("pv_estimate")
        if hour is None or est is None:
            continue
        try:
            buckets[hour] = round(buckets.get(hour, 0.0) + float(est), 4)
        except (ValueError, TypeError):
            continue
    return buckets


def _find_detailed(hass) -> Optional[list[dict[str, Any]]]:
    """Find Solcast-forecast-sensorens detailedHourly-attribut (sprog-/navne-robust)."""
    # Foretræk entiteter fra solcast_solar-config entry; ellers match på id.
    try:
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(hass)
        solcast_entries = {ce.entry_id for ce in
                           hass.config_entries.async_entries("solcast_solar")}
        candidate_ids = [e.entity_id for e in reg.entities.values()
                         if e.config_entry_id in solcast_entries
                         and e.entity_id.startswith("sensor.")]
    except Exception:  # noqa: BLE001
        candidate_ids = []
    if not candidate_ids:
        candidate_ids = [s.entity_id for s in hass.states.async_all("sensor")
                         if "solcast" in s.entity_id and "forecast" in s.entity_id]

    for entity_id in candidate_ids:
        st = hass.states.get(entity_id)
        if st is None:
            continue
        for attr in _ATTR_CANDIDATES:
            detailed = st.attributes.get(attr)
            if isinstance(detailed, list) and detailed:
                return detailed
    return None


def fetch(hass, times: list[datetime]) -> dict[datetime, float]:
    """Byg ``{tid: kW}`` (P50) for optimeringshorisonten. Tom hvis ingen Solcast."""
    detailed = _find_detailed(hass)
    if not detailed:
        return {}
    hourly = parse_hourly(detailed)
    if not hourly:
        return {}
    # Justér Solcast-tidsstemplerne til optimizerens nøgler (samme UTC-time).
    out: dict[datetime, float] = {}
    for t in times:
        key = (t.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
               if getattr(t, "tzinfo", None) else t.replace(minute=0, second=0, microsecond=0))
        if key in hourly:
            out[t] = hourly[key]
    return out

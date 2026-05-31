"""Vejrdata fra Open-Meteo — ingen API-nøgle (spec DEL 1 / DEL 8).

Henter aktuelt vejr + den time-opløste stråling/UV/sigtbarhed som
dataindsamlingen har brug for. Koordinaterne kommer fra Home Assistants egen
hjemme-lokation (``hass.config``), ikke fra ``teo_config.yaml`` — wizardens
config indeholder ingen lat/lon, og HA's hjemmeposition er den autoritative
kilde resten af HA også bruger.

Designhensyn:
* Asynkront kald via HA's delte aiohttp-session.
* Resultatet caches i ``WEATHER_CACHE_TTL_MINUTES`` — vejret ændrer sig
  langsommere end 5-minutters-kadencen, så vi sparer kald til Open-Meteo.
* Enhver fejl (timeout, manglende felt) → et dict med ``None``-værdier, så en
  indsamling aldrig fejler pga. vejret (princip #2: aldrig blokér optimering).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from .const import (
    OPEN_METEO_URL,
    PRECIP_NONE,
    PRECIP_RAIN,
    PRECIP_SLEET,
    PRECIP_SNOW,
    WEATHER_CACHE_TTL_MINUTES,
    WEATHER_FOG,
    WEATHER_OVERCAST,
    WEATHER_PARTLY_CLOUDY,
    WEATHER_RAIN,
    WEATHER_SNOW,
    WEATHER_SUNNY,
    WEATHER_TIMEOUT_SEC,
)

_LOGGER = logging.getLogger(__name__)

# Felter der hentes fra Open-Meteos "current"-blok (ét opslag pr. kald).
_CURRENT_VARS = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)
# Felter der kun findes time-opløst — vi vælger den aktuelle time.
_HOURLY_VARS = (
    "shortwave_radiation",   # global horizontal irradiance (W/m²)
    "diffuse_radiation",
    "uv_index",
    "visibility",            # meter
)

# Kolonnenavne i measurements som dette modul fylder ud.
_FIELDS: tuple[str, ...] = (
    "temp_outdoor_c",
    "temp_feels_like_c",
    "cloud_cover_pct",
    "precipitation_mm_h",
    "precipitation_type",
    "wind_speed_ms",
    "wind_direction_deg",
    "wind_gusts_ms",
    "solar_irradiance_wm2",
    "diffuse_irradiance_wm2",
    "uv_index",
    "visibility_km",
    "humidity_pct",
    "pressure_hpa",
    "weather_category",
)


def _empty() -> dict[str, Any]:
    return {field: None for field in _FIELDS}


def categorise(weather_code: Optional[int], cloud_cover: Optional[float]) -> Optional[str]:
    """Oversæt WMO weather_code (+ skydække som backup) til en vejrkategori."""
    if weather_code is None:
        if cloud_cover is None:
            return None
        # Backup når koden mangler: brug skydække-procenten.
        if cloud_cover < 20:
            return WEATHER_SUNNY
        if cloud_cover < 60:
            return WEATHER_PARTLY_CLOUDY
        return WEATHER_OVERCAST
    code = int(weather_code)
    if code == 0:
        return WEATHER_SUNNY
    if code in (1, 2):
        return WEATHER_PARTLY_CLOUDY
    if code == 3:
        return WEATHER_OVERCAST
    if code in (45, 48):
        return WEATHER_FOG
    if code in (71, 72, 73, 74, 75, 76, 77, 85, 86):
        return WEATHER_SNOW
    # 51-67 (drizzle/rain), 80-82 (byger), 95-99 (torden) → regn.
    return WEATHER_RAIN


def precipitation_type(weather_code: Optional[int]) -> str:
    """Udled nedbørstype af WMO-koden."""
    if weather_code is None:
        return PRECIP_NONE
    code = int(weather_code)
    if code in (71, 72, 73, 74, 75, 76, 77, 85, 86):
        return PRECIP_SNOW
    if code in (56, 57, 66, 67):       # underafkølet/regn-sne blanding
        return PRECIP_SLEET
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99):
        return PRECIP_RAIN
    return PRECIP_NONE


class WeatherFetcher:
    """Henter og cacher Open-Meteo-data for én lokation."""

    def __init__(self) -> None:
        self._cache: Optional[dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None

    def _cache_valid(self, now: datetime) -> bool:
        return (
            self._cache is not None
            and self._cache_time is not None
            and now - self._cache_time < timedelta(minutes=WEATHER_CACHE_TTL_MINUTES)
        )

    async def fetch(self, hass, latitude: float, longitude: float,
                    now: Optional[datetime] = None) -> dict[str, Any]:
        """Returnér vejrfelter til measurements (cachet i TTL-vinduet)."""
        now = now or datetime.now()
        if self._cache_valid(now):
            return self._cache

        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(hass)
            params = {
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
                "current": ",".join(_CURRENT_VARS),
                "hourly": ",".join(_HOURLY_VARS),
                "wind_speed_unit": "ms",
                "timezone": "auto",
                "forecast_days": "1",
            }
            async with asyncio.timeout(WEATHER_TIMEOUT_SEC):
                resp = await session.get(OPEN_METEO_URL, params=params)
                resp.raise_for_status()
                payload = await resp.json()
        except Exception as err:  # noqa: BLE001 — netværk/timeout/parse
            _LOGGER.warning("Open-Meteo-kald fejlede (%s) — vejr udeladt", err)
            return _empty()

        result = self._parse(payload)
        self._cache = result
        self._cache_time = now
        return result

    @staticmethod
    def _pick_current_hour(hourly: dict[str, Any], current_time: Optional[str]) -> int:
        """Find indeks i hourly-arrays der matcher den aktuelle time."""
        times = hourly.get("time") or []
        if current_time and times:
            prefix = current_time[:13]  # YYYY-MM-DDTHH
            for idx, t in enumerate(times):
                if isinstance(t, str) and t.startswith(prefix):
                    return idx
        return 0

    def _parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = payload.get("current") or {}
        hourly = payload.get("hourly") or {}
        idx = self._pick_current_hour(hourly, current.get("time"))

        def hourly_val(name: str) -> Optional[float]:
            arr = hourly.get(name) or []
            if 0 <= idx < len(arr):
                return arr[idx]
            return None

        code = current.get("weather_code")
        cloud = current.get("cloud_cover")
        visibility_m = hourly_val("visibility")

        return {
            "temp_outdoor_c": current.get("temperature_2m"),
            "temp_feels_like_c": current.get("apparent_temperature"),
            "cloud_cover_pct": cloud,
            "precipitation_mm_h": current.get("precipitation"),
            "precipitation_type": precipitation_type(code),
            "wind_speed_ms": current.get("wind_speed_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "wind_gusts_ms": current.get("wind_gusts_10m"),
            "solar_irradiance_wm2": hourly_val("shortwave_radiation"),
            "diffuse_irradiance_wm2": hourly_val("diffuse_radiation"),
            "uv_index": hourly_val("uv_index"),
            "visibility_km": round(visibility_m / 1000.0, 2) if visibility_m is not None else None,
            "humidity_pct": current.get("relative_humidity_2m"),
            "pressure_hpa": current.get("surface_pressure"),
            "weather_category": categorise(code, cloud),
        }

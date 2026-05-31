"""Sol-geometri — beregnet lokalt uden netkald (spec DEL 1 / DEL 8).

Leverer solens position (azimut/elevation), dagslysvinduet og sæsonindikatorer
til hver måling i Data Commons. Beregningen er ren og deterministisk: givet
koordinater + tidspunkt fås altid samme resultat, så den kan køres synkront i
indsamlingscyklussen uden at blokere noget.

Vi bruger ``astral`` frem for ``pysolar`` (som SAMLET_V2 DEL 8 foreslår), fordi
astral allerede er en afhængighed af Home Assistant-kernen (sun-integrationen
bygger på den). Det sparer en ekstra wheel-bygning på Raspberry Pi'ens ARM-CPU
og giver solopgang/-nedgang, elevation og azimut direkte.

Alle felter svarer 1:1 til kolonnerne i ``measurements`` (afsnittet
"Sol-geometri" i DEL 1). Ved enhver fejl returneres et dict med ``None``-værdier
i stedet for at kaste — dataindsamling må aldrig vælte driften (princip #2).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from .const import SUMMER_SOLSTICE_DAY, SUMMER_SOLSTICE_MONTH

_LOGGER = logging.getLogger(__name__)

# Kolonnenavne så et "tomt" resultat har præcis samme form som et fuldt.
_FIELDS: tuple[str, ...] = (
    "sun_azimuth_deg",
    "sun_elevation_deg",
    "is_daylight",
    "minutes_since_sunrise",
    "minutes_to_sunset",
    "day_length_minutes",
    "days_since_summer_solstice",
    "solar_noon_elevation_deg",
)


def _empty() -> dict[str, Any]:
    return {field: None for field in _FIELDS}


def _days_since_summer_solstice(when: date) -> int:
    """Antal dage siden seneste sommersolhverv (~21. juni).

    Stærk sæsonindikator: 0 omkring længste dag, ~182 omkring korteste.
    Hvis vi endnu ikke har passeret solhvervet i år, regnes fra sidste år.
    """
    solstice = date(when.year, SUMMER_SOLSTICE_MONTH, SUMMER_SOLSTICE_DAY)
    if when < solstice:
        solstice = date(when.year - 1, SUMMER_SOLSTICE_MONTH, SUMMER_SOLSTICE_DAY)
    return (when - solstice).days


def compute(
    latitude: float,
    longitude: float,
    elevation_m: float,
    when: datetime,
) -> dict[str, Any]:
    """Beregn sol-geometri for en given (tidszone-bevidst) ``when``.

    ``when`` SKAL være timezone-aware — kalderen sender HA's lokale tid. Bruges
    en naiv datetime, antager astral UTC og azimut/elevation bliver forkerte.
    """
    try:
        from astral import Observer
        from astral.sun import azimuth, elevation, sun
    except Exception as err:  # noqa: BLE001 — astral burde altid være til stede
        _LOGGER.warning("astral utilgængelig — springer sol-geometri over: %s", err)
        return _empty()

    try:
        observer = Observer(latitude=latitude, longitude=longitude,
                            elevation=elevation_m)
        tzinfo = when.tzinfo

        sun_az = round(azimuth(observer, when), 2)
        sun_el = round(elevation(observer, when), 2)

        events = sun(observer, date=when.date(), tzinfo=tzinfo)
        sunrise: datetime = events["sunrise"]
        sunset: datetime = events["sunset"]
        noon: datetime = events["noon"]

        is_daylight = sunrise <= when <= sunset
        mins_since_sunrise = round((when - sunrise).total_seconds() / 60.0)
        mins_to_sunset = round((sunset - when).total_seconds() / 60.0)
        day_length = round((sunset - sunrise).total_seconds() / 60.0)
        noon_elevation = round(elevation(observer, noon), 2)

        return {
            "sun_azimuth_deg": sun_az,
            "sun_elevation_deg": sun_el,
            "is_daylight": is_daylight,
            "minutes_since_sunrise": mins_since_sunrise,
            "minutes_to_sunset": mins_to_sunset,
            "day_length_minutes": day_length,
            "days_since_summer_solstice": _days_since_summer_solstice(when.date()),
            "solar_noon_elevation_deg": noon_elevation,
        }
    except Exception as err:  # noqa: BLE001 — fx polare døgn uden solop-/nedgang
        _LOGGER.debug("Kunne ikke beregne fuld sol-geometri (%s) — delvist tom", err)
        result = _empty()
        # Sæsonindikatoren afhænger ikke af astral og kan altid udfyldes.
        result["days_since_summer_solstice"] = _days_since_summer_solstice(when.date())
        return result

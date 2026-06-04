"""Helligdage og skoleferier (Danmark) — spec DEL 1 / DEL 2.

Leverer de fire kalenderkolonner i ``measurements`` som ren, lokal beregning:
``is_public_holiday_dk``, ``is_school_holiday_dk``, ``days_until_christmas`` og
``days_until_easter``. Disse er stærke kontekstsignaler for forbrugsmønstre
(juleferie, vinterferie, sommerferie) som familielæringen (DEL 2) bygger på.

Officielle helligdage kommer fra ``holidays``-biblioteket. Skoleferier er
kommune-afhængige i DK; vi bruger det gængse nationale mønster fra const.py og
gør det dermed kalibrerbart ét sted (designprincip #8: ingen magiske tal).
Påskedag beregnes med computus (Meeus/Jones/Butcher) uden netkald.

Alle funktioner er rene og defensive: fejler en kilde, returneres ``None`` for
det felt frem for at vælte en indsamling (princip #2).

NOTE: holidays-biblioteket bruger lazy imports internt. is_public_holiday() skal
derfor kaldes via hass.async_add_executor_job() fra async-kontekst.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from .const import (
    CHRISTMAS_DAY,
    CHRISTMAS_MONTH,
    EASTER_HOLIDAY_END_OFFSET,
    EASTER_HOLIDAY_START_OFFSET,
    HOLIDAYS_COUNTRY_DK,
    SCHOOL_AUTUMN_WEEK,
    SCHOOL_CHRISTMAS_END,
    SCHOOL_CHRISTMAS_START,
    SCHOOL_SUMMER_END,
    SCHOOL_SUMMER_START,
    SCHOOL_WINTER_WEEK,
)

_LOGGER = logging.getLogger(__name__)

# Cache per år — undgår gentagne imports
_HOLIDAYS_CACHE: dict[int, object] = {}


def _get_dk_holidays(year: int) -> object:
    """Hent dansk helligdagskalender for et år — med cache.
    
    SKAL kaldes via executor fra async-kontekst da holidays-biblioteket
    bruger lazy imports internt (blocking i Python 3.14 event loop).
    """
    if year not in _HOLIDAYS_CACHE:
        import holidays
        _HOLIDAYS_CACHE[year] = holidays.country_holidays(
            HOLIDAYS_COUNTRY_DK, years=year)
    return _HOLIDAYS_CACHE[year]


def easter_sunday(year: int) -> date:
    """Påskedag (gregoriansk) via computus — ingen afhængigheder."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def is_public_holiday(d: date) -> Optional[bool]:
    """True hvis ``d`` er en officiel dansk helligdag (None hvis lib mangler).
    
    SKAL kaldes via hass.async_add_executor_job() fra async-kontekst.
    """
    try:
        dk = _get_dk_holidays(d.year)
        return d in dk
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("holidays-opslag fejlede: %s", err)
        return None


def _in_md_range(d: date, start_md: tuple[int, int], end_md: tuple[int, int]) -> bool:
    """Er ``d`` inden for et (måned, dag)-spænd — håndterer årsskifte."""
    start = date(d.year, *start_md)
    end = date(d.year, *end_md)
    if start <= end:
        return start <= d <= end
    return d >= start or d <= end


def is_school_holiday(d: date) -> bool:
    """True hvis ``d`` falder i en typisk dansk skoleferie (national approks.)."""
    week = d.isocalendar()[1]
    if week in (SCHOOL_WINTER_WEEK, SCHOOL_AUTUMN_WEEK):
        return True
    if _in_md_range(d, SCHOOL_SUMMER_START, SCHOOL_SUMMER_END):
        return True
    if _in_md_range(d, SCHOOL_CHRISTMAS_START, SCHOOL_CHRISTMAS_END):
        return True
    easter = easter_sunday(d.year)
    start = easter + timedelta(days=EASTER_HOLIDAY_START_OFFSET)
    end = easter + timedelta(days=EASTER_HOLIDAY_END_OFFSET)
    return start <= d <= end


def days_until_christmas(d: date) -> int:
    """Dage til næste juleaften (24/12). 0 på selve dagen."""
    target = date(d.year, CHRISTMAS_MONTH, CHRISTMAS_DAY)
    if d > target:
        target = date(d.year + 1, CHRISTMAS_MONTH, CHRISTMAS_DAY)
    return (target - d).days


def days_until_easter(d: date) -> int:
    """Dage til næste påskedag. 0 på selve dagen."""
    target = easter_sunday(d.year)
    if d > target:
        target = easter_sunday(d.year + 1)
    return (target - d).days


def context_sync(d: date) -> dict[str, Any]:
    """De fire kalenderfelter til measurements-rækken (0/1 for bools).
    
    SKAL kaldes via hass.async_add_executor_job() fra async-kontekst.
    """
    public = is_public_holiday(d)
    return {
        "is_public_holiday_dk": None if public is None else (1 if public else 0),
        "is_school_holiday_dk": 1 if is_school_holiday(d) else 0,
        "days_until_christmas": days_until_christmas(d),
        "days_until_easter": days_until_easter(d),
    }


def context(d: date) -> dict[str, Any]:
    """Alias for context_sync — bevar bagudkompatibilitet.
    
    SKAL kaldes via hass.async_add_executor_job() fra async-kontekst.
    """
    return context_sync(d)

"""Daglig afvigelses-analyse (kl. 06:00).

Kører hver morgen for at identificere:
  1. Hvor ofte TEO's plan blev fulgt
  2. Uforklarede SOC-ændringer
  3. Enphase-cloud overskrivninger

Genererer dansk klartekst-rapport og sender som HA persistent notification.

Køres via automation eller service-kald fra __init__.py.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from .decision_tracker import DecisionTracker

_LOGGER = logging.getLogger(__name__)


async def run_daily_analysis(hass: HomeAssistant) -> dict[str, Any]:
    """Kør daglig analyse og send rapport til HA.

    Returnerer:
      {
        "success": bool,
        "report_lines": list[str],
        "total_measurements": int,
        "plan_matches": int,
        "plan_mismatches": int,
      }
    """
    try:
        tracker = await hass.async_add_executor_job(DecisionTracker)
        analysis = await hass.async_add_executor_job(tracker.analyze_last_24h)

        # Send rapport som persistent notification
        report_text = "\n".join(analysis["report_lines"])

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "TEO Daglig Afvigelses-analyse",
                "message": report_text,
                "notification_id": "teo_daily_analysis",
            },
        )

        _LOGGER.info(
            "Daglig analyse kørt: %d målinger, %d/%d planen fulgt",
            analysis["total_measurements"],
            analysis["plan_matches"],
            analysis["total_measurements"],
        )

        return {
            "success": True,
            "report_lines": analysis["report_lines"],
            "total_measurements": analysis["total_measurements"],
            "plan_matches": analysis["plan_matches"],
            "plan_mismatches": analysis["plan_mismatches"],
        }

    except Exception as err:
        _LOGGER.error("Daglig analyse fejlede: %s", err, exc_info=True)
        return {
            "success": False,
            "error": str(err),
        }

"""Analyse Decisions — daglig afvigelses-analyse service.

Logsystem DEL 2:
- Service: teo.decision_analysis
- Sammenligner planlagt vs. faktisk seneste 24 timer
- Genererer dansk rapport → persistent notification

Kaldes automatisk kl. 06:00 via automation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DATA_DB_FILE
from .decision_tracker import DecisionTracker

_LOGGER = logging.getLogger(__name__)

# Service schema (ingen parametre)
SERVICE_SCHEMA = vol.Schema({})


async def async_setup_decision_analysis_service(hass: HomeAssistant) -> None:
    """Registrér teo.decision_analysis service."""

    async def handle_decision_analysis(call: ServiceCall) -> None:
        """Kør daglig beslutningsanalyse og send rapport."""
        try:
            # Lazy-load decision_tracker
            db_path = Path(hass.config.config_dir) / DATA_DB_FILE
            tracker = DecisionTracker(db_path)

            # Analysér seneste 24 timer
            result = await tracker.analyze_last_24h(hass)

            # Send rapport som persistent notification
            report = result["report"]
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "📊 TEO Beslutningsanalyse",
                    "message": report,
                    "notification_id": "teo_decision_analysis",
                },
                blocking=True,
            )

            _LOGGER.info(
                "Beslutningsanalyse afsluttet: %d beslutninger, %.1f%% match, %d afvigelser",
                result["total_decisions"],
                result["plan_match_rate"],
                result["deviations"],
            )

        except Exception as err:
            _LOGGER.exception("Fejl i beslutningsanalyse: %s", err)
            # Send fejlnotifikation til bruger
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "⚠️ TEO Beslutningsanalyse Fejl",
                    "message": f"Kunne ikke køre analyse: {err}",
                    "notification_id": "teo_decision_analysis_error",
                },
                blocking=False,
            )

    hass.services.async_register(
        "teo",
        "decision_analysis",
        handle_decision_analysis,
        schema=SERVICE_SCHEMA,
    )

    _LOGGER.info("TEO decision_analysis service registreret")

"""Analyse Decisions — daglig afvigelses-analyse service.

Logsystem DEL 2:
- Service: teo.decision_analysis
- Sammenligner planlagt vs. faktisk seneste 24 timer
- Genererer dansk rapport → /config/teo_reports/YYYY-MM-DD.txt + system log

Kaldes automatisk kl. 06:00 via automation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime

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

            # Gem rapport til dateret fil i teo_reports/
            report = result["report"]
            reports_dir = Path(hass.config.config_dir) / "teo_reports"
            date_str = datetime.now().strftime("%Y-%m-%d")
            report_file = reports_dir / f"{date_str}.txt"

            def _write_report():
                # Opret mappe hvis den ikke findes
                reports_dir.mkdir(exist_ok=True)
                with open(report_file, "w", encoding="utf-8") as f:
                    f.write(f"Genereret: {datetime.now().isoformat()}\n\n")
                    f.write(report)

            await hass.async_add_executor_job(_write_report)

            # Log rapport på WARNING-niveau så den er synlig
            _LOGGER.warning(
                "TEO Beslutningsanalyse afsluttet:\n%s",
                report
            )

            _LOGGER.info(
                "Rapport gemt til %s (%d beslutninger, %.1f%% match, %d afvigelser)",
                report_file,
                result["total_decisions"],
                result["plan_match_rate"],
                result["deviations"],
            )

        except Exception as err:
            _LOGGER.exception("Fejl i beslutningsanalyse: %s", err)

    hass.services.async_register(
        "teo",
        "decision_analysis",
        handle_decision_analysis,
        schema=SERVICE_SCHEMA,
    )

    _LOGGER.info("TEO decision_analysis service registreret")

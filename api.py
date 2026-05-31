"""TEO REST API — endpoints til dashboard-widgets.

Logsystem DEL 3:
- REST endpoint: /api/teo/soc_timeline?hours=24
- Data til Chart.js visualisering

Registreres i __init__.py via lazy loading.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DATA_DB_FILE
from .decision_tracker import DecisionTracker

_LOGGER = logging.getLogger(__name__)


class TEOSocTimelineView(HomeAssistantView):
    """API view for SOC timeline data."""

    url = "/api/teo/soc_timeline"
    name = "api:teo:soc_timeline"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return SOC timeline data as JSON."""
        hass: HomeAssistant = request.app["hass"]

        # Parse query parameter
        hours_param = request.query.get("hours", "24")
        try:
            hours = int(hours_param)
            hours = max(1, min(hours, 168))  # Clamp 1-168 (1 uge)
        except ValueError:
            hours = 24

        try:
            # Lazy-load decision_tracker
            db_path = Path(hass.config.config_dir) / DATA_DB_FILE
            tracker = DecisionTracker(db_path)

            # Hent timeline data
            timeline = await tracker.get_soc_timeline(hass, hours=hours)

            return self.json({
                "success": True,
                "hours": hours,
                "data": timeline,
            })

        except Exception as err:
            _LOGGER.exception("Fejl i SOC timeline API: %s", err)
            return self.json(
                {"success": False, "error": str(err)},
                status_code=500,
            )


async def async_setup_api(hass: HomeAssistant) -> None:
    """Registrér TEO REST API endpoints."""
    hass.http.register_view(TEOSocTimelineView())
    _LOGGER.info("TEO REST API endpoints registreret")

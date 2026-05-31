"""TEO REST API endpoints.

DEL 3: API endpoint til SOC-tracking dashboard-widget.

Registreres som Home Assistant view så frontend kan hente data via:
  GET /api/teo/soc_timeline?hours=24
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .decision_tracker import DecisionTracker

_LOGGER = logging.getLogger(__name__)


class TeoSocTimelineView(HomeAssistantView):
    """REST API endpoint for SOC timeline data."""

    url = "/api/teo/soc_timeline"
    name = "api:teo:soc_timeline"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Hent SOC timeline data."""
        hass: HomeAssistant = request.app["hass"]

        # Parse query params
        hours = int(request.query.get("hours", "24"))

        try:
            tracker = await hass.async_add_executor_job(DecisionTracker)
            data = await hass.async_add_executor_job(
                tracker.get_soc_timeline, hours
            )

            return self.json(data)

        except Exception as err:
            _LOGGER.error("SOC timeline API fejlede: %s", err, exc_info=True)
            return self.json(
                {"error": str(err)},
                status_code=500,
            )


def register_api_views(hass: HomeAssistant) -> None:
    """Registrer TEO API endpoints."""
    hass.http.register_view(TeoSocTimelineView())
    _LOGGER.info("TEO API endpoints registreret")

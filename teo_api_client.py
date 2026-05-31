"""Klient til TEO API (api.teo.energy) — spec §6.

Bruges UDELUKKENDE i Self-Hosted-tilstand. I Local-tilstand instantieres
klienten aldrig (coordinatoren tjekker tilstand før kald) — designprincip #1.

Sikkerhed (spec §11): kun HTTPS, TLS 1.2+ (1.3 foretrukket). Alle UUID'er
valideres før afsendelse. Ingen personoplysninger sendes nogensinde
(designprincip #5) — kalderen er ansvarlig for kun at videregive anonyme felter.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any, Optional

from .const import (
    ALGORITHM_VERSION,
    API_PATH_CONFIG,
    API_PATH_CREATE_ACCOUNT,
    API_PATH_DATA,
    API_PATH_FEEDBACK,
    API_PATH_FEEDBACK_STATUS,
    API_PATH_REGISTER,
    API_PATH_UPDATES,
    API_TIMEOUT_SEC,
    TEO_API_BASE_URL,
    TEO_VERSION,
)
from .installation_id import is_valid_uuid

_LOGGER = logging.getLogger(__name__)


class TEOAPIError(Exception):
    """Generel fejl ved kommunikation med TEO API."""


class TEOAPIClient:
    """Tynd async HTTPS-klient. Opretter egen session hvis ingen gives."""

    def __init__(self, base_url: str = TEO_API_BASE_URL,
                 session: Any = None) -> None:
        if not base_url.startswith("https://"):
            raise TEOAPIError("TEO API kræver HTTPS")
        self._base = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None

    # --- session-håndtering -------------------------------------------
    async def _get_session(self):
        if self._session is None:
            import aiohttp
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            connector = aiohttp.TCPConnector(ssl=ctx)
            timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SEC)
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _request(self, method: str, path: str,
                       **kwargs: Any) -> Optional[dict[str, Any]]:
        session = await self._get_session()
        url = f"{self._base}{path}"
        try:
            async with session.request(method, url, **kwargs) as resp:
                if resp.status == 404:
                    return None
                if resp.status >= 400:
                    raise TEOAPIError(f"{method} {path} → HTTP {resp.status}")
                return await resp.json()
        except TEOAPIError:
            raise
        except Exception as err:  # noqa: BLE001
            raise TEOAPIError(f"{method} {path}: {err}") from err

    # --- endpoints -----------------------------------------------------
    async def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /v1/register — registrér anonym konfiguration under UUID."""
        self._require_uuid(payload.get("id"))
        payload.setdefault("teo_version", TEO_VERSION)
        return await self._request("POST", API_PATH_REGISTER, json=payload) or {}

    async def get_config(self, installation_uuid: str) -> Optional[dict[str, Any]]:
        """GET /v1/config?id={uuid} — hent gemt konfiguration (geninstallation)."""
        self._require_uuid(installation_uuid)
        return await self._request("GET", API_PATH_CONFIG,
                                   params={"id": installation_uuid})

    async def check_updates(self, installation_uuid: str,
                            current_version: str = ALGORITHM_VERSION
                            ) -> Optional[dict[str, Any]]:
        """GET /v1/updates — tjek for godkendte algoritmeopdateringer."""
        self._require_uuid(installation_uuid)
        return await self._request(
            "GET", API_PATH_UPDATES,
            params={"id": installation_uuid, "current_version": current_version},
        )

    async def send_data(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        """POST /v1/data — anonym månedlig opsummering (kun ved opt-in)."""
        self._require_uuid(payload.get("id"))
        return await self._request("POST", API_PATH_DATA, json=payload)

    async def send_feedback(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        """POST /v1/feedback — brugerrapport om en beslutning."""
        self._require_uuid(payload.get("id"))
        return await self._request("POST", API_PATH_FEEDBACK, json=payload)

    async def get_feedback_status(self, report_id: str) -> Optional[dict[str, Any]]:
        """GET /v1/feedback/status — følg op på en indsendt rapport."""
        return await self._request("GET", API_PATH_FEEDBACK_STATUS,
                                   params={"report_id": report_id})

    async def create_account(self, email: str,
                             installation_uuid: str) -> Optional[dict[str, Any]]:
        """POST /v1/create-account — opret gratis Self-Hosted-konto (wizard trin 3)."""
        self._require_uuid(installation_uuid)
        return await self._request(
            "POST", API_PATH_CREATE_ACCOUNT,
            json={"email": email, "installation_id": installation_uuid},
        )

    @staticmethod
    def _require_uuid(value: Any) -> None:
        if not is_valid_uuid(value or ""):
            raise TEOAPIError("Ugyldigt eller manglende installations-UUID")

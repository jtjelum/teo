"""Easee EV-lader integration til TEO.

Kommunikerer med Easee via cloud API. Understøtter on/off-styring og
strømbegrænsning. Finder ladere via netværksscan (Easee sender mDNS).

Protokol: Easee Cloud REST API
Auto-discovery: Netværksscan port 80 + API-login
"""

from __future__ import annotations

import logging
from typing import Optional

from ..base.ev_charger_base import EVChargerBase, EVChargerStatus, NotSupportedError

_LOGGER = logging.getLogger(__name__)

_EASEE_API = "https://api.easee.com/api"


class EaseeCharger(EVChargerBase):
    """TEO-integration til Easee Home / Charge / Base.

    Args:
        charger_id: Easee charger ID (fx "EH123456").
        username: Easee-konto email.
        password: Easee-konto adgangskode.
        circuit_max_current_a: Kredsløbsgrænse i ampere (default 20A).
    """

    def __init__(self, charger_id: str, username: str, password: str,
                 circuit_max_current_a: float = 20.0) -> None:
        self.charger_id = charger_id
        self.username = username
        self.password = password
        self.circuit_max_current_a = circuit_max_current_a
        self._token: Optional[str] = None

    async def discover(self) -> list[str]:
        """Find Easee-ladere via API-login.

        Returnerer liste af charger IDs (ikke IP-adresser — Easee er cloud-baseret).
        """
        try:
            token = await self._get_token()
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{_EASEE_API}/chargers",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return [c.get("id", "") for c in data if c.get("id")]
        except Exception as err:
            _LOGGER.warning("Easee discovery fejlede: %s", err)
            return []

    async def get_status(self) -> EVChargerStatus:
        """Hent aktuel laderstatus.

        Raises:
            ConnectionError: Hvis Easee API ikke kan nås.
        """
        try:
            token = await self._get_token()
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{_EASEE_API}/chargers/{self.charger_id}/state",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        raise ConnectionError(f"Easee API returnerede HTTP {resp.status}")
                    data = await resp.json()

            return EVChargerStatus(
                is_charging=data.get("chargerOpMode") == 3,
                charge_power_kw=float(data.get("totalPower", 0.0)),
                cable_connected=data.get("isOnline", False),
                is_online=data.get("isOnline", False),
                max_current_a=float(data.get("dynamicChargerCurrent", 0.0)),
                session_energy_kwh=float(data.get("sessionEnergy", 0.0)),
                raw=data
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(f"Kunne ikke hente Easee status: {err}") from err

    async def set_charging_enabled(self, enabled: bool) -> bool:
        """Start eller stop ladning.

        Args:
            enabled: True = start, False = stop/pause.
        """
        try:
            token = await self._get_token()
            import aiohttp
            action = "start_charging" if enabled else "pause_charging"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_EASEE_API}/chargers/{self.charger_id}/commands/{action}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status < 300
        except Exception as err:
            raise ConnectionError(f"Kunne ikke styre Easee ladning: {err}") from err

    async def set_current_limit(self, current_a: float) -> bool:
        """Sæt strømstyrke — respekterer kredsløbsgrænsen.

        Args:
            current_a: Ønsket strømstyrke. Begrænses til circuit_max_current_a.
        """
        clamped = min(current_a, self.circuit_max_current_a)
        try:
            token = await self._get_token()
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_EASEE_API}/chargers/{self.charger_id}/settings",
                    json={"dynamicChargerCurrent": clamped},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status < 300
        except Exception as err:
            raise ConnectionError(f"Kunne ikke sætte Easee strømstyrke: {err}") from err

    async def _get_token(self) -> str:
        """Hent Easee OAuth2 token (caches)."""
        if self._token:
            return self._token
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_EASEE_API}/accounts/login",
                    json={"userName": self.username, "password": self.password},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    self._token = data.get("accessToken", "")
                    return self._token
        except Exception as err:
            raise ConnectionError(f"Kunne ikke logge ind på Easee: {err}") from err

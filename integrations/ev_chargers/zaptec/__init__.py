"""Zaptec EV-lader integration til TEO.

Kommunikerer med Zaptec via cloud API.
Understøtter Zaptec Go og Zaptec Pro.

Protokol: Zaptec Cloud REST API
"""

from __future__ import annotations
import logging
from typing import Optional
from ..base.ev_charger_base import EVChargerBase, EVChargerStatus

_LOGGER = logging.getLogger(__name__)
_ZAPTEC_API = "https://api.zaptec.com"


class ZaptecCharger(EVChargerBase):
    """TEO-integration til Zaptec Go / Pro.

    Args:
        charger_id: Zaptec charger UUID. Find i Zaptec-portalen.
        username: Zaptec-konto email.
        password: Zaptec-konto adgangskode.
    """

    def __init__(self, charger_id: str, username: str, password: str) -> None:
        self.charger_id = charger_id
        self.username = username
        self.password = password
        self._token: Optional[str] = None

    async def discover(self) -> list[str]:
        """Find Zaptec-ladere via API-login."""
        try:
            token = await self._get_token()
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{_ZAPTEC_API}/api/chargers",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return [c.get("Id", "") for c in data.get("Data", []) if c.get("Id")]
        except Exception as err:
            _LOGGER.warning("Zaptec discovery fejlede: %s", err)
            return []

    async def get_status(self) -> EVChargerStatus:
        """Hent aktuel Zaptec-laderstatus."""
        try:
            token = await self._get_token()
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{_ZAPTEC_API}/api/chargers/{self.charger_id}/state",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        raise ConnectionError(f"Zaptec HTTP {resp.status}")
                    states = await resp.json()

            state_map = {s["StateId"]: s.get("ValueAsString", "") for s in states}
            op_mode = int(state_map.get("710", "2"))

            return EVChargerStatus(
                is_charging=op_mode == 5,
                charge_power_kw=float(state_map.get("513", "0")) / 1000.0,
                cable_connected=op_mode in (3, 5, 6),
                is_online=True,
                session_energy_kwh=float(state_map.get("553", "0")) / 1000.0,
                raw=state_map
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(f"Fejl ved Zaptec: {err}") from err

    async def set_charging_enabled(self, enabled: bool) -> bool:
        """Start eller stop Zaptec-ladning."""
        try:
            token = await self._get_token()
            import aiohttp
            command = 506 if enabled else 507
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_ZAPTEC_API}/api/chargers/{self.charger_id}/sendCommand/{command}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status < 300
        except Exception as err:
            raise ConnectionError(f"Fejl ved Zaptec styring: {err}") from err

    async def set_current_limit(self, current_a: float) -> bool:
        """Sæt strømstyrke på Zaptec-lader."""
        try:
            token = await self._get_token()
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_ZAPTEC_API}/api/chargers/{self.charger_id}/settings",
                    json={"MaxChargeCurrent": current_a},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status < 300
        except Exception as err:
            raise ConnectionError(f"Fejl ved Zaptec strøm: {err}") from err

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_ZAPTEC_API}/oauth/token",
                    data={"grant_type": "password",
                          "username": self.username,
                          "password": self.password},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    self._token = data.get("access_token", "")
                    return self._token
        except Exception as err:
            raise ConnectionError(f"Zaptec login fejlede: {err}") from err

"""go-e Charger integration til TEO.

Kommunikerer lokalt via go-e REST API v2.
Ingen cloud-konto kræves — 100% lokal.

Protokol: Lokalt REST API (HTTP)
Auto-discovery: mDNS (go-eCharger-XXXXXX.local) + portscan port 80
"""

from __future__ import annotations

import logging
from typing import Optional

from ..base.ev_charger_base import EVChargerBase, EVChargerStatus

_LOGGER = logging.getLogger(__name__)

_GOE_API_PATH = "/api/status"
_GOE_SET_PATH = "/api/set"


class GoeCharger(EVChargerBase):
    """TEO-integration til go-e Charger Gemini / HOME.

    Kommunikerer direkte med laderen på det lokale netværk.
    Ingen cloud-konto eller internet kræves.

    Args:
        host: IP-adresse til go-e Charger
              (fx "192.168.1.50" eller "go-eCharger-123456.local").
    """

    def __init__(self, host: str) -> None:
        self.host = host

    async def discover(self) -> list[str]:
        """Find go-e Charger via mDNS og portscan."""
        import asyncio
        import socket
        found = []

        # mDNS — go-e bruger go-eCharger-XXXXXX.local
        # Vi kan ikke kende serienummeret, så vi scanner i stedet
        import ipaddress

        async def probe(ip_str: str) -> Optional[str]:
            try:
                fut = asyncio.open_connection(ip_str, 80)
                reader, writer = await asyncio.wait_for(fut, timeout=0.5)
                writer.close()
                await writer.wait_closed()
                # Verificer at det er en go-e ved at kalde /api/status
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://{ip_str}{_GOE_API_PATH}",
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # go-e API returnerer "car" nøgle
                            if "car" in data or "nrg" in data:
                                return ip_str
            except Exception:
                pass
            return None

        tasks = [probe(str(ip))
                 for ip in ipaddress.ip_network("192.168.1.0/24").hosts()]
        results = await asyncio.gather(*tasks)
        return [ip for ip in results if ip]

    async def get_status(self) -> EVChargerStatus:
        """Hent aktuel go-e status via lokal API.

        Raises:
            ConnectionError: Hvis laderen ikke kan nås.
        """
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.host}{_GOE_API_PATH}",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        raise ConnectionError(
                            f"go-e returnerede HTTP {resp.status}")
                    data = await resp.json()

            # go-e API v2 status felter
            # car: 1=Idle, 2=Charging, 3=WaitCar, 4=Complete, 5=Error
            car_state = int(data.get("car", 1))
            is_charging = car_state == 2
            cable_connected = car_state in (2, 3, 4)

            # nrg[11] = aktuel effekt i W (eller power felt)
            power_w = 0.0
            nrg = data.get("nrg", [])
            if len(nrg) > 11:
                power_w = float(nrg[11])
            elif "wh" in data:
                power_w = float(data.get("wh", 0))

            # amp = aktuel strømstyrke
            current_a = float(data.get("amp", 0))

            # wh = Wh i aktuel session
            session_wh = float(data.get("wh", 0))

            return EVChargerStatus(
                is_charging=is_charging,
                charge_power_kw=power_w / 1000.0,
                cable_connected=cable_connected,
                is_online=True,
                max_current_a=current_a,
                session_energy_kwh=session_wh / 1000.0,
                raw=data
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(
                f"Kunne ikke hente go-e status: {err}") from err

    async def set_charging_enabled(self, enabled: bool) -> bool:
        """Start eller stop go-e ladning via lokal API."""
        try:
            import aiohttp
            # go-e: alw=1 tillad altid ladning, alw=0 stop ladning
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.host}{_GOE_SET_PATH}",
                    params={"alw": "1" if enabled else "0"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return resp.status < 300
        except Exception as err:
            raise ConnectionError(
                f"Kunne ikke styre go-e ladning: {err}") from err

    async def set_current_limit(self, current_a: float) -> bool:
        """Sæt strømstyrke på go-e Charger (6-32A)."""
        clamped = max(6.0, min(32.0, current_a))
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.host}{_GOE_SET_PATH}",
                    params={"amp": str(int(clamped))},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return resp.status < 300
        except Exception as err:
            raise ConnectionError(
                f"Kunne ikke sætte go-e strømstyrke: {err}") from err

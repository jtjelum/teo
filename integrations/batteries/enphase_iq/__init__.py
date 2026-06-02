"""Enphase IQ Battery integration til TEO.

Kommunikerer med Enphase Envoy-S Metered via det lokale HTTP API.
Kræver DIY Enlighten Manager-konto for fuld batterikontrol (reserve +
charge_from_grid). Uden DIY-konto er kun aflæsning mulig.

Protokol: Local HTTP API (Envoy firmware D7+)
Auto-discovery: mDNS (envoy.local) + netværksscan på port 80
"""

from __future__ import annotations

import logging
from typing import Optional

from ..base.battery_base import BatteryBase, BatteryStatus, NotSupportedError

_LOGGER = logging.getLogger(__name__)

# Envoy API-endpoints
_ENDPOINT_INVENTORY = "/inventory.json"
_ENDPOINT_PRODUCTION = "/production.json"
_ENDPOINT_BATTERY = "/ivp/ensemble/power"
_ENDPOINT_SOC = "/ivp/ensemble/inventory"
_ENDPOINT_OPT_SCHEDULES = "/ivp/ss/gen_config"


class EnphaseIQBattery(BatteryBase):
    """TEO-integration til Enphase IQ Battery 3T / 5P.

    Kommunikerer direkte med Envoy-S Metered på det lokale netværk.
    Kræver DIY-konto på enlighten.enphaseenergy.com for set_reserve_percent()
    og set_charge_from_grid() — get_status() virker uden.

    Args:
        host: IP-adresse eller hostname til Envoy (fx "192.168.1.189" eller "envoy.local").
        serial: Envoy serienummer (fx "122328094789").
        username: Enlighten Manager email (DIY-konto).
        password: Enlighten Manager adgangskode.
    """

    def __init__(self, host: str, serial: str,
                 username: Optional[str] = None,
                 password: Optional[str] = None) -> None:
        self.host = host
        self.serial = serial
        self.username = username
        self.password = password
        self._session = None
        self._token: Optional[str] = None

    async def discover(self) -> list[str]:
        """Find Enphase Envoy på lokalt netværk via mDNS og port-scan.

        Forsøger først envoy.local (mDNS), derefter netværksscan.

        Returns:
            Liste af IP-adresser hvor Envoy blev fundet.
        """
        found = []
        try:
            import socket
            ip = socket.gethostbyname("envoy.local")
            if await self._probe(ip):
                found.append(ip)
                return found
        except Exception:
            pass

        # Netværksscan på port 80 (Envoy HTTP API)
        import asyncio
        import ipaddress

        async def probe_host(ip_str: str) -> Optional[str]:
            try:
                fut = asyncio.open_connection(ip_str, 80)
                reader, writer = await asyncio.wait_for(fut, timeout=0.5)
                writer.close()
                await writer.wait_closed()
                if await self._probe(ip_str):
                    return ip_str
            except Exception:
                pass
            return None

        # Scan 192.168.1.0/24 (typisk hjemmenetværk)
        tasks = [probe_host(str(ip)) for ip in ipaddress.ip_network("192.168.1.0/24").hosts()]
        results = await asyncio.gather(*tasks)
        found = [ip for ip in results if ip]
        return found

    async def _probe(self, host: str) -> bool:
        """Tjek om dette er en Enphase Envoy ved at kalde /info."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{host}/info",
                    timeout=aiohttp.ClientTimeout(total=3),
                    ssl=False
                ) as resp:
                    text = await resp.text()
                    return "envoy" in text.lower() or "enphase" in text.lower()
        except Exception:
            return False

    async def get_status(self) -> BatteryStatus:
        """Hent aktuel batteristatus fra Envoy.

        Raises:
            ConnectionError: Hvis Envoy ikke kan nås.
        """
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Hent batteri SOC og effekt
                async with session.get(
                    f"http://{self.host}{_ENDPOINT_SOC}",
                    timeout=aiohttp.ClientTimeout(total=5),
                    ssl=False
                ) as resp:
                    if resp.status != 200:
                        raise ConnectionError(f"Envoy returnerede HTTP {resp.status}")
                    data = await resp.json()

            # Parse Enphase inventory-format
            soc = 0.0
            power_kw = 0.0
            for device in data:
                if device.get("type") == "ENCHARGE":
                    for d in device.get("devices", []):
                        soc = float(d.get("percentFull", 0))
                        # Enphase: negativ effekt = lader
                        watts = float(d.get("real_power_mw", 0)) / 1000.0
                        power_kw = -watts / 1000.0

            return BatteryStatus(
                soc_percent=soc,
                power_kw=power_kw,
                is_online=True,
                raw=data
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(f"Kunne ikke hente Enphase status: {err}") from err

    async def set_reserve_percent(self, percent: float) -> bool:
        """Sæt Envoy battery reserve via opt_schedules API.

        Kræver DIY-konto. Bruger samme metode som TEO's battery_actuator.

        Args:
            percent: Reserve i procent (0.0-100.0).

        Raises:
            NotSupportedError: Hvis ingen DIY-credentials er konfigureret.
            ConnectionError: Hvis Envoy ikke kan nås.
            ValueError: Hvis percent er uden for 0-100.
        """
        if not self.username or not self.password:
            raise NotSupportedError(
                "DIY Enlighten Manager-konto kræves for reserve-styring. "
                "Se teo.energy/enphase-guide"
            )
        if not 0 <= percent <= 100:
            raise ValueError(f"Reserve skal være 0-100, fik {percent}")

        try:
            token = await self._get_token()
            import aiohttp
            payload = {
                "storage_mode": "self-consumption",
                "opt_schedules": False,
                "reserved_soc": int(percent),
            }
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"https://{self.host}{_ENDPOINT_OPT_SCHEDULES}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                    ssl=False
                ) as resp:
                    return resp.status < 300
        except NotSupportedError:
            raise
        except Exception as err:
            raise ConnectionError(f"Kunne ikke sætte Enphase reserve: {err}") from err

    async def set_charge_from_grid(self, enabled: bool) -> bool:
        """Aktiver/deaktiver netladning via Envoy opt_schedules API.

        Kræver DIY-konto.

        Raises:
            NotSupportedError: Hvis ingen DIY-credentials er konfigureret.
            ConnectionError: Hvis Envoy ikke kan nås.
        """
        if not self.username or not self.password:
            raise NotSupportedError(
                "DIY Enlighten Manager-konto kræves for netladnings-styring."
            )
        try:
            token = await self._get_token()
            import aiohttp
            payload = {
                "storage_mode": "self-consumption",
                "opt_schedules": False,
                "charge_from_grid": enabled,
            }
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"https://{self.host}{_ENDPOINT_OPT_SCHEDULES}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                    ssl=False
                ) as resp:
                    return resp.status < 300
        except NotSupportedError:
            raise
        except Exception as err:
            raise ConnectionError(f"Kunne ikke sætte charge_from_grid: {err}") from err

    async def _get_token(self) -> str:
        """Hent JWT token fra Enlighten Manager (caches i session)."""
        if self._token:
            return self._token
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://enlighten.enphaseenergy.com/login/login.json",
                    data={
                        "user[email]": self.username,
                        "user[password]": self.password,
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    session_id = data.get("session_id", "")

                async with session.post(
                    "https://entrez.enphaseenergy.com/tokens",
                    json={
                        "session_id": session_id,
                        "serial_num": self.serial,
                        "username": self.username,
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    self._token = await resp.text()
                    return self._token
        except Exception as err:
            raise ConnectionError(f"Kunne ikke hente Enphase token: {err}") from err

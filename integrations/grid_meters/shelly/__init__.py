"""Shelly EM / 3EM elmåler integration til TEO.

Protokol: Lokalt REST API (HTTP) — ingen cloud kræves.
"""

from __future__ import annotations
import logging
from typing import Optional
from ..base.grid_meter_base import GridMeterBase, GridMeterStatus

_LOGGER = logging.getLogger(__name__)


class ShellyEMMeter(GridMeterBase):
    """TEO-integration til Shelly EM / 3EM / Pro 3EM.

    Args:
        host: IP-adresse til Shelly (fx "192.168.1.60").
        channel: Kanal til netmåling (standard: 0).
    """

    def __init__(self, host: str, channel: int = 0) -> None:
        self.host = host
        self.channel = channel

    async def discover(self) -> list[str]:
        """Find Shelly EM på lokalt netværk."""
        import asyncio
        import ipaddress

        async def probe(ip_str: str) -> Optional[str]:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://{ip_str}/shelly",
                        timeout=aiohttp.ClientTimeout(total=1.0)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            t = data.get("type", "").upper()
                            if "EM" in t or "SHEM" in t:
                                return ip_str
            except Exception:
                pass
            return None

        tasks = [probe(str(ip))
                 for ip in ipaddress.ip_network("192.168.1.0/24").hosts()]
        results = await asyncio.gather(*tasks)
        return [ip for ip in results if ip]

    async def get_status(self) -> GridMeterStatus:
        """Hent aktuel neteffekt fra Shelly EM."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Prøv Gen2 API (Pro 3EM)
                async with session.get(
                    f"http://{self.host}/rpc/EM.GetStatus",
                    params={"id": self.channel},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        power_w = float(data.get("total_act_power",
                                        data.get("act_power", 0)))
                        voltage = data.get("a_voltage") or data.get("voltage")
                        return GridMeterStatus(
                            grid_power_kw=power_w / 1000.0,
                            is_online=True,
                            voltage_v=float(voltage) if voltage else None,
                            raw=data
                        )

                # Fallback Gen1 API
                async with session.get(
                    f"http://{self.host}/status",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        raise ConnectionError(f"Shelly HTTP {resp.status}")
                    data = await resp.json()

            emeters = data.get("emeters", [])
            if not emeters:
                raise ConnectionError("Ingen emeter-data fra Shelly.")

            total_w = sum(float(em.get("power", 0)) for em in emeters)
            voltage = emeters[0].get("voltage") if emeters else None

            return GridMeterStatus(
                grid_power_kw=total_w / 1000.0,
                is_online=True,
                voltage_v=float(voltage) if voltage else None,
                raw=data
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(f"Fejl ved Shelly EM: {err}") from err

"""HomeWizard P1 Meter integration til TEO.

Kommunikerer lokalt via HomeWizard Energy API v1.
Ingen cloud-konto kræves — men "Local API" skal aktiveres i appen.

Protokol: Lokalt REST API (HTTP)
Auto-discovery: mDNS (p1meter-XXXXXX.local) + portscan port 80
"""

from __future__ import annotations

import logging
from typing import Optional

from ..base.grid_meter_base import GridMeterBase, GridMeterStatus

_LOGGER = logging.getLogger(__name__)

_HW_API_PATH = "/api/v1/data"
_HW_INFO_PATH = "/api"


class HomeWizardP1Meter(GridMeterBase):
    """TEO-integration til HomeWizard P1 Meter.

    Kræver at "Local API" er aktiveret i HomeWizard Energy-appen:
    Indstillinger → Målere → P1 Meter → Local API → Aktiver.

    Args:
        host: IP-adresse til HomeWizard P1 Meter.
    """

    def __init__(self, host: str) -> None:
        self.host = host

    async def discover(self) -> list[str]:
        """Find HomeWizard P1 Meter på lokalt netværk."""
        import asyncio
        import ipaddress

        async def probe(ip_str: str) -> Optional[str]:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://{ip_str}{_HW_INFO_PATH}",
                        timeout=aiohttp.ClientTimeout(total=1.0)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # HomeWizard returnerer product_type
                            product = data.get("product_type", "")
                            if "p1" in product.lower() or "HWE-P1" in product:
                                return ip_str
            except Exception:
                pass
            return None

        tasks = [probe(str(ip))
                 for ip in ipaddress.ip_network("192.168.1.0/24").hosts()]
        results = await asyncio.gather(*tasks)
        return [ip for ip in results if ip]

    async def get_status(self) -> GridMeterStatus:
        """Hent aktuel neteffekt fra HomeWizard P1 Meter.

        Raises:
            ConnectionError: Hvis måleren ikke kan nås eller Local API ikke er aktiveret.
        """
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.host}{_HW_API_PATH}",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 403:
                        raise ConnectionError(
                            "HomeWizard P1 afviser forbindelsen. "
                            "Aktiver Local API i HomeWizard Energy-appen: "
                            "Indstillinger → Målere → P1 Meter → Local API."
                        )
                    if resp.status != 200:
                        raise ConnectionError(
                            f"HomeWizard P1 returnerede HTTP {resp.status}")
                    data = await resp.json()

            # HomeWizard API v1 felter:
            # active_power_w: aktuel neteffekt i W
            # (+) = import fra net, (-) = eksport til net
            power_w = float(data.get("active_power_w", 0))
            voltage = data.get("active_voltage_l1_v") or data.get("active_voltage_v")

            return GridMeterStatus(
                grid_power_kw=power_w / 1000.0,
                is_online=True,
                voltage_v=float(voltage) if voltage else None,
                raw=data
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(
                f"Kunne ikke hente HomeWizard P1 status: {err}") from err

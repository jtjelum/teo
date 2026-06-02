"""Victron Energy integration til TEO.

Kommunikerer med Victron via MQTT på Venus OS (Cerbo GX, CCGX, Raspberry Pi
med Venus OS). Victron er den mest veldokumenterede open source batteriplatform
— fuld læse- og skrivekontrol via MQTT.

Protokol: MQTT (Venus OS lokalnetværk)
Auto-discovery: mDNS (venus.local) + MQTT discovery
Krav: Venus OS med MQTT aktiveret (standard i nyere firmware)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..base.battery_base import BatteryBase, BatteryStatus

_LOGGER = logging.getLogger(__name__)

_VICTRON_MQTT_PORT = 1883
_VICTRON_MDNS = "venus.local"


class VictronBattery(BatteryBase):
    """TEO-integration til Victron Energy batterisystemer.

    Forbinder til Venus OS via MQTT på det lokale netværk.
    Understøtter Victron MultiPlus, Quattro og alle GX-enheder.

    Args:
        host: IP-adresse eller hostname til Venus OS enhed.
        system_id: Venus OS system serial number.
                   Find den i Venus OS Remote Console → System → Serial.
        mqtt_port: MQTT port (standard: 1883).
        mqtt_user: MQTT brugernavn (valgfri).
        mqtt_password: MQTT adgangskode (valgfri).
    """

    def __init__(self, host: str, system_id: str,
                 mqtt_port: int = _VICTRON_MQTT_PORT,
                 mqtt_user: Optional[str] = None,
                 mqtt_password: Optional[str] = None) -> None:
        self.host = host
        self.system_id = system_id
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password

    async def discover(self) -> list[str]:
        """Find Victron Venus OS på lokalt netværk via mDNS og portscan."""
        import asyncio
        import socket
        found = []

        try:
            ip = socket.gethostbyname(_VICTRON_MDNS)
            found.append(ip)
            return found
        except Exception:
            pass

        import ipaddress

        async def probe(ip_str: str) -> Optional[str]:
            try:
                fut = asyncio.open_connection(ip_str, _VICTRON_MQTT_PORT)
                _, writer = await asyncio.wait_for(fut, timeout=0.5)
                writer.close()
                await writer.wait_closed()
                return ip_str
            except Exception:
                return None

        tasks = [probe(str(ip))
                 for ip in ipaddress.ip_network("192.168.1.0/24").hosts()]
        results = await asyncio.gather(*tasks)
        return [ip for ip in results if ip]

    async def get_status(self) -> BatteryStatus:
        """Hent batteristatus via Venus OS MQTT."""
        try:
            import asyncio
            import aiomqtt

            soc = None
            power_w = None
            capacity_wh = None

            topics = [
                f"N/{self.system_id}/battery/0/Soc",
                f"N/{self.system_id}/battery/0/Power",
                f"N/{self.system_id}/battery/0/InstalledCapacity",
            ]

            async with aiomqtt.Client(
                self.host, port=self.mqtt_port,
                username=self.mqtt_user, password=self.mqtt_password,
            ) as client:
                for topic in topics:
                    await client.subscribe(topic)
                try:
                    async with asyncio.timeout(5.0):
                        async for message in client.messages:
                            payload = json.loads(message.payload)
                            value = payload.get("value")
                            t = str(message.topic)
                            if "Soc" in t:
                                soc = float(value) if value is not None else None
                            elif "Power" in t:
                                power_w = float(value) if value is not None else None
                            elif "InstalledCapacity" in t:
                                capacity_wh = float(value) if value is not None else None
                            if soc is not None and power_w is not None:
                                break
                except asyncio.TimeoutError:
                    pass

            if soc is None:
                raise ConnectionError(
                    f"Ingen data fra Victron på {self.host}. "
                    "Aktiver MQTT i Venus OS: Settings → Services → MQTT on LAN.")

            return BatteryStatus(
                soc_percent=soc,
                power_kw=(power_w / 1000.0) if power_w is not None else 0.0,
                capacity_kwh=(capacity_wh / 1000.0) if capacity_wh else None,
                is_online=True,
                raw={"soc": soc, "power_w": power_w}
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(f"Fejl ved Victron: {err}") from err

    async def set_reserve_percent(self, percent: float) -> bool:
        """Sæt minimum SOC via Venus OS ESS-indstillinger."""
        try:
            import aiomqtt
            topic = f"W/{self.system_id}/settings/0/Settings/CGwacs/BatteryLife/MinimumSocLimit"
            async with aiomqtt.Client(
                self.host, port=self.mqtt_port,
                username=self.mqtt_user, password=self.mqtt_password,
            ) as client:
                await client.publish(topic, json.dumps({"value": percent}))
            return True
        except Exception as err:
            raise ConnectionError(f"Kunne ikke sætte Victron reserve: {err}") from err

    async def set_charge_from_grid(self, enabled: bool) -> bool:
        """Aktiver/deaktiver netladning via Venus OS ESS."""
        try:
            import aiomqtt
            topic = f"W/{self.system_id}/settings/0/Settings/CGwacs/MaxChargePower"
            async with aiomqtt.Client(
                self.host, port=self.mqtt_port,
                username=self.mqtt_user, password=self.mqtt_password,
            ) as client:
                await client.publish(topic, json.dumps({"value": -1 if enabled else 0}))
            return True
        except Exception as err:
            raise ConnectionError(f"Kunne ikke sætte Victron charge_from_grid: {err}") from err

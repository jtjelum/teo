"""BYD Battery-Box integration til TEO.

Kommunikerer med BYD Battery-Box via Modbus TCP.
Understøtter HVS, HVM, HVL og LVS serien.

Protokol: Modbus TCP port 8080 (BYD standard)
Auto-discovery: Netværksscan port 8080
Standard IP: 192.168.16.254 (BYD default) eller DHCP
"""

from __future__ import annotations

import logging
from typing import Optional

from ..base.battery_base import BatteryBase, BatteryStatus, NotSupportedError

_LOGGER = logging.getLogger(__name__)

_BYD_DEFAULT_IP = "192.168.16.254"
_BYD_MODBUS_PORT = 8080

# Modbus register-adresser (BYD Battery-Box protokol)
_REG_SOC = 0x0100          # State of Charge (0-1000 → 0-100%)
_REG_POWER = 0x0102        # Aktuel effekt i W (signed)
_REG_CAPACITY = 0x0104     # Total kapacitet i Wh
_REG_STATUS = 0x0106       # Status register


class BYDBatteryBox(BatteryBase):
    """TEO-integration til BYD Battery-Box HVS/HVM/HVL/LVS.

    Kommunikerer lokalt via Modbus TCP — ingen cloud-konto kræves.
    Batteriet skal være forbundet med netværkskabel (WiFi deaktiverer
    sig efter timeout i nyere firmware).

    Args:
        host: IP-adresse til BYD Battery-Box.
              Standard BYD-adresse er 192.168.16.254.
              Nyere firmware understøtter DHCP — find IP i router.
        port: Modbus TCP port (standard: 8080).
        unit_id: Modbus unit ID (standard: 1).
    """

    def __init__(self, host: str = _BYD_DEFAULT_IP,
                 port: int = _BYD_MODBUS_PORT,
                 unit_id: int = 1) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id

    async def discover(self) -> list[str]:
        """Find BYD Battery-Box på lokalt netværk.

        Forsøger først standard BYD IP (192.168.16.254),
        derefter DHCP-scan på port 8080.

        Returns:
            Liste af IP-adresser hvor BYD blev fundet.
        """
        import asyncio
        found = []

        async def probe(ip: str) -> Optional[str]:
            try:
                fut = asyncio.open_connection(ip, _BYD_MODBUS_PORT)
                reader, writer = await asyncio.wait_for(fut, timeout=1.0)
                writer.close()
                await writer.wait_closed()
                return ip
            except Exception:
                return None

        # Prøv standard BYD IP først
        result = await probe(_BYD_DEFAULT_IP)
        if result:
            found.append(result)
            return found

        # Scan lokalt netværk
        import ipaddress
        tasks = [probe(str(ip))
                 for ip in ipaddress.ip_network("192.168.1.0/24").hosts()]
        results = await asyncio.gather(*tasks)
        found = [ip for ip in results if ip]
        return found

    async def get_status(self) -> BatteryStatus:
        """Hent aktuel batteristatus via Modbus TCP.

        Raises:
            ConnectionError: Hvis batteriet ikke kan nås.
        """
        try:
            from pymodbus.client import AsyncModbusTcpClient
            client = AsyncModbusTcpClient(self.host, port=self.port)
            await client.connect()

            if not client.connected:
                raise ConnectionError(
                    f"Kunne ikke forbinde til BYD Battery-Box på {self.host}:{self.port}")

            try:
                # Læs SOC (register 0x0100, 1 register)
                soc_result = await client.read_holding_registers(
                    _REG_SOC, count=1, slave=self.unit_id)
                # Læs effekt (register 0x0102, 1 register, signed)
                power_result = await client.read_holding_registers(
                    _REG_POWER, count=1, slave=self.unit_id)
                # Læs kapacitet (register 0x0104, 1 register)
                cap_result = await client.read_holding_registers(
                    _REG_CAPACITY, count=1, slave=self.unit_id)
            finally:
                client.close()

            if soc_result.isError() or power_result.isError():
                raise ConnectionError("BYD Modbus returnerede fejl")

            soc = soc_result.registers[0] / 10.0  # 0-1000 → 0-100%
            # Signed 16-bit: positiv = lader, negativ = aflader
            raw_power = power_result.registers[0]
            power_w = raw_power if raw_power < 32768 else raw_power - 65536
            power_kw = power_w / 1000.0

            capacity_kwh = None
            if not cap_result.isError():
                capacity_kwh = cap_result.registers[0] / 1000.0

            return BatteryStatus(
                soc_percent=soc,
                power_kw=power_kw,
                capacity_kwh=capacity_kwh,
                is_online=True,
                raw={
                    "soc_raw": soc_result.registers[0],
                    "power_raw": raw_power,
                }
            )
        except ConnectionError:
            raise
        except Exception as err:
            raise ConnectionError(
                f"Fejl ved læsning af BYD Battery-Box: {err}") from err

    async def set_reserve_percent(self, percent: float) -> bool:
        """BYD Battery-Box understøtter ikke reserve-styring via Modbus.

        BYD har ingen offentlig Modbus-kommando til at sætte reserve.
        Styring sker via BYD-appen eller inverter-integration.

        Raises:
            NotSupportedError: Altid — BYD understøtter ikke dette via lokal API.
        """
        raise NotSupportedError(
            "BYD Battery-Box understøtter ikke reserve-styring via lokal API. "
            "Brug BYD-appen eller kombiner med en SolarEdge/Huawei-inverter."
        )

    async def set_charge_from_grid(self, enabled: bool) -> bool:
        """BYD Battery-Box understøtter ikke netladnings-styring via Modbus.

        Raises:
            NotSupportedError: Altid — BYD understøtter ikke dette via lokal API.
        """
        raise NotSupportedError(
            "BYD Battery-Box understøtter ikke netladnings-styring via lokal API. "
            "Brug BYD-appen eller kombiner med en kompatibel inverter."
        )

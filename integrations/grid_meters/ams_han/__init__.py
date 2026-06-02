"""AMS/HAN-reader elmåler integration til TEO.

Modtager realtids neteffekt fra nordiske AMS-readere via MQTT.
Understøtter alle HAN P1-kompatible readere (Kamstrup, Aidon, Kaifa m.fl.).

Protokol: MQTT (reader sender til lokal Mosquitto broker)
Auto-discovery: MQTT topic discovery
"""

from __future__ import annotations

import logging
from typing import Optional

from ..base.grid_meter_base import GridMeterBase, GridMeterStatus

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TOPIC = "ams/power"
_DEFAULT_MQTT_HOST = "localhost"
_DEFAULT_MQTT_PORT = 1883


class AMSHANMeter(GridMeterBase):
    """TEO-integration til AMS/HAN-reader via MQTT.

    Readeren skal konfigureres til at sende til lokal MQTT-broker.
    TEO lytter på MQTT-topic og opdaterer neteffekt i realtid.

    Args:
        mqtt_topic: MQTT topic reader sender til (default: "ams/power").
        mqtt_host: MQTT broker hostname (default: "localhost").
        mqtt_port: MQTT broker port (default: 1883).
    """

    def __init__(self, mqtt_topic: str = _DEFAULT_TOPIC,
                 mqtt_host: str = _DEFAULT_MQTT_HOST,
                 mqtt_port: int = _DEFAULT_MQTT_PORT) -> None:
        self.mqtt_topic = mqtt_topic
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self._last_reading: Optional[dict] = None

    async def discover(self) -> list[str]:
        """Find AMS-reader ved at lytte på MQTT.

        Returnerer topic-navn hvis der modtages data inden timeout.

        Returns:
            Liste med MQTT topic hvis reader er aktiv, ellers tom liste.
        """
        try:
            import asyncio
            import aiomqtt

            found = []
            async with aiomqtt.Client(self.mqtt_host, self.mqtt_port) as client:
                await client.subscribe(self.mqtt_topic)
                try:
                    async with asyncio.timeout(5.0):
                        async for message in client.messages:
                            found.append(self.mqtt_topic)
                            break
                except asyncio.TimeoutError:
                    pass
            return found
        except Exception as err:
            _LOGGER.warning("AMS/HAN discovery fejlede: %s", err)
            return []

    async def get_status(self) -> GridMeterStatus:
        """Returnerer seneste MQTT-måling.

        Raises:
            ConnectionError: Hvis ingen måling er modtaget endnu.
        """
        if self._last_reading is None:
            raise ConnectionError(
                "Ingen AMS/HAN måling modtaget endnu. "
                "Tjek at MQTT-broker kører og reader sender til topic: "
                f"{self.mqtt_topic}"
            )

        raw = self._last_reading
        # AMS-reader JSON format: data.P = import W, data.PO = eksport W
        data = raw.get("data", raw)
        import_w = float(data.get("P", data.get("import_w", 0.0)))
        export_w = float(data.get("PO", data.get("export_w", 0.0)))
        grid_kw = (import_w - export_w) / 1000.0

        return GridMeterStatus(
            grid_power_kw=grid_kw,
            is_online=True,
            voltage_v=float(data.get("U1", data.get("voltage_v", 0.0))) or None,
            raw=raw
        )

    def update_from_mqtt(self, payload: dict) -> None:
        """Opdatér seneste måling fra MQTT callback.

        Kaldes af TEO's MQTT-subscriber når ny måling ankommer.
        Denne metode er synkron og kan kaldes fra enhver tråd.

        Args:
            payload: Parsed JSON fra MQTT-besked.
        """
        self._last_reading = payload

"""Base-klasse for elmåler-integrationer.

Elmåleren giver TEO realtids neteffekt — kritisk for at vide hvad huset
forbruger lige nu og om der eksporteres til nettet.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GridMeterStatus:
    """Aktuel elmålerstatus."""
    grid_power_kw: float            # + = import fra net, - = eksport til net
    is_online: bool = True
    voltage_v: Optional[float] = None
    frequency_hz: Optional[float] = None
    raw: dict = field(default_factory=dict)


class GridMeterBase(ABC):
    """Abstrakt base-klasse for alle elmåler-integrationer."""

    @abstractmethod
    async def discover(self) -> list[str]:
        """Scan lokalt netværk eller lyt på MQTT for målere af denne type.

        Returns:
            Liste af IP-adresser eller MQTT-topics. Tom liste hvis intet fundet.
        """

    @abstractmethod
    async def get_status(self) -> GridMeterStatus:
        """Hent aktuel målerstatus.

        Raises:
            ConnectionError: Hvis måleren ikke kan nås.
        """

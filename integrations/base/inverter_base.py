"""Base-klasse for inverter-integrationer.

Invertere leverer solproduktionsdata til TEO's LP-optimizer og dashboard.
Nogle invertere kombineres med batteri (fx Enphase Envoy + IQ Battery) —
i det tilfælde implementeres både InverterBase og BatteryBase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InverterStatus:
    """Aktuel inverterstatus."""
    solar_production_kw: float              # Aktuel solproduktion
    grid_import_kw: float                   # Netimport (+ = import, - = eksport)
    house_consumption_kw: Optional[float] = None  # Husets forbrug
    lifetime_production_kwh: Optional[float] = None  # Total livstidsproduktion
    is_online: bool = True
    raw: dict = field(default_factory=dict)


class InverterBase(ABC):
    """Abstrakt base-klasse for alle inverter-integrationer."""

    @abstractmethod
    async def discover(self) -> list[str]:
        """Scan lokalt netværk for invertere af denne type.

        Returns:
            Liste af IP-adresser. Tom liste hvis intet fundet.
        """

    @abstractmethod
    async def get_status(self) -> InverterStatus:
        """Hent aktuel inverterstatus.

        Raises:
            ConnectionError: Hvis inverteren ikke kan nås.
        """

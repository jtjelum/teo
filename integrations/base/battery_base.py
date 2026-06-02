"""Base-klasse for batteriintegrationer.

Alle batteriintegrationer til TEO skal arve fra ``BatteryBase`` og
implementere de abstrakte metoder. Gør de det, fungerer enheden automatisk
med LP-optimizeren og dashboardet — uden ændringer i TEO-kernen.

Eksempel:
    from integrations.base.battery_base import BatteryBase, BatteryStatus

    class MinBatteri(BatteryBase):
        async def get_status(self) -> BatteryStatus:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class NotSupportedError(Exception):
    """Kastes når en enhed ikke understøtter den ønskede funktion."""


@dataclass
class BatteryStatus:
    """Aktuel batteristatus.

    Alle felter med ``None`` betyder at enheden ikke understøtter/rapporterer
    den pågældende værdi. TEO håndterer ``None`` gracefully.
    """
    soc_percent: float                          # Batteriniveau 0-100 %
    power_kw: float                             # + = lader, - = aflader
    capacity_kwh: Optional[float] = None        # Total kapacitet
    charge_from_grid_active: Optional[bool] = None  # Netladning aktiv?
    reserve_percent: Optional[float] = None     # Aktuel reserve-indstilling
    temperature_c: Optional[float] = None       # Batteritemperatur
    is_online: bool = True                      # Enheden kan nås
    raw: dict = field(default_factory=dict)     # Rå API-respons til debug


class BatteryBase(ABC):
    """Abstrakt base-klasse for alle batteriintegrationer.

    Implementér ``discover()``, ``get_status()``, ``set_reserve_percent()``
    og ``set_charge_from_grid()`` for at understøtte fuld TEO-funktionalitet.

    Metoder der ikke er understøttet af enheden skal kaste ``NotSupportedError``.
    De må ALDRIG bare returnere ``None`` eller ``True`` uden at gøre noget —
    det maskerer fejl og giver stille forkert adfærd.
    """

    @abstractmethod
    async def discover(self) -> list[str]:
        """Scan lokalt netværk for enheder af denne type.

        Returnerer liste af IP-adresser hvor enheden blev fundet.
        Brug aldrig blocking kode — kun async.

        Returns:
            Liste af IP-adresser, fx ["192.168.1.189"]. Tom liste hvis intet fundet.
        """

    @abstractmethod
    async def get_status(self) -> BatteryStatus:
        """Hent aktuel batteristatus.

        Raises:
            ConnectionError: Hvis enheden ikke kan nås.
            ValueError: Hvis API-svaret er ugyldigt.
        """

    @abstractmethod
    async def set_reserve_percent(self, percent: float) -> bool:
        """Sæt reserve-niveau (0-100 %).

        Reserven er det minimum-SOC batteriet ikke aflades under.
        TEO bruger dette til at beskytte batteriet og til EV-styring.

        Args:
            percent: Ønsket reserve i procent (0.0-100.0).

        Returns:
            True hvis kommandoen blev accepteret af enheden.

        Raises:
            NotSupportedError: Hvis enheden ikke understøtter reserve-styring.
            ConnectionError: Hvis enheden ikke kan nås.
            ValueError: Hvis percent er uden for 0-100.
        """

    @abstractmethod
    async def set_charge_from_grid(self, enabled: bool) -> bool:
        """Aktiver/deaktiver netladning.

        Args:
            enabled: True = tillad netladning, False = kun sol.

        Returns:
            True hvis kommandoen blev accepteret.

        Raises:
            NotSupportedError: Hvis enheden ikke understøtter netladnings-styring.
            ConnectionError: Hvis enheden ikke kan nås.
        """

    async def set_storage_mode(self, mode: str) -> bool:
        """Sæt lagringstilstand (valgfri — ikke alle enheder understøtter dette).

        Args:
            mode: "self_consumption", "backup", "charge_only" eller "discharge_only".

        Returns:
            True hvis accepteret.

        Raises:
            NotSupportedError: Standard — override i subklasse hvis understøttet.
        """
        raise NotSupportedError(f"{self.__class__.__name__} understøtter ikke storage mode")

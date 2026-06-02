"""Base-klasse for EV-lader-integrationer.

TEO bruger EV-ladere til at styre hvornår og hvor hurtigt bilen lades —
primært for at undgå at dræne husbatteriet og for at udnytte billig strøm.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class NotSupportedError(Exception):
    """Kastes når en enhed ikke understøtter den ønskede funktion."""


@dataclass
class EVChargerStatus:
    """Aktuel EV-laderstatus."""
    is_charging: bool                           # Lader bilen lige nu?
    charge_power_kw: float                      # Aktuel ladeeffekt
    cable_connected: bool                       # Kabel tilsluttet?
    is_online: bool = True
    max_current_a: Optional[float] = None       # Maks strømstyrke (A)
    session_energy_kwh: Optional[float] = None  # Energi i aktuel session
    raw: dict = field(default_factory=dict)


class EVChargerBase(ABC):
    """Abstrakt base-klasse for alle EV-lader-integrationer."""

    @abstractmethod
    async def discover(self) -> list[str]:
        """Scan lokalt netværk for ladere af denne type.

        Returns:
            Liste af IP-adresser. Tom liste hvis intet fundet.
        """

    @abstractmethod
    async def get_status(self) -> EVChargerStatus:
        """Hent aktuel laderstatus.

        Raises:
            ConnectionError: Hvis laderen ikke kan nås.
        """

    @abstractmethod
    async def set_charging_enabled(self, enabled: bool) -> bool:
        """Start eller stop ladning.

        Args:
            enabled: True = start ladning, False = stop.

        Returns:
            True hvis kommandoen blev accepteret.

        Raises:
            NotSupportedError: Hvis laderen ikke understøtter on/off-styring.
            ConnectionError: Hvis laderen ikke kan nås.
        """

    async def set_current_limit(self, current_a: float) -> bool:
        """Sæt maks strømstyrke (valgfri).

        Args:
            current_a: Ønsket strømstyrke i ampere.

        Returns:
            True hvis accepteret.

        Raises:
            NotSupportedError: Standard — override i subklasse hvis understøttet.
        """
        raise NotSupportedError(f"{self.__class__.__name__} understøtter ikke strømstyring")

"""TEO Algorithm Version Management.

Håndterer automatisk versionering ved succesfuld daily calibration:
- Format: MAJOR.MINOR.PATCH
- PATCH bump ved hver succesfull kalibrering
- PATCH 99→100: bump MINOR, reset PATCH til 0
- MINOR 9→10: bump MAJOR, reset MINOR og PATCH til 0
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

_LOGGER = logging.getLogger(__name__)

VERSION_FILE: Final = "/config/teo_algorithm_version.txt"
DEFAULT_VERSION: Final = "0.0.0"


def read_version() -> str:
    """Læs nuværende version fra fil. Returnerer default hvis fil ikke eksisterer."""
    try:
        path = Path(VERSION_FILE)
        if path.exists():
            version = path.read_text().strip()
            # Validér format MAJOR.MINOR.PATCH
            parts = version.split(".")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                return version
            _LOGGER.warning("Ugyldig version format i %s: %s, bruger default", VERSION_FILE, version)
    except Exception as err:
        _LOGGER.warning("Kunne ikke læse version fra %s: %s", VERSION_FILE, err)
    return DEFAULT_VERSION


def write_version(version: str) -> None:
    """Skriv version til fil."""
    try:
        Path(VERSION_FILE).write_text(version)
        _LOGGER.debug("Version skrevet til %s: %s", VERSION_FILE, version)
    except Exception as err:
        _LOGGER.error("Kunne ikke skrive version til %s: %s", VERSION_FILE, err)


def bump_algorithm_version() -> str:
    """Bump algorithm version efter succesfuld daily calibration.
    
    Logik:
    - PATCH++
    - PATCH 99→100: MINOR++, PATCH=0
    - MINOR 9→10: MAJOR++, MINOR=0, PATCH=0
    - MAJOR bare fortsætter opad
    
    Returns:
        Ny version som string (MAJOR.MINOR.PATCH)
    """
    current = read_version()
    major, minor, patch = map(int, current.split("."))
    
    # Bump PATCH
    patch += 1
    
    # Check PATCH overflow
    if patch >= 100:
        patch = 0
        minor += 1
        
        # Check MINOR overflow
        if minor >= 10:
            minor = 0
            major += 1
    
    new_version = f"{major}.{minor}.{patch}"
    write_version(new_version)
    _LOGGER.info("Algorithm version bumped: %s → %s", current, new_version)
    return new_version

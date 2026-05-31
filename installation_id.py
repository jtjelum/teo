"""Installations-ID — lokal UUID-generering, -gendannelse og læsevenligt navn.

Spec §3.1. Designprincip #5 (Privacy by design): UUID'et genereres og gemmes
KUN lokalt. Det forlader først enheden hvis brugeren aktivt vælger
Self-Hosted-tilstand og gendanner/registrerer via TEO API.

Filoperationerne er synkrone og bevidst trivielle (én lille tekstfil). I HA
bør de kaldes via ``hass.async_add_executor_job`` for ikke at blokere
event-loopet — det er kalderens ansvar, så modulet forbliver testbart uden HA.
"""

from __future__ import annotations

import logging
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

from .const import CONFIG_DIR, INSTALLATION_ID_FILE

_LOGGER = logging.getLogger(__name__)

# Fast vokabular til læsevenligt ID. Ordene er IKKE brugervendt UI-tekst, men
# en stabil navngivnings-namespace: ændres listen, ændres alle afledte navne.
# Derfor hører de hjemme her (data) og ikke i translations/. Hold listerne
# uændrede mellem versioner for at bevare genkendelighed.
_HR_ADJECTIVES: tuple[str, ...] = (
    "sol", "vind", "regn", "frost", "lys", "stille", "klar", "blå",
    "grøn", "gylden", "kølig", "varm", "frisk", "rolig", "stærk", "let",
)
_HR_NOUNS: tuple[str, ...] = (
    "batteri", "panel", "strøm", "energi", "bølge", "gnist", "flow", "puls",
    "kreds", "fase", "celle", "ladning", "spænding", "effekt", "net", "ø",
)
_HR_SUFFIXES: tuple[str, ...] = (
    "vind", "sol", "hav", "skov", "bakke", "eng", "fjord", "klit",
    "mose", "hede", "dal", "top", "kyst", "vig", "sø", "å",
)


def generate_installation_id(config_dir: str = CONFIG_DIR) -> str:
    """Generér et nyt UUID4, gem det lokalt og returnér det som string."""
    new_id = str(uuid_lib.uuid4())
    path = Path(config_dir) / INSTALLATION_ID_FILE
    path.write_text(new_id + "\n", encoding="utf-8")
    _LOGGER.info("Genererede nyt installations-ID (%s)", get_human_readable_id(new_id))
    return new_id


def get_installation_id(config_dir: str = CONFIG_DIR) -> str:
    """Returnér eksisterende installations-ID eller generér et nyt.

    Læser fra ``/config/teo_installation_id.txt`` hvis filen findes og
    indeholder et gyldigt UUID; ellers genereres et nyt.
    """
    path = Path(config_dir) / INSTALLATION_ID_FILE
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if is_valid_uuid(raw):
            return raw
        _LOGGER.warning(
            "Installations-ID-fil var ugyldig (%r) — genererer nyt", raw
        )
    return generate_installation_id(config_dir)


def is_valid_uuid(value: str) -> bool:
    """True hvis ``value`` er et velformet UUID."""
    try:
        uuid_lib.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def get_human_readable_id(installation_uuid: str) -> str:
    """Konvertér et UUID deterministisk til tre danske ord, fx "sol-batteri-vind".

    Bruges udelukkende som hjælp til genkendelse i UI — aldrig som nøgle.
    Samme UUID giver altid samme navn (deterministisk afledning af UUID-bytes).
    """
    parsed = uuid_lib.UUID(str(installation_uuid))
    b = parsed.bytes
    # Brug adskilte byte-grupper så de tre ord varierer uafhængigt.
    adjective = _HR_ADJECTIVES[b[0] % len(_HR_ADJECTIVES)]
    noun = _HR_NOUNS[b[7] % len(_HR_NOUNS)]
    suffix = _HR_SUFFIXES[b[15] % len(_HR_SUFFIXES)]
    return f"{adjective}-{noun}-{suffix}"


async def restore_from_id(installation_uuid: str) -> Optional[dict]:
    """Gendan gemt konfiguration fra TEO API (kun Self-Hosted, wizard trin 0).

    Kalder ``GET /v1/config?id={uuid}``. Returnerer konfigurationen hvis
    fundet, ellers ``None`` (ukendt ID eller netfejl). Importen er lokal for
    at undgå cirkulær import og for at holde Local-tilstand fri for API-kode.
    """
    if not is_valid_uuid(installation_uuid):
        _LOGGER.warning("restore_from_id: ugyldigt UUID-format")
        return None

    from .teo_api_client import TEOAPIClient

    client = TEOAPIClient()
    try:
        result = await client.get_config(installation_uuid)
    except Exception as err:  # noqa: BLE001 — gendannelse må aldrig kaste videre
        _LOGGER.warning("Kunne ikke gendanne fra TEO API: %s", err)
        return None
    finally:
        await client.close()

    if result and result.get("found"):
        return result.get("config")
    return None

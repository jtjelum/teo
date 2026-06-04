"""Tosproglig tekst-arkitektur — spec §9.
Al brugervendt tekst (wizard, dashboard, log, notifikationer) hentes herfra,
aldrig hardkodet i Python eller YAML (designprincip #7).
    from .translations import get_string
    msg = get_string("reasoning.battery_charge_grid", language="da",
                     price=107, future_price=175, timerange="17:00-03:30",
                     net=5.37, degradation=0.34)
Nye sprog tilføjes ved at lægge en ny ``<lang>.json`` i denne mappe — ingen
kodeændringer kræves.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)
_DEFAULT_LANGUAGE = "da"
_THIS_DIR = Path(__file__).parent

# Pre-load alle sprogfiler ved modul-load (ikke inde i event loop).
_LANGUAGE_CACHE: dict[str, dict[str, Any]] = {}

def _preload_languages() -> None:
    """Indlæs alle tilgængelige sprogfiler ved modul-load."""
    for path in _THIS_DIR.glob("*.json"):
        lang = path.stem
        try:
            _LANGUAGE_CACHE[lang] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke indlæse sprogfil %s: %s", path, err)

_preload_languages()


def _load_language(language: str) -> dict[str, Any]:
    """Hent cachet sprogfil. Falder tilbage til dansk ved ukendt sprog."""
    if language in _LANGUAGE_CACHE:
        return _LANGUAGE_CACHE[language]
    if language != _DEFAULT_LANGUAGE and _DEFAULT_LANGUAGE in _LANGUAGE_CACHE:
        _LOGGER.warning("Sprogfil %s.json mangler — bruger %s", language,
                        _DEFAULT_LANGUAGE)
        return _LANGUAGE_CACHE[_DEFAULT_LANGUAGE]
    raise FileNotFoundError(f"Manglende sprogfil: {_THIS_DIR / language}.json")


def _resolve(data: dict[str, Any], dotted_key: str) -> Any:
    """Slå en punktsepareret nøgle ("a.b.c") op i et indlejret dict."""
    node: Any = data
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def get_string(key: str, language: str = _DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """Hent en oversat streng og indsæt eventuelle ``{placeholder}``-værdier.
    Returnerer ``key`` uændret hvis nøglen ikke findes (gør manglende
    oversættelser synlige i UI frem for at kaste fejl). Manglende
    format-argumenter logges men crasher ikke.
    """
    data = _load_language(language)
    template = _resolve(data, key)
    if template is None and language != _DEFAULT_LANGUAGE:
        template = _resolve(_load_language(_DEFAULT_LANGUAGE), key)
    if template is None:
        _LOGGER.warning("Manglende oversættelsesnøgle: %s (%s)", key, language)
        return key
    if not isinstance(template, str):
        return template  # fx en liste (data_sharing_what_items)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError) as err:
        _LOGGER.warning("Manglende format-argument for %s: %s", key, err)
        return template


def clear_cache() -> None:
    """Ryd sprogcachen (bruges i tests og ved hot-reload af oversættelser)."""
    _LANGUAGE_CACHE.clear()
    _preload_languages()

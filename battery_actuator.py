"""Enphase batteri-aktuering ??? direkte Envoy local-API (kritisk fix 2026-05-30).

Baggrund: HA's ``enphase_envoy``-integration skriver batteri-reserven via
``PUT /admin/lib/tariff``, men pyenphase sender altid ``opt_schedules=true``.
N??r den er sand, lader Enphase' egen schedule-optimering den manuelle reserve
blive overstyret ??? vi bekr??ftede live at en kommanderet reserve p?? 20% IKKE
blev h??ndh??vet (batteriet dr??nede til ~10%). S??tter man ``opt_schedules=false``
f??lger Envoys aktive schedule ??jeblikkeligt den kommanderede reserve.

Dette modul giver derfor TEO en p??lidelig aktueringsvej: det henter den
g??ldende tariff, patcher ``storage_settings`` (altid ``opt_schedules=false``) og
skriver den tilbage. Token + host genbruges fra ``enphase_envoy``-config entry,
s?? der ikke skal vedligeholdes en separat DIY-token.

Kun ??t styrepunkt skrives ad gangen, og kun ved ??NDRING (coordinatoren
husker sidst-anvendte tilstand) ??? vi spammer ikke Envoy med identiske PUTs.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from typing import Any, Optional

from .const import (
    ENPHASE_DOMAIN,
    ENPHASE_MODE_BACKUP,
    ENPHASE_MODE_SAVINGS,
    ENPHASE_MODE_SELF_CONSUMPTION,
    ENVOY_HTTP_TIMEOUT_SEC,
    ENVOY_TARIFF_PATH,
)

_LOGGER = logging.getLogger(__name__)

# Gyldige tariff-modes (TEO bruger prim??rt self-consumption + reserve-styring).
_VALID_MODES = (ENPHASE_MODE_SELF_CONSUMPTION, ENPHASE_MODE_BACKUP,
                ENPHASE_MODE_SAVINGS)


class EnphaseBatteryActuator:
    """Skriver Envoys batteri-tariff direkte med opt_schedules=false."""

    def __init__(self, hass) -> None:
        self.hass = hass

    # -- credentials ----------------------------------------------------
    def _credentials(self) -> Optional[tuple[str, str]]:
        """Hent (host, token) fra den eksisterende enphase_envoy-config entry."""
        entries = self.hass.config_entries.async_entries(ENPHASE_DOMAIN)
        if not entries:
            return None
        data = entries[0].data
        host, token = data.get("host"), data.get("token")
        if host and token:
            return host, token
        return None

    def available(self) -> bool:
        """Returnerer altid True ??? credentials verificeres i apply()."""
        return True

    # -- lavniveau HTTP (k??rer i executor ??? urllib er blokerende) -------
    @staticmethod
    def _ssl_ctx() -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # Envoy bruger selvsigneret cert
        return ctx

    def _get_tariff(self, host: str, token: str) -> dict[str, Any]:
        req = urllib.request.Request(
            f"https://{host}{ENVOY_TARIFF_PATH}",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, context=self._ssl_ctx(),
                                    timeout=ENVOY_HTTP_TIMEOUT_SEC) as resp:
            return json.load(resp)

    def _put_tariff(self, host: str, token: str, tariff: dict[str, Any]
                    ) -> dict[str, Any]:
        body = json.dumps({"tariff": tariff}).encode()
        req = urllib.request.Request(
            f"https://{host}{ENVOY_TARIFF_PATH}", data=body, method="PUT",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=self._ssl_ctx(),
                                    timeout=ENVOY_HTTP_TIMEOUT_SEC) as resp:
            return json.load(resp)

    def _apply_sync(self, reserve_pct: Optional[float], mode: Optional[str],
                    charge_from_grid: Optional[bool]) -> dict[str, Any]:
        creds = self._credentials()
        if creds is None:
            return {"applied": False, "reason": "ingen Envoy-credentials"}
        host, token = creds
        tariff = self._get_tariff(host, token)["tariff"]
        ss = tariff.setdefault("storage_settings", {})

        # KERNEN I FIXET: deaktiv??r Enphase' schedule-optimering, s?? de
        # manuelle v??rdier bliver autoritative.
        ss["opt_schedules"] = False
        if reserve_pct is not None:
            ss["reserved_soc"] = float(reserve_pct)
        if mode is not None and mode in _VALID_MODES:
            ss["mode"] = mode
        if charge_from_grid is not None:
            ss["charge_from_grid"] = bool(charge_from_grid)

        resp = self._put_tariff(host, token, tariff)
        sched = resp.get("schedule", {})
        return {
            "applied": True,
            "reserved_soc": sched.get("reserved_soc"),
            "charge_from_grid": sched.get("charge_from_grid"),
            "mode": sched.get("batt_mode") or sched.get("battery_mode"),
            "opt_schedules": sched.get("opt_schedules"),
        }

    def _current_state_sync(self) -> Optional[dict[str, Any]]:
        creds = self._credentials()
        if creds is None:
            return None
        host, token = creds
        ss = self._get_tariff(host, token).get("tariff", {}).get("storage_settings", {})
        return {
            "reserved_soc": ss.get("reserved_soc"),
            "opt_schedules": ss.get("opt_schedules"),
            "charge_from_grid": ss.get("charge_from_grid"),
            "mode": ss.get("mode"),
        }

    async def current_state(self) -> Optional[dict[str, Any]]:
        """L??s Envoys nuv??rende storage_settings (til drift-detektion)."""
        try:
            return await self.hass.async_add_executor_job(self._current_state_sync)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Kunne ikke l??se Envoy-tariff: %s", err)
            return None

    # -- offentligt API -------------------------------------------------
    async def apply(self, *, reserve_pct: Optional[float] = None,
                    mode: Optional[str] = None,
                    charge_from_grid: Optional[bool] = None) -> dict[str, Any]:
        """Anvend reserve/mode/charge_from_grid p?? Envoy (opt_schedules=false).

        Returnerer Envoys faktiske schedule-v??rdier efter skrivning, s?? kalderen
        kan verificere at kommandoen blev h??ndh??vet.
        """
        try:
            result = await self.hass.async_add_executor_job(
                self._apply_sync, reserve_pct, mode, charge_from_grid)
            if result.get("applied"):
                _LOGGER.info(
                    "Batteri-aktuering: reserve=%s%% mode=%s grid=%s (opt_schedules=%s)",
                    result.get("reserved_soc"), result.get("mode"),
                    result.get("charge_from_grid"), result.get("opt_schedules"))
            return result
        except Exception as err:  # noqa: BLE001 ??? aktuering m?? aldrig v??lte drift
            _LOGGER.warning("Batteri-aktuering fejlede: %s", err)
            return {"applied": False, "reason": str(err)}

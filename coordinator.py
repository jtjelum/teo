"""DataUpdateCoordinator ??? TEO's nervecenter.

Henter live-data (priser, sol, batteri-SOC, forbrug), k??rer optimeringen p?? de
planlagte tidspunkter (kl. 13:00 + 23:00) og falder tilbage til regelmotoren
hvis LP-optimeringen ikke kan l??ses (designprincip #6). Hver beslutning skrives
til beslutningsloggen med tosproget begrundelse (designprincip #3).

Coordinatoren kender ikke konkrete enheder direkte ??? den arbejder mod de
HA-entiteter som enhedsintegrationerne (integrations/) eksponerer, s?? kernen
forbliver enhedsuafh??ngig (designprincip #4).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import config_store, fallback, forecast, holiday_calendar, optimizer, solar_forecast
from .anomaly_detector import profile_for
from .const import (
    ACTION_BATTERY_CHARGE_GRID,
    ACTION_BATTERY_CHARGE_SOLAR,
    ACTUATION_CHECK_INTERVAL_SEC,
    ALGORITHM_VERSION,
    CONF_AREA,
    CONF_CHARGE_FROM_GRID_ALLOWED,
    CONF_CONTROL,
    CONF_MIN_SOC_PCT,
    CONF_SELL_AT_NEGATIVE_PRICE,
    DEFAULT_CHARGE_FROM_GRID_ALLOWED,
    DEFAULT_SELL_AT_NEGATIVE_PRICE,
    CONF_BATTERY,
    CONF_CHARGE_FROM_GRID_BELOW_ORE,
    CONF_DEGRADATION_COST,
    CONF_EV_PROTECTION_SOC_PCT,
    CONF_GRID,
    CONF_GRID_METER,
    CONF_ID,
    CONF_INSTALLATION,
    CONF_MQTT_TOPIC,
    CONF_LANGUAGE,
    CONF_MIN_SOC_PCT,
    CONF_MODE,
    CONF_OPTIMISATION,
    CONF_USE_BATTERY_ABOVE_ORE,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_BATTERY_MAX_CHARGE_KW,
    DEFAULT_BATTERY_MAX_DISCHARGE_KW,
    DEFAULT_BATTERY_MAX_SOC_PCT,
    DEFAULT_BATTERY_MIN_SOC_PCT,
    DEFAULT_CHARGE_EFFICIENCY,
    DEFAULT_CHARGE_FROM_GRID_BELOW_ORE,
    DEFAULT_DEGRADATION_COST_DKK_PER_KWH,
    DEFAULT_DISCHARGE_EFFICIENCY,
    DEFAULT_EV_PROTECTION_SOC_PCT,
    DEFAULT_GRID_AREA,
    DEFAULT_LANGUAGE,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_NETWORK_TARIFF_ORE,
    DEFAULT_OPTIMISATION_HORIZON_HOURS,
    DEFAULT_RUN_AT_HOURS,
    DEFAULT_SOLAR_UNCERTAINTY_FACTOR,
    DEFAULT_UPDATE_INTERVAL_SEC,
    DEFAULT_USE_BATTERY_ABOVE_ORE,
    DOMAIN,
    ENPHASE_MODE_SELF_CONSUMPTION,
    EVENING_PEAK_START_HOUR,
    MODE_LOCAL,
    RESERVE_DRIFT_TOLERANCE_PCT,
)
from .decision_log import DecisionLog
from .translations import get_string

_LOGGER = logging.getLogger(__name__)


@dataclass
class TEOConfig:
    """Indl??st brugerkonfiguration (teo_config.yaml + config entry)."""

    installation_id: str = ""
    mode: str = MODE_LOCAL
    language: str = DEFAULT_LANGUAGE
    grid_area: str = DEFAULT_GRID_AREA
    min_soc_pct: float = DEFAULT_BATTERY_MIN_SOC_PCT
    ev_protection_soc_pct: float = DEFAULT_EV_PROTECTION_SOC_PCT
    charge_from_grid_below_ore: float = DEFAULT_CHARGE_FROM_GRID_BELOW_ORE
    use_battery_above_ore: float = DEFAULT_USE_BATTERY_ABOVE_ORE
    degradation_cost: float = DEFAULT_DEGRADATION_COST_DKK_PER_KWH
    run_at_hours: tuple[int, ...] = DEFAULT_RUN_AT_HOURS
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TEOConfig":
        inst = data.get(CONF_INSTALLATION, {})
        grid = data.get(CONF_GRID, {})
        bat = data.get(CONF_BATTERY, {})
        opt = data.get(CONF_OPTIMISATION, {})
        return cls(
            installation_id=inst.get(CONF_ID, ""),
            mode=inst.get(CONF_MODE, MODE_LOCAL),
            language=inst.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            grid_area=grid.get(CONF_AREA, DEFAULT_GRID_AREA),
            min_soc_pct=bat.get(CONF_MIN_SOC_PCT, DEFAULT_BATTERY_MIN_SOC_PCT),
            ev_protection_soc_pct=bat.get(
                CONF_EV_PROTECTION_SOC_PCT, DEFAULT_EV_PROTECTION_SOC_PCT),
            charge_from_grid_below_ore=opt.get(
                CONF_CHARGE_FROM_GRID_BELOW_ORE, DEFAULT_CHARGE_FROM_GRID_BELOW_ORE),
            use_battery_above_ore=opt.get(
                CONF_USE_BATTERY_ABOVE_ORE, DEFAULT_USE_BATTERY_ABOVE_ORE),
            degradation_cost=bat.get(
                CONF_DEGRADATION_COST, DEFAULT_DEGRADATION_COST_DKK_PER_KWH),
            run_at_hours=tuple(opt.get("run_at_hours", DEFAULT_RUN_AT_HOURS)),
            raw=data,
        )


class TEODataUpdateCoordinator(DataUpdateCoordinator):
    """Samler data, k??rer optimering/fallback og f??rer beslutningslog."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL_SEC),
        )
        self.entry = entry
        self.config = TEOConfig()
        self.decision_log: Optional[DecisionLog] = None
        self.last_plan: list[dict[str, Any]] = []
        self.last_summary: dict[str, Any] = {}
        self.last_solver_status: Optional[str] = None
        self.fallback_active: bool = False
        # Data Commons (DEL 2/3): seneste l??rings- og prisanalyse-resultater.
        self.data_collector: Any = None
        self.last_learning_summary: dict[str, Any] = {}
        self.last_price_analysis: dict[str, Any] = {}
        # Besparelsesberegning (DEL 4): {"today": {...}, "month": {...}}.
        self.cost_summary: dict[str, Any] = {}
        # Seneste loggede beslutning med klartekst-felter (DEL 4).
        self.last_decision: dict[str, Any] = {}
        # Batteri-aktuering (Enphase tariff, opt_schedules=false).
        self._actuator: Any = None
        self._last_actuation: Optional[tuple] = None
        self._last_actuation_check_ts: Optional[datetime] = None
        self.last_actuation: dict[str, Any] = {}
        # Manuel "pause al automatik"-kontakt (dashboard fane 5). N??r False
        # beregner TEO stadig en plan, men anvender ikke styring p?? enheder.
        self.automation_enabled: bool = True
        # Bruger-toggles (GUI) der virker som H??RDE LP-begr??nsninger (DEL: GUI).
        self.allow_negative_export: bool = DEFAULT_SELL_AT_NEGATIVE_PRICE
        self.allow_grid_charge: bool = DEFAULT_CHARGE_FROM_GRID_ALLOWED
        self._last_optimisation_hour: Optional[int] = None
        # (action_type, fallback_active) for sidste loggede beslutning.
        self._last_logged_action_type: Optional[tuple[str, bool]] = None
        self._config_path = str(Path(CONFIG_DIR) / CONFIG_FILE)
        # Seneste neteffekt fra AMS-readeren (kW, +import/???eksport) via MQTT-push.
        self._ams_grid_kw: Optional[float] = None
        self._ams_unsub = None
        # Brugerindstillinger (indl??ses fra teo_user_settings.yaml ved opstart)
        self._user_reserve_soc: Optional[float] = None
        self._user_charge_from_grid: Optional[bool] = None
        self._user_ev_solar_net_only: Optional[bool] = None

    # -- ops??tning ------------------------------------------------------
    async def _async_setup(self) -> None:
        """Engangsops??tning: indl??s konfig + ??bn beslutningslog."""
        data = await self.hass.async_add_executor_job(self._load_config_file)
        merged = {**data, **dict(self.entry.data)} if data else dict(self.entry.data)
        self.config = TEOConfig.from_dict(merged or {})

        # Indl??s persistente brugerindstillinger fra teo_user_settings.yaml.
        # Lazy loading ??? fejl m?? ALDRIG nedl??gge TEO-integrationen.
        await self._load_user_settings()

        self.decision_log = await self.hass.async_add_executor_job(DecisionLog)
        from .battery_actuator import EnphaseBatteryActuator
        self._actuator = EnphaseBatteryActuator(self.hass)
        await self._subscribe_ams()

    async def _load_user_settings(self) -> None:
        """Indl??s persistente brugerindstillinger. Crasher aldrig."""
        try:
            from . import user_settings
            settings = await self.hass.async_add_executor_job(user_settings.load)

            # S??t alle 6 indstillinger til gemte v??rdier (eller defaults)
            from .const import (
                USER_SETTING_MIN_SOC,
                USER_SETTING_RESERVE_SOC,
                USER_SETTING_CHARGE_FROM_GRID,
                USER_SETTING_SELL_AT_NEGATIVE,
                USER_SETTING_GRID_CHARGE_ALLOWED,
                USER_SETTING_EV_SOLAR_NET_ONLY,
            )

            # Minimum SOC (bruges af LP-optimizer)
            min_soc = settings.get(USER_SETTING_MIN_SOC)
            if min_soc is not None:
                self.config.min_soc_pct = float(min_soc)
                # Opdat??r ogs?? raw config s?? det er konsistent
                self.config.raw.setdefault(CONF_BATTERY, {})[CONF_MIN_SOC_PCT] = float(min_soc)

            # Reserve SOC (til Enphase battery_actuator ??? gemmes i last_actuation)
            # Bem??rk: denne v??rdi bruges f??rst n??r manual_actuate kaldes f??rste gang
            self._user_reserve_soc = settings.get(USER_SETTING_RESERVE_SOC)

            # Charge from grid switch (manuel netladning)
            self._user_charge_from_grid = settings.get(USER_SETTING_CHARGE_FROM_GRID)

            # LP-toggles (h??rde begr??nsninger i optimizer)
            self.allow_negative_export = bool(settings.get(USER_SETTING_SELL_AT_NEGATIVE))
            self.allow_grid_charge = bool(settings.get(USER_SETTING_GRID_CHARGE_ALLOWED))

            # EV solar+net only (til fremtidig EV-integration)
            self._user_ev_solar_net_only = settings.get(USER_SETTING_EV_SOLAR_NET_ONLY)

            _LOGGER.info("Indl??ste brugerindstillinger: min_soc=%s, reserve=%s, "
                        "sell_negative=%s, grid_charge_allowed=%s",
                        self.config.min_soc_pct, self._user_reserve_soc,
                        self.allow_negative_export, self.allow_grid_charge)
        except Exception as err:  # noqa: BLE001 ??? graceful degradation
            _LOGGER.warning("Kunne ikke indl??se brugerindstillinger: %s ??? "
                          "bruger defaults", err)

    async def _subscribe_ams(self) -> None:
        """Abonn??r p?? AMS-readerens MQTT-topic for realtids-neteffekt.

        Readeren udsender r?? JSON (felt ``data.P`` = netimport W, ``data.PO`` =
        eksport W) ??? den opretter ingen HA-entitet selv, s?? TEO lytter direkte.
        """
        topic = (self.config.raw.get(CONF_GRID_METER, {}) or {}).get(
            CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC)
        try:
            from homeassistant.components import mqtt
            self._ams_unsub = await mqtt.async_subscribe(
                self.hass, topic, self._on_ams_message)
            _LOGGER.info("Abonnerer p?? AMS-topic '%s'", topic)
        except Exception as err:  # noqa: BLE001 ??? MQTT evt. ikke klar endnu
            _LOGGER.warning("Kunne ikke abonnere p?? AMS-topic: %s", err)

    @callback
    def _on_ams_message(self, msg) -> None:  # noqa: ANN001
        """Parse AMS-payload og gem seneste neteffekt (kW, +import/???eksport)."""
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        src = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        imp = self._coerce_float(src.get("P"))
        exp = self._coerce_float(src.get("PO")) or 0.0
        if imp is not None:
            self._ams_grid_kw = round((imp - exp) / 1000.0, 3)

    def _load_config_file(self) -> dict[str, Any]:
        path = Path(self._config_path)
        if not path.exists():
            return {}
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # -- opdateringscyklus ---------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        """Kaldes hvert interval. Henter snapshot og k??rer optimering ved behov."""
        if self.decision_log is None:
            await self._async_setup()

        snapshot = await self._collect_snapshot()

        now = datetime.now()
        # K??r den (dyre) LP-optimering n??r timen skifter, hvis vi endnu ikke
        # har en plan, eller mens vi er i fallback (bliv ved at fors??ge at
        # komme tilbage til optimering). Lykkes den ikke, bruges fallback.
        if (now.hour != self._last_optimisation_hour
                or not self.last_plan or self.fallback_active):
            self._last_optimisation_hour = now.hour
            lp_ok = await self._try_lp(snapshot, now)
            self.fallback_active = not lp_ok

        if self.fallback_active:
            self._apply_fallback(snapshot, now)

        await self._log_if_changed(snapshot, now)
        await self._actuate(snapshot, now)

        return {
            "snapshot": snapshot,
            "plan": self.last_plan,
            "summary": self.last_summary,
            "solver_status": self.last_solver_status,
            "fallback_active": self.fallback_active,
            "algorithm_version": ALGORITHM_VERSION,
            "installation_id": self.config.installation_id,
            "mode": self.config.mode,
            "cost": self.cost_summary,
            "decision": self.last_decision,
            "actuation": self.last_actuation,
        }

    async def _collect_snapshot(self) -> dict[str, Any]:
        """L??s ??jeblikkelige v??rdier fra HA-entiteter (tomt hvis endnu ikke wiret).

        Enhedsintegrationerne (integrations/) opretter entiteterne; her l??ses de
        generisk, s?? kernen ikke afh??nger af en bestemt fabrikat.
        """
        # Nord Pool (HA core): sensor.nord_pool_<zone>_current_price i DKK/kWh.
        # ?? 100 ??? ??re/kWh, som er TEO's interne prisenhed.
        area = self.config.grid_area.lower()
        price_entity = f"sensor.nord_pool_{area}_current_price"

        # Enphase Envoy/Encharge: match p?? device_class og entity-m??nster i stedet
        # for hardkodede ID'er (robust over for serienumre og sprog ??? SOC-
        # entiteterne hedder fx "_batteri" p?? dansk).
        return {
            "price_ore": self._read_state_float(price_entity, scale=100.0),
            "battery_soc_pct": self._aggregate_battery_soc(),
            "battery_power_kw": self._aggregate_battery_power_kw(),
            "solar_kw": self._envoy_power_kw("_current_power_production"),
            "house_kw": self._envoy_power_kw("_current_power_consumption"),
            "ev_power_kw": self._aggregate_easee_power_kw(),
            "grid_power_kw": self._ams_grid_kw,
            "price_entity": price_entity,
            "timestamp": datetime.now().isoformat(),
        }

    def _aggregate_easee_power_kw(self) -> Optional[float]:
        """Samlet EV-ladeeffekt (kW) over alle Easee-ladere.

        Finder Easee-entiteterne via entity-registreringen (sprog-/navne-
        uafh??ngigt) og summerer deres effekt-sensorer.
        """
        try:
            from homeassistant.helpers import entity_registry as er
            reg = er.async_get(self.hass)
        except Exception:  # noqa: BLE001
            return None
        easee_entry_ids = {
            ce.entry_id for ce in self.hass.config_entries.async_entries("easee")
        }
        if not easee_entry_ids:
            return None
        total = 0.0
        found = False
        for ent in reg.entities.values():
            if ent.config_entry_id not in easee_entry_ids:
                continue
            if not ent.entity_id.startswith("sensor."):
                continue
            st = self.hass.states.get(ent.entity_id)
            if st is None or st.attributes.get("device_class") != "power":
                continue
            kw = self._normalise_power_kw(st)
            if kw is not None:
                total += kw
                found = True
        return round(total, 3) if found else None

    # -- afl??sning af HA-entiteter --------------------------------------
    @staticmethod
    def _coerce_float(raw: Any) -> Optional[float]:
        if raw in ("unknown", "unavailable", None, ""):
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    def _read_state_float(self, entity_id: str,
                          scale: float = 1.0) -> Optional[float]:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        val = self._coerce_float(state.state)
        return val * scale if val is not None else None

    def _aggregate_battery_soc(self) -> Optional[float]:
        """Gennemsnitlig SOC p?? tv??rs af alle Encharge-batterier (%)."""
        vals = [
            self._coerce_float(st.state)
            for st in self.hass.states.async_all("sensor")
            if st.entity_id.startswith("sensor.encharge")
            and st.attributes.get("device_class") == "battery"
        ]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _aggregate_battery_power_kw(self) -> Optional[float]:
        """Samlet batterieffekt (kW) summeret over Encharge-enhederne."""
        total = 0.0
        found = False
        for st in self.hass.states.async_all("sensor"):
            if (st.entity_id.startswith("sensor.encharge")
                    and st.attributes.get("device_class") == "power"):
                kw = self._normalise_power_kw(st)
                if kw is not None:
                    total += kw
                    found = True
        return round(total, 3) if found else None

    def _envoy_power_kw(self, suffix: str) -> Optional[float]:
        """Find f??rste sensor.envoy_*<suffix> og return??r effekt i kW."""
        for st in self.hass.states.async_all("sensor"):
            if st.entity_id.startswith("sensor.envoy_") and st.entity_id.endswith(suffix):
                return self._normalise_power_kw(st)
        return None

    def _normalise_power_kw(self, state) -> Optional[float]:
        """Konvert??r en effekt-sensor til kW uanset om enheden er W eller kW."""
        val = self._coerce_float(state.state)
        if val is None:
            return None
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        return round(val / 1000.0, 3) if unit == "w" else round(val, 3)

    async def _try_lp(self, snapshot: dict[str, Any], now: datetime) -> bool:
        """Fors??g fuld LP-optimering. Returnerer True hvis en plan blev lagt."""
        try:
            inputs = await self._build_optimizer_inputs(snapshot)
            result = await self.hass.async_add_executor_job(optimizer.run, inputs)
        except optimizer.OptimizerUnavailable as err:
            # Forventet under opstart (SOC/priser endnu ikke klar) ??? fallback
            # d??kker sikkert, og binary_sensor.teo_fallback_aktiv viser status.
            _LOGGER.debug("LP utilg??ngelig (%s) ??? bruger fallback", err)
            return False
        except Exception as err:  # noqa: BLE001 ??? enhver LP-fejl ??? sikker fallback
            _LOGGER.warning("Uventet LP-fejl (%s) ??? bruger fallback", err)
            return False

        self.last_plan = result.get("plan", [])
        self.last_summary = result.get("summary", {})
        self.last_solver_status = result.get("solver_status")
        _LOGGER.info("LP-optimering OK: %d trin, status=%s",
                     len(self.last_plan), self.last_solver_status)
        return True

    def _apply_fallback(self, snapshot: dict[str, Any], now: datetime) -> None:
        """L??g en sikker, reaktiv fallback-plan (genberegnes hvert interval)."""
        result = self._run_fallback(snapshot, now)
        self.last_plan = result.get("plan", [])
        self.last_summary = result.get("summary", {})
        self.last_solver_status = result.get("solver_status")

    async def _log_if_changed(self, snapshot: dict[str, Any],
                              now: datetime) -> None:
        """Log beslutningen ??? men kun n??r handlingstypen ??NDRER sig.

        Forhindrer log-spam (cyklus hvert 10. sek) og giver en ren tidslinje
        af faktiske ??ndringer i beslutningsloggen.
        """
        if self.decision_log is None or not self.last_plan:
            return
        step = self.last_plan[0]
        action_type = step.get("battery_action_type") or "BATTERY_IDLE"
        # Re-log ogs?? n??r fallback skifter (optimal???n??dplan), selv om
        # handlingstypen er den samme ??? ellers viser klartekst-labelen
        # for??ldet "N??dplan aktiv" efter at optimeringen er kommet sig.
        log_key = (action_type, self.fallback_active)
        if log_key == self._last_logged_action_type:
            return
        self._last_logged_action_type = log_key

        context = {
            "soc_pct": snapshot.get("battery_soc_pct"),
            "price_ore": snapshot.get("price_ore"),
            "fallback": self.fallback_active,
            "solver_used": self.last_solver_status,
        }
        # Klartekst-felter (DEL 4): gyldighed til n??ste hele time, idle-??rsag og
        # en kort beslutningskilde til avancerede brugere.
        valid_until = (now.replace(minute=0, second=0, microsecond=0)
                       + timedelta(hours=1))
        idle_reason = self._idle_reason(snapshot, now)
        source_summary = self._decision_source_summary(snapshot)
        self.last_decision = await self.hass.async_add_executor_job(
            lambda: self.decision_log.log(
                action_type=action_type,
                device="batteri",
                context=context,
                power_kw=step.get("battery_power_kw"),
                timestamp=now,
                language=self.config.language,
                valid_until=valid_until,
                idle_reason=idle_reason,
                decision_source_summary=source_summary,
                price=snapshot.get("price_ore"),
                soc=snapshot.get("battery_soc_pct"),
                threshold=self.config.use_battery_above_ore,
            )
        )

    async def _actuate(self, snapshot: dict[str, Any], now: datetime) -> None:
        """Anvend planens batterihandling p?? Envoy via den p??lidelige tariff-vej.

        Skriver ved ??NDRING af handling, OG gen-h??ndh??ver ved drift: en ekstern
        akt??r (Enphase-cloud/Enlighten) gen-aktiverer opt_schedules ca. hvert 2.
        minut og nulstiller reserven, s?? TEO tjekker tariffen hvert
        ACTUATION_CHECK_INTERVAL_SEC og gen-skriver hvis opt_schedules er flippet
        eller reserven er drevet. Respekterer pause-switchen (automation_enabled).
        Reserven holdes i [min_soc, max_soc]; gulvet beskytter nu reelt mod
        dybafladning fordi vi skriver opt_schedules=false (se battery_actuator).
        """
        if not self.automation_enabled or self._actuator is None:
            return
        if not self.last_plan or not self._actuator.available():
            return

        action = self.last_plan[0].get("battery_action_type") or "BATTERY_IDLE"
        min_soc = float(self.config.min_soc_pct)
        max_soc = float(DEFAULT_BATTERY_MAX_SOC_PCT)

        if action == ACTION_BATTERY_CHARGE_GRID:
            desired = (max_soc, ENPHASE_MODE_SELF_CONSUMPTION, True)  # lad fra net
        elif action == ACTION_BATTERY_CHARGE_SOLAR:
            desired = (min_soc, ENPHASE_MODE_SELF_CONSUMPTION, False)  # kun sol
        else:
            desired = (min_soc, ENPHASE_MODE_SELF_CONSUMPTION, False)  # discharge/idle

        action_changed = desired != self._last_actuation
        due_check = (self._last_actuation_check_ts is None
                     or (now - self._last_actuation_check_ts).total_seconds()
                     >= ACTUATION_CHECK_INTERVAL_SEC)
        if not action_changed and not due_check:
            return

        # Ved u??ndret handling: tjek for drift f??r vi skriver (undg?? write-storm).
        if not action_changed:
            self._last_actuation_check_ts = now
            state = await self._actuator.current_state()
            if state is None:
                return
            rsv = state.get("reserved_soc")
            drifted = (
                state.get("opt_schedules") is not False           # opt re-aktiveret
                or rsv is None
                or abs(float(rsv) - desired[0]) > RESERVE_DRIFT_TOLERANCE_PCT
                or bool(state.get("charge_from_grid")) != desired[2]
            )
            if not drifted:
                return

        result = await self._actuator.apply(
            reserve_pct=desired[0], mode=desired[1], charge_from_grid=desired[2])
        if result.get("applied"):
            self._last_actuation = desired
            self._last_actuation_check_ts = now
            self.last_actuation = {**result, "action": action}

    def _idle_reason(self, snapshot: dict[str, Any], now: datetime) -> str:
        """Udled HVORFOR batteriet holdes i ro (v??lger idle-label, DEL 4.1)."""
        if snapshot.get("price_ore") is None:
            return "no_price"
        soc = snapshot.get("battery_soc_pct")
        if soc is not None and soc >= DEFAULT_BATTERY_MAX_SOC_PCT - 5:
            return "full"
        pa = self.last_price_analysis or {}
        if pa.get("evening_expensive") and now.hour < EVENING_PEAK_START_HOUR:
            return "evening"
        if pa.get("multi_day_wait") or (pa.get("rebound") or {}).get("detected"):
            return "price"
        return "full"

    def _decision_source_summary(self, snapshot: dict[str, Any]) -> str:
        """Kort 'Baseret p??: ???'-linje (DEL 4.4) p?? brugerens sprog."""
        lang = self.config.language
        parts: list[str] = []
        price = snapshot.get("price_ore")
        soc = snapshot.get("battery_soc_pct")
        if price is not None:
            parts.append(get_string("human.source.price", language=lang,
                                    price=round(price)))
        if soc is not None:
            parts.append(get_string("human.source.battery", language=lang,
                                    soc=round(soc)))
        scenario = (self.last_price_analysis or {}).get("day_scenario")
        if scenario:
            parts.append(get_string("human.source.scenario", language=lang,
                                    scenario=scenario))
        prefix = get_string("human.source_prefix", language=lang)
        return f"{prefix} " + " ?? ".join(parts) if parts else prefix

    async def _build_optimizer_inputs(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Byg det fulde LP-input fra Nord Pool-prisserie + batteristatus.

        Forbruger den globale models ``model_calibration`` (DEL 7), n??r den er
        anvendt: prisbuffer pr. time, solfaktor pr. vejrtype og cold-start
        lastprofil. Last-prognosen kommer prim??rt fra den LOKALT l??rte
        familieprofil (family_patterns), med cold-start som fallback.
        Sol-prognose er 0 indtil Solcast wires (punkt 3).
        """
        if snapshot.get("battery_soc_pct") is None:
            raise optimizer.OptimizerUnavailable("ingen batteri-SOC")

        prices = await self._fetch_price_series()
        if len(prices) < 2:
            raise optimizer.OptimizerUnavailable("for kort prisserie")

        capacity = DEFAULT_BATTERY_CAPACITY_KWH
        soc_kwh = snapshot["battery_soc_pct"] / 100.0 * capacity
        min_soc_kwh = self.config.min_soc_pct / 100.0 * capacity
        max_soc_kwh = DEFAULT_BATTERY_MAX_SOC_PCT / 100.0 * capacity
        # Hold start-SOC inden for gr??nserne (numerisk robusthed).
        soc_kwh = min(max(soc_kwh, min_soc_kwh), max_soc_kwh)

        times = sorted(prices)
        house_kw = snapshot.get("house_kw")
        anchor_kw = abs(house_kw) if house_kw is not None else 0.4
        model_cal = self.config.raw.get("model_calibration", {}) or {}

        # Tidskontekst i LOKAL tid (familieprofiler er l??rt p?? lokal ugedag/time).
        from homeassistant.util import dt as dt_util
        contexts: list[tuple[Any, int, int, str]] = []
        local_hour: dict[Any, int] = {}
        for t in times:
            lt = dt_util.as_local(t) if getattr(t, "tzinfo", None) else t
            hc = holiday_calendar.context(lt.date())
            is_hol = (bool(hc["is_public_holiday_dk"])
                      if hc["is_public_holiday_dk"] is not None else None)
            is_sch = (bool(hc["is_school_holiday_dk"])
                      if hc["is_school_holiday_dk"] is not None else None)
            contexts.append((t, lt.weekday(), lt.hour,
                             profile_for(lt.weekday(), is_hol, is_sch)))
            local_hour[t] = lt.hour

        # Last-prognose: lokal familieprofil ??? cold-start ??? fladt.
        load_forecast = await self.hass.async_add_executor_job(
            forecast.build_load_forecast, contexts, model_cal, anchor_kw)

        # Prisbuffer pr. time (risikomargin i usikre timer).
        buffers = model_cal.get("price_uncertainty_buffer") or {}
        spot_prices = {}
        for t in times:
            b = buffers.get(f"{local_hour[t]:02d}")
            spot_prices[t] = (round(prices[t] * (1.0 + float(b)), 2)
                              if b is not None else prices[t])

        # Solfaktor pr. vejrtype (erstatter den globale usikkerhedsfaktor).
        weather = await self.hass.async_add_executor_job(self._current_weather_category)
        solar_factors = model_cal.get("solar_factors") or {}
        unc = float(solar_factors.get(weather, DEFAULT_SOLAR_UNCERTAINTY_FACTOR))

        # (Punkt 3) Solcast-prognose hvis integrationen er til stede; ellers 0.
        solar_p50 = solar_forecast.fetch(self.hass, times)
        if not solar_p50:
            solar_p50 = {t: 0.0 for t in times}

        return {
            "spot_prices": spot_prices,
            "network_tariff_ore": DEFAULT_NETWORK_TARIFF_ORE,
            "battery_capacity_kwh": capacity,
            "battery_soc_kwh": soc_kwh,
            "battery_min_soc_kwh": min_soc_kwh,
            "battery_max_soc_kwh": max_soc_kwh,
            "battery_max_charge_kw": DEFAULT_BATTERY_MAX_CHARGE_KW,
            "battery_max_discharge_kw": DEFAULT_BATTERY_MAX_DISCHARGE_KW,
            "battery_charge_efficiency": DEFAULT_CHARGE_EFFICIENCY,
            "battery_discharge_efficiency": DEFAULT_DISCHARGE_EFFICIENCY,
            "degradation_cost_dkk_per_kwh": self.config.degradation_cost,
            "solar_forecast_p50": solar_p50,
            "solar_uncertainty_factor": unc,
            "load_forecast_kw": load_forecast,
            "timestep_minutes": 60,
            # H??RDE bruger-begr??nsninger (GUI-switches).
            "allow_grid_charge": self.allow_grid_charge,
            "allow_negative_export": self.allow_negative_export,
            # EV-beskyttelse: n??r switch er ON (ev_protection_soc_pct=100)
            # s??ttes ev_max til 0 s?? LP ikke planl??gger EV-ladning.
            "ev_energy_demand_kwh": 0.0,
            "ev_max_power_kw": 0.0 if self.config.ev_protection_soc_pct >= 100 else 7.4,
        }

    # -- GUI-styring (number/switch) ------------------------------------
    async def manual_actuate(self, reserve_pct: Optional[float] = None,
                             charge_from_grid: Optional[bool] = None
                             ) -> dict[str, Any]:
        """Manuel Envoy-skrivning fra dashboardet (reserve / charge-from-grid).

        Skriver via den p??lidelige opt_schedules=false-vej. N??r automatik er
        T??NDT vil TEO's auto-aktuering revurdere ved n??ste cyklus; n??r den er
        SLUKKET persisterer den manuelle indstilling (TEO aktuerer ikke).
        """
        if self._actuator is None or not self._actuator.available():
            return {"applied": False, "reason": "ingen Envoy-aktuator"}
        result = await self._actuator.apply(
            reserve_pct=reserve_pct, mode=ENPHASE_MODE_SELF_CONSUMPTION,
            charge_from_grid=charge_from_grid)
        if result.get("applied"):
            self.last_actuation = {**result, "action": "manual"}
            self._last_actuation = None  # tving auto-revurdering n??ste cyklus
        return result

    async def set_min_soc(self, pct: float) -> None:
        """S??t minimum-SOC: skriv til teo_config.yaml + brug straks i LP."""
        await self.hass.async_add_executor_job(
            config_store.set_value, CONF_BATTERY, CONF_MIN_SOC_PCT, float(pct))
        self.config.min_soc_pct = float(pct)
        self.config.raw.setdefault(CONF_BATTERY, {})[CONF_MIN_SOC_PCT] = float(pct)

    async def set_control(self, *, sell_at_negative: Optional[bool] = None,
                          grid_charge_allowed: Optional[bool] = None) -> None:
        """S??t LP-toggles og persist??r dem i teo_config.yaml under 'control'."""
        if sell_at_negative is not None:
            self.allow_negative_export = bool(sell_at_negative)
            await self.hass.async_add_executor_job(
                config_store.set_value, CONF_CONTROL, CONF_SELL_AT_NEGATIVE_PRICE,
                bool(sell_at_negative))
        if grid_charge_allowed is not None:
            self.allow_grid_charge = bool(grid_charge_allowed)
            await self.hass.async_add_executor_job(
                config_store.set_value, CONF_CONTROL, CONF_CHARGE_FROM_GRID_ALLOWED,
                bool(grid_charge_allowed))

    def _current_weather_category(self) -> Optional[str]:
        """Seneste vejrkategori (til solfaktor-opslag). None hvis ukendt."""
        try:
            if self.data_collector is None:
                return None
            latest = self.data_collector.latest()
            return (latest or {}).get("weather_category")
        except Exception:  # noqa: BLE001
            return None

    async def _fetch_price_series(self) -> dict[datetime, float]:
        """Hent Nord Pool-priser (i dag + i morgen) via integrationens service.

        Returnerer ``{time: ??re/kWh}`` aggregeret til hele timer fra og med den
        aktuelle time, op til optimeringshorisonten. Nord Pool leverer DKK/MWh
        i 15-min opl??sning ??? ??10 = ??re/kWh, derefter timegennemsnit.
        """
        entries = self.hass.config_entries.async_entries("nordpool")
        if not entries:
            return {}
        entry_id = entries[0].entry_id
        area = self.config.grid_area.upper()

        buckets: dict[datetime, list[float]] = {}
        today = date.today()
        for day in (today, today + timedelta(days=1)):
            try:
                resp = await self.hass.services.async_call(
                    "nordpool", "get_prices_for_date",
                    {"config_entry": entry_id, "date": day.isoformat()},
                    blocking=True, return_response=True,
                )
            except Exception as err:  # noqa: BLE001 ??? fx i morgen ikke offentliggjort endnu
                _LOGGER.debug("Nord Pool-priser for %s utilg??ngelige: %s", day, err)
                continue
            for row in (resp or {}).get(area, []) or []:
                try:
                    start = datetime.fromisoformat(row["start"])
                    ore = float(row["price"]) / 10.0   # DKK/MWh ??? ??re/kWh
                except (ValueError, KeyError, TypeError):
                    continue
                hour = start.replace(minute=0, second=0, microsecond=0)
                buckets.setdefault(hour, []).append(ore)

        now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        series = {
            h: round(sum(v) / len(v), 2)
            for h, v in buckets.items() if h >= now_hour
        }
        # Begr??ns til optimeringshorisonten.
        ordered = sorted(series.items())[:DEFAULT_OPTIMISATION_HORIZON_HOURS]
        return dict(ordered)

    def _run_fallback(self, snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
        inputs = fallback.FallbackInputs(
            current_price_ore=snapshot.get("price_ore") or 0.0,
            battery_soc_pct=snapshot.get("battery_soc_pct") or 100.0,
            ev_protection_soc_pct=self.config.ev_protection_soc_pct,
            charge_from_grid_below_ore=self.config.charge_from_grid_below_ore,
            use_battery_above_ore=self.config.use_battery_above_ore,
            min_soc_pct=self.config.min_soc_pct,
        )
        decision = fallback.run_fallback(inputs)
        return fallback.build_fallback_result(decision, now)

    async def _log_current_decision(self, snapshot: dict[str, Any],
                                    now: datetime) -> None:
        """Skriv den aktuelle beslutning til loggen (korteste vej til transparens)."""
        if self.decision_log is None or not self.last_plan:
            return
        step = self.last_plan[0]
        action_type = step.get("battery_action_type") or "BATTERY_IDLE"
        context = {
            "soc_pct": snapshot.get("battery_soc_pct"),
            "price_ore": snapshot.get("price_ore"),
            "fallback": self.fallback_active,
            "solver_used": self.last_solver_status,
        }
        await self.hass.async_add_executor_job(
            lambda: self.decision_log.log(
                action_type=action_type,
                device="batteri",
                context=context,
                power_kw=step.get("battery_power_kw"),
                timestamp=now,
                price=snapshot.get("price_ore"),
                soc=snapshot.get("battery_soc_pct"),
                threshold=self.config.use_battery_above_ore,
            )
        )

    async def async_shutdown(self) -> None:
        """Ryd op ved afmontering."""
        if self._ams_unsub is not None:
            self._ams_unsub()
            self._ams_unsub = None
        await super().async_shutdown()

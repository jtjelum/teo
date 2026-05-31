"""TEO — Tjelums Energy Optimisation.

Hoved-entrypoint for Home Assistant-integrationen. Opsætter
DataUpdateCoordinator, indlæser brugerkonfiguration og videresender
platforme. Selve beslutningslogikken ligger i coordinator.py og optimizer.py.

Designprincip #1 (Lokalt first): Intet net-kald foretages her ud over det
coordinatoren selv styrer (Nord Pool/Solcast). I Local-tilstand sker ingen
kommunikation med TEO API.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)

from .const import (
    DATA_COLLECTION_INTERVAL_MINUTES,
    DOMAIN,
    SERVICE_APPLY_MODEL,
    SERVICE_CLOUD_UPLOAD,
    SERVICE_COLLECT_DATA,
    SERVICE_DAILY_CALIBRATION,
    SERVICE_DECISION_ANALYSIS,
    SERVICE_MODEL_UPDATE,
    SERVICE_PRICE_ANALYSIS,
)
from .cloud_uploader import CloudUploader
from .coordinator import TEODataUpdateCoordinator
from .cost_calculator import CostCalculator
from .data_collector import DataCollector
from .family_learner import FamilyLearner
from .model_updater import ModelUpdater

_LOGGER = logging.getLogger(__name__)

# Platforme TEO eksponerer i HA. Sensorer/numre/switches kommer fra
# coordinatorens data; selve enhedsstyringen sker via integrations/.
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,  # min-SOC + Enphase-reserve (config write-back på plads)
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sæt en TEO-konfigurationsindgang op."""
    coordinator = TEODataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Registrer logsystem services og API (lazy-loaded)
    try:
        from .analyse_decisions import async_setup_decision_analysis_service
        await async_setup_decision_analysis_service(hass)
    except Exception as err:
        _LOGGER.warning("Logsystem service registrering fejlede: %s", err)

    try:
        from .api import async_setup_api
        await async_setup_api(hass)
    except Exception as err:
        _LOGGER.warning("Logsystem API registrering fejlede: %s", err)

    await _async_setup_data_commons(hass, entry, coordinator)

    _LOGGER.info(
        "TEO opsat (tilstand=%s, zone=%s)",
        coordinator.config.mode,
        coordinator.config.grid_area,
    )
    return True


async def _async_setup_data_commons(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: TEODataUpdateCoordinator,
) -> None:
    """Sæt 5-minutters dataindsamling op (Data Commons, DEL 1).

    Indsamlingen er bevidst afkoblet fra optimeringscyklussen: den kører på sin
    egen timer og er pakket i try/except, så en fejl i dataopsamlingen aldrig
    kan påvirke driften (designprincip #2 — aldrig blokér optimering).
    """
    collector = await hass.async_add_executor_job(DataCollector)
    coordinator.data_collector = collector
    cost_calc = CostCalculator()

    async def _collect(now=None) -> None:
        try:
            await collector.collect(hass, coordinator)
        except Exception as err:  # noqa: BLE001 — sidste værn omkring timeren
            _LOGGER.debug("Dataindsamling fejlede (ignoreret): %s", err)
        # Genberegn besparelse (dag + måned) så økonomi-sensorerne er live.
        try:
            coordinator.cost_summary = await hass.async_add_executor_job(
                cost_calc.run, coordinator.config.grid_area, None,
                collector.upsert_daily,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Besparelsesberegning fejlede (ignoreret): %s", err)

    entry.async_on_unload(
        async_track_time_interval(
            hass, _collect, timedelta(minutes=DATA_COLLECTION_INTERVAL_MINUTES)
        )
    )

    async def _handle_collect_service(call: ServiceCall) -> None:
        await _collect()

    async def _handle_daily_calibration(call: ServiceCall) -> None:
        """Genberegn familieprofiler/sæsonmønstre (DEL 2, dagligt kl. 02:00)."""
        from .version import bump_algorithm_version
        try:
            learner = FamilyLearner()
            summary = await hass.async_add_executor_job(learner.run)
            coordinator.last_learning_summary = summary
            
            # Bump algorithm version ved succesfuld kalibrering
            if "error" not in summary:
                new_version = await hass.async_add_executor_job(bump_algorithm_version)
                coordinator.algorithm_version = new_version  # Opdater coordinator cache
                _LOGGER.info("Familielæring kørt: %s (version bumped til %s)", summary, new_version)
            else:
                _LOGGER.warning("Familielæring fejlede: %s (version ikke bumped)", summary.get("error"))
        except Exception as err:  # noqa: BLE001 — læring må aldrig vælte drift
            _LOGGER.warning("Familielæring fejlede: %s (version ikke bumped)", err)

    async def _handle_price_analysis(call: ServiceCall) -> None:
        """Analysér morgendagens priser (DEL 3, dagligt kl. 13:30)."""
        from datetime import timedelta as _td

        from homeassistant.util import dt as dt_util

        from .price_analyzer import PriceAnalyzer
        try:
            prices = await coordinator._fetch_price_series()
            if not prices:
                _LOGGER.debug("Prisanalyse: ingen priser tilgængelige endnu")
                return
            today = dt_util.now().date()
            tomorrow = today + _td(days=1)
            has_tomorrow = any(dt.date() == tomorrow for dt in prices)
            planning = tomorrow if has_tomorrow else today

            analyzer = PriceAnalyzer(
                coordinator.config.charge_from_grid_below_ore,
                coordinator.config.use_battery_above_ore,
            )
            analysis = analyzer.analyze(prices, planning, today_date=today)
            coordinator.last_price_analysis = analysis

            if analysis.get("available"):
                await hass.async_add_executor_job(
                    collector.upsert_daily,
                    planning.isoformat(),
                    coordinator.config.grid_area,
                    {
                        "avg_nordpool_price_ore": analysis.get("day_avg_ore"),
                        "min_nordpool_price_ore": analysis.get("day_min_ore"),
                        "max_nordpool_price_ore": analysis.get("day_max_ore"),
                        "nordpool_volatility_ore": analysis.get("volatility_ore"),
                        "day_scenario": analysis.get("day_scenario"),
                    },
                )
            _LOGGER.info("Prisanalyse (%s): scenarie=%s, aften-index=%s",
                         planning, analysis.get("day_scenario"),
                         analysis.get("evening_index"))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Prisanalyse fejlede: %s", err)

    async def _handle_cloud_upload(call: ServiceCall) -> None:
        """Anonym døgn-upload (DEL 6, kl. 04:30) — no-op uden opt-in."""
        try:
            uploader = CloudUploader(coordinator.config.raw)
            result = await uploader.upload(
                hass, coordinator.config.installation_id, coordinator.config.mode)
            _LOGGER.info("Cloud-upload: %s", result)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Cloud-upload fejlede: %s", err)

    async def _handle_model_update(call: ServiceCall) -> None:
        """Hent global model (DEL 7.4, kl. 04:00) — anvendes først ved bekræftelse."""
        try:
            result = await ModelUpdater().fetch_latest(hass)
            _LOGGER.info("Modeltjek: %s", result)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Modeltjek fejlede: %s", err)

    async def _handle_apply_model(call: ServiceCall) -> None:
        """Brugerbekræftet anvendelse af den afventende globale model."""
        try:
            result = await hass.async_add_executor_job(
                ModelUpdater().apply_pending, coordinator.config.grid_area)
            _LOGGER.info("Model anvendt: %s", result)
            if result.get("applied"):
                await hass.config_entries.async_reload(entry.entry_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Modelanvendelse fejlede: %s", err)


    # Services så automations (DEL 6) og Udviklerværktøjer kan trigge manuelt.
    hass.services.async_register(DOMAIN, SERVICE_COLLECT_DATA, _handle_collect_service)
    hass.services.async_register(DOMAIN, SERVICE_DAILY_CALIBRATION, _handle_daily_calibration)
    hass.services.async_register(DOMAIN, SERVICE_PRICE_ANALYSIS, _handle_price_analysis)
    hass.services.async_register(DOMAIN, SERVICE_CLOUD_UPLOAD, _handle_cloud_upload)
    hass.services.async_register(DOMAIN, SERVICE_MODEL_UPDATE, _handle_model_update)
    hass.services.async_register(DOMAIN, SERVICE_APPLY_MODEL, _handle_apply_model)

    # Daglige batch-jobs skemalægges i koden (DEL 6) frem for i bruger-YAML, så
    # datapipelinen er robust og kører selv uden automations (princip #2). De
    # tilsvarende YAML-skabeloner ligger i teo_automations/ som redigerbar
    # reference. Tidspunkter: kalibrering 02:00, prisanalyse 13:30 (~30 min
    # efter Nord Pool), modeltjek 04:00, cloud-upload 04:30.
    def _daily(handler, hour: int, minute: int):
        async def _tick(now) -> None:
            await handler(None)
        return async_track_time_change(hass, _tick, hour=hour, minute=minute, second=0)

    for unsub in (
        _daily(_handle_daily_calibration, 2, 0),
        _daily(_handle_price_analysis, 13, 30),
        _daily(_handle_model_update, 4, 0),
        _daily(_handle_cloud_upload, 4, 30),
    ):
        entry.async_on_unload(unsub)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Afmontér en TEO-konfigurationsindgang."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TEODataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Genindlæs integrationen når brugeren ændrer indstillinger."""
    await hass.config_entries.async_reload(entry.entry_id)

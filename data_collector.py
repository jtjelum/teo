"""Data Commons — lokal dataindsamling (spec DEL 1).

Gemmer ét fuldt målepunkt hvert 5. minut i ``/config/teo_data.db``: energi
(Envoy + AMS), vejr (Open-Meteo), sol-geometri (lokalt beregnet), tidskontekst
og TEO's egen beslutning. Råstoffet til familielæring, prisarbitrage og
besparelsesberegning bygges ovenpå denne tabel.

Designprincipper der styrer modulet:
* **#1 Indsaml alt, analysér bagefter** — vi gemmer hver kolonne uden at
  forudsætte hvilke mønstre der findes. Manglende kilder skrives som NULL.
* **#2 Aldrig blokér optimering** — indsamling er asynkron og pakket i
  try/except; en fejl logges til ``data_commons.log`` og forbruger intet fra
  driftscyklussen. Måledatabasen er fysisk adskilt fra beslutningsloggen.

Selve skedulering/serviceregistrering ligger i ``__init__.py``; her bor skemaet,
række-opbygningen og de synkrone SQLite-skrivninger.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from . import holiday_calendar, sun_calculator
from .const import (
    CONFIG_DIR,
    DATA_COMMONS_LOG_FILE,
    DATA_DB_FILE,
    DATA_LOG_DIR,
    MEASUREMENTS_RETENTION_DAYS,
)
from .weather_fetcher import WeatherFetcher

_LOGGER = logging.getLogger(__name__)

# Dedikeret fil-logger til hele Data Commons-rørledningen (spec DEL 10:
# "Log alle fejl i /config/teo_logs/data_commons.log").
_COMMONS_LOGGER_NAME = "custom_components.teo.data_commons"


def get_commons_logger(config_dir: str = CONFIG_DIR) -> logging.Logger:
    """Hent (og opret ved første kald) fil-loggeren for Data Commons."""
    logger = logging.getLogger(_COMMONS_LOGGER_NAME)
    if logger.handlers:
        return logger
    try:
        log_dir = Path(config_dir) / DATA_LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / DATA_COMMONS_LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    except Exception as err:  # noqa: BLE001 — fald tilbage til HA-loggen
        _LOGGER.warning("Kunne ikke oprette data_commons.log: %s", err)
    return logger


# ---------------------------------------------------------------------------
# Databaseskema — alle seks tabeller fra DEL 1 (idempotent)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                  TEXT NOT NULL,
    -- Energi
    solar_production_kw        REAL,
    solar_l1_kw                REAL,
    solar_l2_kw                REAL,
    solar_l3_kw                REAL,
    house_consumption_kw       REAL,
    house_l1_kw                REAL,
    house_l2_kw                REAL,
    house_l3_kw                REAL,
    battery_soc_pct            REAL,
    battery_power_kw           REAL,
    battery_reserve_pct        REAL,
    grid_import_kw             REAL,
    grid_export_kw             REAL,
    ev_total_kw                REAL,
    ev_master_kw               REAL,
    ev_slave_kw                REAL,
    nordpool_price_ore         REAL,
    -- Vejr
    temp_outdoor_c             REAL,
    temp_feels_like_c          REAL,
    cloud_cover_pct            REAL,
    precipitation_mm_h         REAL,
    precipitation_type         TEXT,
    wind_speed_ms              REAL,
    wind_direction_deg         REAL,
    wind_gusts_ms              REAL,
    solar_irradiance_wm2       REAL,
    diffuse_irradiance_wm2     REAL,
    uv_index                   REAL,
    visibility_km              REAL,
    humidity_pct               REAL,
    pressure_hpa               REAL,
    weather_category           TEXT,
    -- Sol-geometri
    sun_azimuth_deg            REAL,
    sun_elevation_deg          REAL,
    is_daylight                INTEGER,
    minutes_since_sunrise      INTEGER,
    minutes_to_sunset          INTEGER,
    day_length_minutes         INTEGER,
    days_since_summer_solstice INTEGER,
    solar_noon_elevation_deg   REAL,
    -- Tidskontekst
    weekday                    INTEGER,
    hour                       INTEGER,
    month                      INTEGER,
    week_of_year               INTEGER,
    quarter                    INTEGER,
    is_weekday                 INTEGER,
    is_weekend                 INTEGER,
    is_public_holiday_dk       INTEGER,
    is_school_holiday_dk       INTEGER,
    days_until_christmas       INTEGER,
    days_until_easter          INTEGER,
    is_summer_time             INTEGER,
    -- TEO-beslutninger
    teo_action                 TEXT,
    teo_human_label            TEXT,
    teo_human_explanation      TEXT,
    teo_valid_until            TEXT,
    teo_reasoning_short        TEXT,
    optimizer_ran              INTEGER,
    fallback_active            INTEGER,
    solcast_forecast_kwh       REAL,
    load_forecast_kwh          REAL,
    planned_battery_action     TEXT,
    nordpool_tomorrow_avg_ore  REAL,
    nordpool_next_6h_avg_ore   REAL
);
CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements (timestamp);

CREATE TABLE IF NOT EXISTS daily_summary (
    date                       TEXT NOT NULL,
    zone                       TEXT,
    solar_total_kwh            REAL,
    grid_import_total_kwh      REAL,
    grid_export_total_kwh      REAL,
    battery_charged_kwh        REAL,
    battery_discharged_kwh     REAL,
    battery_cycles_count       REAL,
    ev_charged_kwh             REAL,
    house_base_kwh             REAL,
    avg_temp_c                 REAL,
    max_temp_c                 REAL,
    min_temp_c                 REAL,
    total_precipitation_mm     REAL,
    avg_cloud_cover_pct        REAL,
    avg_wind_speed_ms          REAL,
    avg_irradiance_wm2         REAL,
    weather_day_type           TEXT,
    estimated_cost_dkk         REAL,
    baseline_cost_dkk          REAL,
    estimated_saving_dkk       REAL,
    avg_nordpool_price_ore     REAL,
    min_nordpool_price_ore     REAL,
    max_nordpool_price_ore     REAL,
    nordpool_volatility_ore    REAL,
    solcast_forecast_kwh       REAL,
    solcast_actual_kwh         REAL,
    solcast_error_pct          REAL,
    optimizer_runs_count       INTEGER,
    fallback_activations_count INTEGER,
    anomaly_detected           INTEGER,
    anomaly_reason             TEXT,
    day_scenario               TEXT,
    PRIMARY KEY (date, zone)
);

CREATE TABLE IF NOT EXISTS calibration_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp          TEXT NOT NULL,
    calibration_type   TEXT,
    parameter_changed  TEXT,
    old_value          TEXT,
    new_value          TEXT,
    reason             TEXT,
    data_points_used   INTEGER,
    confidence         REAL,
    source             TEXT
);

CREATE TABLE IF NOT EXISTS decision_outcomes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_timestamp  TEXT NOT NULL,
    action_taken        TEXT,
    planned_saving_dkk  REAL,
    actual_saving_dkk   REAL,
    price_forecast_ore  REAL,
    actual_price_ore    REAL,
    solar_forecast_kwh  REAL,
    actual_solar_kwh    REAL,
    load_forecast_kwh   REAL,
    actual_load_kwh     REAL,
    decision_quality    TEXT,
    quality_reason      TEXT
);

CREATE TABLE IF NOT EXISTS family_patterns (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type       TEXT,
    context_key        TEXT,
    avg_consumption_kw REAL,
    std_consumption_kw REAL,
    sample_count       INTEGER,
    confidence         REAL,
    last_updated       TEXT
);
"""

# Kolonner i measurements i insert-rækkefølge (uden id). Holdes adskilt fra
# skemaet så row-builderen og INSERT altid er enige.
MEASUREMENT_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "solar_production_kw", "solar_l1_kw", "solar_l2_kw", "solar_l3_kw",
    "house_consumption_kw", "house_l1_kw", "house_l2_kw", "house_l3_kw",
    "battery_soc_pct", "battery_power_kw", "battery_reserve_pct",
    "grid_import_kw", "grid_export_kw",
    "ev_total_kw", "ev_master_kw", "ev_slave_kw",
    "nordpool_price_ore",
    "temp_outdoor_c", "temp_feels_like_c", "cloud_cover_pct",
    "precipitation_mm_h", "precipitation_type",
    "wind_speed_ms", "wind_direction_deg", "wind_gusts_ms",
    "solar_irradiance_wm2", "diffuse_irradiance_wm2", "uv_index",
    "visibility_km", "humidity_pct", "pressure_hpa", "weather_category",
    "sun_azimuth_deg", "sun_elevation_deg", "is_daylight",
    "minutes_since_sunrise", "minutes_to_sunset", "day_length_minutes",
    "days_since_summer_solstice", "solar_noon_elevation_deg",
    "weekday", "hour", "month", "week_of_year", "quarter",
    "is_weekday", "is_weekend",
    "is_public_holiday_dk", "is_school_holiday_dk",
    "days_until_christmas", "days_until_easter", "is_summer_time",
    "teo_action", "teo_human_label", "teo_human_explanation",
    "teo_valid_until", "teo_reasoning_short",
    "optimizer_ran", "fallback_active",
    "solcast_forecast_kwh", "load_forecast_kwh", "planned_battery_action",
    "nordpool_tomorrow_avg_ore", "nordpool_next_6h_avg_ore",
)


def _as_int_bool(value: Any) -> Optional[int]:
    """Gem bool som 0/1, men bevar None (ukendt ≠ falsk)."""
    if value is None:
        return None
    return 1 if value else 0


def _split_grid(grid_kw: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """Del signeret neteffekt (+import/−eksport) i (import_kw, export_kw)."""
    if grid_kw is None:
        return None, None
    if grid_kw >= 0:
        return round(grid_kw, 3), 0.0
    return 0.0, round(-grid_kw, 3)


def time_context(now: datetime) -> dict[str, Any]:
    """Lokal tidskontekst. Helligdags-/skoleferiefelter fyldes i Trin 2."""
    iso = now.isocalendar()
    weekday = now.weekday()  # 0=mandag ... 6=søndag (matcher spec)
    is_weekend = weekday >= 5
    # Dansk sommertid: kun kendt hvis tidspunktet er tidszone-bevidst.
    if now.tzinfo is not None and now.dst() is not None:
        is_dst: Optional[bool] = bool(now.dst())
    else:
        is_dst = None
    return {
        "weekday": weekday,
        "hour": now.hour,
        "month": now.month,
        "week_of_year": iso[1],
        "quarter": (now.month - 1) // 3 + 1,
        "is_weekday": _as_int_bool(not is_weekend),
        "is_weekend": _as_int_bool(is_weekend),
        # Helligdags-/skoleferiekontekst leveres af holiday_calendar (Trin 2).
        "is_public_holiday_dk": None,
        "is_school_holiday_dk": None,
        "days_until_christmas": None,
        "days_until_easter": None,
        "is_summer_time": _as_int_bool(is_dst),
    }


class DataCollector:
    """Samler og persisterer 5-minutters måledata."""

    def __init__(self, db_path: Optional[str] = None,
                 config_dir: str = CONFIG_DIR) -> None:
        self._path = db_path or str(Path(config_dir) / DATA_DB_FILE)
        self._lock = threading.Lock()
        self._weather = WeatherFetcher()
        self._log = get_commons_logger(config_dir)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- offentligt API -------------------------------------------------
    async def collect(self, hass, coordinator) -> Optional[int]:
        """Saml ét målepunkt og skriv det. Returnerer rowid (eller None ved fejl)."""
        try:
            row = await self._build_row(hass, coordinator)
        except Exception as err:  # noqa: BLE001 — indsamling må aldrig vælte drift
            self._log.exception("Kunne ikke bygge målerække: %s", err)
            return None
        try:
            rowid = await hass.async_add_executor_job(self._write, row)
        except Exception as err:  # noqa: BLE001
            self._log.exception("Kunne ikke skrive målerække: %s", err)
            return None

        # Decision tracking (lazy-loaded, fejl blokerer aldrig optimering)
        try:
            from .decision_tracker import DecisionTracker
            tracker = DecisionTracker(self._path)
            await tracker.log_decision(
                hass,
                planned_action=row.get("planned_battery_action"),
                planned_reasoning=row.get("teo_reasoning_short"),
            )
        except Exception as err:  # noqa: BLE001
            self._log.warning("Decision tracking fejlede (ikke-kritisk): %s", err)

        return rowid

    async def _build_row(self, hass, coordinator) -> dict[str, Any]:
        """Byg measurements-rækken fra coordinator-snapshot + vejr + sol + tid."""
        from homeassistant.util import dt as dt_util

        now = dt_util.now()  # HA-lokal, tidszone-bevidst
        data = coordinator.data or {}
        snapshot = data.get("snapshot") or {}
        plan = data.get("plan") or []
        step = plan[0] if plan else {}

        # Energi
        grid_import, grid_export = _split_grid(snapshot.get("grid_power_kw"))
        # Enphase' encharge-effekt er negativ ved opladning; spec (DEL 1) ønsker
        # positiv=lader / negativ=aflader, så vi vender fortegnet her.
        raw_batt = snapshot.get("battery_power_kw")
        battery_power = -raw_batt if raw_batt is not None else None
        row: dict[str, Any] = {
            "timestamp": now.isoformat(),
            "solar_production_kw": snapshot.get("solar_kw"),
            "house_consumption_kw": snapshot.get("house_kw"),
            "battery_soc_pct": snapshot.get("battery_soc_pct"),
            "battery_power_kw": battery_power,
            "battery_reserve_pct": self._read_reserve_pct(hass),
            "grid_import_kw": grid_import,
            "grid_export_kw": grid_export,
            "ev_total_kw": snapshot.get("ev_power_kw"),
            "nordpool_price_ore": snapshot.get("price_ore"),
            # TEO-beslutning
            "teo_action": step.get("battery_action_type"),
            "planned_battery_action": step.get("battery_action_type"),
            "optimizer_ran": _as_int_bool(not coordinator.fallback_active),
            "fallback_active": _as_int_bool(coordinator.fallback_active),
        }

        # Vejr (Open-Meteo) — koordinater fra HA's hjemme-lokation.
        lat = getattr(hass.config, "latitude", None)
        lon = getattr(hass.config, "longitude", None)
        elev = getattr(hass.config, "elevation", 0) or 0
        if lat is not None and lon is not None:
            row.update(await self._weather.fetch(hass, lat, lon, now=now))
            row.update(sun_calculator.compute(lat, lon, elev, now))

        # Tidskontekst + helligdags-/skoleferiekontekst (Trin 2).
        row.update(time_context(now))
        row.update(holiday_calendar.context(now.date()))
        # is_daylight kan komme fra sol-geometrien som bool → gem som 0/1.
        if "is_daylight" in row:
            row["is_daylight"] = _as_int_bool(row.get("is_daylight"))
        return row

    def _read_reserve_pct(self, hass) -> Optional[float]:
        """Læs Envoys faktiske reserve-readback (sensor, ikke number-kommando).

        Vi gemmer det Envoy *rapporterer* (sandheden), ikke den kommanderede
        værdi — jf. den observerede reserve-skrivefejl 2026-05-30 hvor number
        viste 30 mens Envoy kørte 0.
        """
        for st in hass.states.async_all("sensor"):
            if st.entity_id.endswith("_reserve_battery_level"):
                try:
                    return float(st.state)
                except (ValueError, TypeError):
                    return None
        return None

    # -- persistens -----------------------------------------------------
    def _write(self, row: dict[str, Any]) -> int:
        values = [row.get(col) for col in MEASUREMENT_COLUMNS]
        placeholders = ", ".join("?" for _ in MEASUREMENT_COLUMNS)
        columns = ", ".join(MEASUREMENT_COLUMNS)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO measurements ({columns}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def purge_old(self, retention_days: int = MEASUREMENTS_RETENTION_DAYS,
                  now: Optional[datetime] = None) -> int:
        """Slet measurements ældre end opbevaringsgrænsen."""
        cutoff = (now or datetime.now()) - timedelta(days=retention_days)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM measurements WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
            return cur.rowcount

    def upsert_daily(self, date_str: str, zone: Optional[str],
                     fields: dict[str, Any]) -> None:
        """Indsæt/opdatér én daily_summary-række (nøgle: date+zone).

        Deles af price_analyzer-servicen (skriver prisstatistik + day_scenario)
        og cost_calculator (skriver omkostning/besparelse) — hver fylder kun de
        kolonner den ejer, uden at overskrive de øvrige.
        """
        if not fields:
            return
        cols = list(fields.keys())
        col_names = ", ".join(["date", "zone", *cols])
        placeholders = ", ".join("?" for _ in range(2 + len(cols)))
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in cols)
        values = [date_str, zone, *(fields[c] for c in cols)]
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""INSERT INTO daily_summary ({col_names}) VALUES ({placeholders})
                    ON CONFLICT(date, zone) DO UPDATE SET {set_clause}""",
                values,
            )

    def latest(self) -> Optional[dict[str, Any]]:
        """Hent seneste målepunkt (til selvtest/diagnostik)."""
        with self._lock, self._connect() as conn:
            r = conn.execute(
                "SELECT * FROM measurements ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]

"""Konstanter og standardværdier for TEO (Tjelums Energy Optimisation).

Designprincip #8 (ufravigeligt): Ingen magic numbers andre steder i koden.
Al konfiguration, alle defaults og alle nøgler defineres her.

Designprincip #7: Brugervendt tekst hører IKKE hjemme her — den ligger i
translations/da.json og translations/en.json. Denne fil indeholder kun
maskinnære nøgler, enums og numeriske defaults.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Integration-identitet
# ---------------------------------------------------------------------------

DOMAIN: Final = "teo"
INTEGRATION_NAME: Final = "TEO"
TEO_VERSION: Final = "1.0.0"

# Algoritme-version er bevidst adskilt fra TEO_VERSION (spec §12).
# Den ændres når optimizer-parametre eller LP-model justeres.
ALGORITHM_VERSION: Final = "1.0.0"

# ---------------------------------------------------------------------------
# Filstier (relativt til HA's /config-mappe)
# ---------------------------------------------------------------------------

CONFIG_DIR: Final = "/config"
INSTALLATION_ID_FILE: Final = "teo_installation_id.txt"
CONFIG_FILE: Final = "teo_config.yaml"
USER_SETTINGS_FILE: Final = "teo_user_settings.yaml"
DECISIONS_DB_FILE: Final = "teo_decisions.db"
SECRETS_DIR: Final = ".teo"  # /config/.teo/ — 600-rettigheder, krypterede tokens
ENPHASE_TOKEN_FILE: Final = "enphase_token.json"

# ---------------------------------------------------------------------------
# Driftstilstande
# ---------------------------------------------------------------------------

MODE_LOCAL: Final = "local"
MODE_SELF_HOSTED: Final = "self_hosted"
MODES: Final = (MODE_LOCAL, MODE_SELF_HOSTED)

LANG_DA: Final = "da"
LANG_EN: Final = "en"
LANGUAGES: Final = (LANG_DA, LANG_EN)
DEFAULT_LANGUAGE: Final = LANG_DA

# ---------------------------------------------------------------------------
# Elzoner (Nord Pool priszoner)
# ---------------------------------------------------------------------------

GRID_AREAS: Final = (
    "DK1", "DK2",
    "SE1", "SE2", "SE3", "SE4",
    "NO1", "NO2", "NO3", "NO4", "NO5",
    "FI", "EE", "LV", "LT",
)
DEFAULT_GRID_AREA: Final = "DK2"

# ---------------------------------------------------------------------------
# Standardparametre for optimering (Jakob's installation som default-profil)
#   Kilde: CLAUDE_CODE_START_HER.md "Standard parametre" + TECHNICAL_SPEC §3.3/§5.1
# ---------------------------------------------------------------------------

# Batteri
DEFAULT_BATTERY_CAPACITY_KWH: Final = 10.5
DEFAULT_BATTERY_MIN_SOC_PCT: Final = 20
DEFAULT_BATTERY_MAX_SOC_PCT: Final = 95
DEFAULT_EV_PROTECTION_SOC_PCT: Final = 30
DEFAULT_CHARGE_EFFICIENCY: Final = 0.95
DEFAULT_DISCHARGE_EFFICIENCY: Final = 0.95
DEFAULT_DEGRADATION_COST_DKK_PER_KWH: Final = 0.04
# Fald-tilbage for maks lade-/afladeeffekt når enheden ikke oplyser det selv.
DEFAULT_BATTERY_MAX_CHARGE_KW: Final = 3.84
DEFAULT_BATTERY_MAX_DISCHARGE_KW: Final = 3.84

# Prisstrategi (øre/kWh)
DEFAULT_CHARGE_FROM_GRID_BELOW_ORE: Final = 60
DEFAULT_USE_BATTERY_ABOVE_ORE: Final = 100

# Sol
DEFAULT_SOLAR_AZIMUTH_DEG: Final = 180  # 0=Nord, 90=Øst, 180=Syd, 270=Vest
DEFAULT_SOLAR_TILT_DEG: Final = 35
DEFAULT_SOLAR_PEAK_KWP: Final = 11.2
DEFAULT_SOLAR_UNCERTAINTY_FACTOR: Final = 0.85  # P50 × 0,85 (konservativt)

# Optimeringshorisont
DEFAULT_OPTIMISATION_HORIZON_HOURS: Final = 24
DEFAULT_TIMESTEP_MINUTES: Final = 60
DEFAULT_RUN_AT_HOURS: Final = (13, 23)
DEFAULT_RECALCULATE_ON_PRICE_SPIKE_ORE: Final = 30

# Net (Danmark default)
DEFAULT_NETWORK_TARIFF_ORE: Final = 8.8
DEFAULT_VAT_PERCENT: Final = 25

# ---------------------------------------------------------------------------
# Notifikationer
# ---------------------------------------------------------------------------

DEFAULT_LOW_BATTERY_ALERT_SOC_PCT: Final = 15

# ---------------------------------------------------------------------------
# Manuel styring / overrides
# ---------------------------------------------------------------------------

OVERRIDE_EXPIRY_HOURS: Final = 4  # Manuelle tilsidesætninger udløber efter 4 timer

# ---------------------------------------------------------------------------
# Beslutningslog
# ---------------------------------------------------------------------------

DECISION_RETENTION_DAYS: Final = 90
DECISION_LOG_MAX_DISPLAY: Final = 50

# Handlingstyper (action_type) — spec §3.5
ACTION_BATTERY_CHARGE_GRID: Final = "BATTERY_CHARGE_GRID"
ACTION_BATTERY_CHARGE_SOLAR: Final = "BATTERY_CHARGE_SOLAR"
ACTION_BATTERY_DISCHARGE: Final = "BATTERY_DISCHARGE"
ACTION_BATTERY_IDLE: Final = "BATTERY_IDLE"
ACTION_EV_PAUSE_SOC: Final = "EV_PAUSE_SOC"
ACTION_EV_PAUSE_PRICE: Final = "EV_PAUSE_PRICE"
ACTION_EV_ALLOWED: Final = "EV_ALLOWED"
ACTION_NO_GRID_CHARGE_SOLAR: Final = "NO_GRID_CHARGE_SOLAR"
ACTION_OPTIMISATION_RECALCULATED: Final = "OPTIMISATION_RECALCULATED"
ACTION_FALLBACK_ACTIVE: Final = "FALLBACK_ACTIVE"

# Enhedsbetegnelser brugt i loggen (device-feltet)
DEVICE_BATTERY: Final = "batteri"
DEVICE_SYSTEM: Final = "system"

# ---------------------------------------------------------------------------
# Enhedskategorier (modulær integration — designprincip #4)
# ---------------------------------------------------------------------------

CATEGORY_BATTERY: Final = "battery"
CATEGORY_INVERTER: Final = "inverter"
CATEGORY_EV_CHARGER: Final = "ev_charger"
CATEGORY_GRID_METER: Final = "grid_meter"
CATEGORY_HEAT_PUMP: Final = "heat_pump"  # v2.0 — placeholder

# ---------------------------------------------------------------------------
# Enphase batteri-aktuering (direkte Envoy local-API) — KRITISK FIX 2026-05-30
# ---------------------------------------------------------------------------
# HA's enphase_envoy/pyenphase skriver reserve via /admin/lib/tariff men sender
# altid opt_schedules=true, hvorved Enphase' egen cloud-optimering OVERSTYRER
# den manuelle reserve (batteriet drænede forbi 20% i nat). TEO skriver derfor
# tariffen direkte med opt_schedules=FALSE, så reserve/mode/charge_from_grid
# bliver autoritative. Token+host genbruges fra enphase_envoy-config entry.
ENPHASE_DOMAIN: Final = "enphase_envoy"
ENVOY_TARIFF_PATH: Final = "/admin/lib/tariff"
ENVOY_HTTP_TIMEOUT_SEC: Final = 20

# Enphase tariff-mode-strenge (bemærk bindestreg, ulig HA-select's understreg).
ENPHASE_MODE_SELF_CONSUMPTION: Final = "self-consumption"
ENPHASE_MODE_BACKUP: Final = "backup"
ENPHASE_MODE_SAVINGS: Final = "savings"

# En ekstern aktør (Enphase-cloud/Enlighten-optimering) gen-aktiverer
# opt_schedules ca. hvert 2. minut og nulstiller reserven. TEO gen-håndhæver
# derfor sin kommando: tjek tariffen med dette interval og gen-skriv ved drift.
ACTUATION_CHECK_INTERVAL_SEC: Final = 30
RESERVE_DRIFT_TOLERANCE_PCT: Final = 2.0

# ---------------------------------------------------------------------------
# GUI-batteristyring (number/switch-entiteter) — lokal opsætning komplet
# ---------------------------------------------------------------------------

# Konfig-sektion for bruger-toggles der virker som HÅRDE LP-begrænsninger.
CONF_CONTROL: Final = "control"
CONF_SELL_AT_NEGATIVE_PRICE: Final = "sell_at_negative_price"
CONF_CHARGE_FROM_GRID_ALLOWED: Final = "charge_from_grid_allowed"
DEFAULT_SELL_AT_NEGATIVE_PRICE: Final = True
DEFAULT_CHARGE_FROM_GRID_ALLOWED: Final = True

# number.teo_batteri_minimum_soc — skrives til teo_config.yaml (battery.min_soc).
MIN_SOC_SELECTABLE_MIN: Final = 5
MIN_SOC_SELECTABLE_MAX: Final = 50
MIN_SOC_SELECTABLE_STEP: Final = 5

# number.teo_enphase_reserve_soc — manuel Envoy-reserve (via opt_schedules=false).
ENPHASE_RESERVE_MIN: Final = 5
ENPHASE_RESERVE_MAX: Final = 95
ENPHASE_RESERVE_STEP: Final = 5

# ---------------------------------------------------------------------------
# Brugerindstillinger — persistente GUI-værdier (teo_user_settings.yaml)
# ---------------------------------------------------------------------------

# YAML-nøgler for user settings
USER_SETTING_MIN_SOC: Final = "minimum_soc_pct"
USER_SETTING_RESERVE_SOC: Final = "reserve_soc_pct"
USER_SETTING_CHARGE_FROM_GRID: Final = "charge_from_grid"
USER_SETTING_SELL_AT_NEGATIVE: Final = "sell_at_negative_price"
USER_SETTING_GRID_CHARGE_ALLOWED: Final = "grid_charge_allowed_in_optimization"
USER_SETTING_EV_SOLAR_NET_ONLY: Final = "ev_charge_solar_net_only"

# Defaults for user settings (Jakob's favoritindstillinger)
DEFAULT_USER_MIN_SOC: Final = 5
DEFAULT_USER_RESERVE_SOC: Final = 5
DEFAULT_USER_CHARGE_FROM_GRID: Final = False
DEFAULT_USER_SELL_AT_NEGATIVE: Final = False
DEFAULT_USER_GRID_CHARGE_ALLOWED: Final = True
DEFAULT_USER_EV_SOLAR_NET_ONLY: Final = True
DEVICE_CATEGORIES: Final = (
    CATEGORY_BATTERY,
    CATEGORY_INVERTER,
    CATEGORY_EV_CHARGER,
    CATEGORY_GRID_METER,
)

# Discovery-metoder
DISCOVERY_MDNS: Final = "mdns"
DISCOVERY_FINGERPRINT: Final = "fingerprint"
DISCOVERY_MANUAL: Final = "manual"

# ---------------------------------------------------------------------------
# Netværksscanner — spec §3.6
# ---------------------------------------------------------------------------

SCAN_TIMEOUT_PER_IP_SEC: Final = 0.5  # 500 ms
SCAN_MAX_HOSTS: Final = 254
SCAN_MAX_WORKERS: Final = 64

# mDNS service-typer
MDNS_SERVICE_TYPES: Final = (
    "_enphaseenergy._tcp.local.",
    "_hap._tcp.local.",
    "_http._tcp.local.",
)

# Port-fingerprints: (port, sti, søgetekst i svar, kategori, mærke)
FINGERPRINT_ENPHASE: Final = (443, "/info", "envoy", CATEGORY_INVERTER, "enphase")
FINGERPRINT_EASEE: Final = (4123, "/api/charger", "easee", CATEGORY_EV_CHARGER, "easee")
FINGERPRINT_ZAPTEC: Final = (80, "/api", "zaptec", CATEGORY_EV_CHARGER, "zaptec")
FINGERPRINT_GOE: Final = (80, "/api/info", "go-e", CATEGORY_EV_CHARGER, "go-e")

# ---------------------------------------------------------------------------
# Optimeringsmotor — spec §3.3
# ---------------------------------------------------------------------------

SOLVER_HIGHS: Final = "highs"
SOLVER_GLPK: Final = "glpk"
SOLVER_FALLBACK: Final = "fallback"
SOLVER_ORDER: Final = (SOLVER_HIGHS, SOLVER_GLPK)

SOLVER_STATUS_OPTIMAL: Final = "optimal"
SOLVER_STATUS_FEASIBLE: Final = "feasible"
SOLVER_STATUS_FAILED: Final = "failed"

BATTERY_ACTION_CHARGE: Final = "charge"
BATTERY_ACTION_DISCHARGE: Final = "discharge"
BATTERY_ACTION_IDLE: Final = "idle"

# ---------------------------------------------------------------------------
# TEO API (kun Self-Hosted) — spec §6
# ---------------------------------------------------------------------------

# Bruges KUN i Self-Hosted-tilstand. I Local-tilstand foretages ingen kald.
TEO_API_BASE_URL: Final = "https://api.teo.energy"
API_PATH_REGISTER: Final = "/v1/register"
API_PATH_CONFIG: Final = "/v1/config"
API_PATH_UPDATES: Final = "/v1/updates"
API_PATH_DATA: Final = "/v1/data"
API_PATH_FEEDBACK: Final = "/v1/feedback"
API_PATH_FEEDBACK_STATUS: Final = "/v1/feedback/status"
API_PATH_CREATE_ACCOUNT: Final = "/v1/create-account"

API_PATH_TELEMETRY: Final = "/v1/telemetry"      # Data Commons-upload (DEL 6)
API_PATH_MODEL_LATEST: Final = "/v1/model/latest"  # Global model (DEL 7.4)

API_TIMEOUT_SEC: Final = 15
API_UPDATE_CHECK_HOUR: Final = 4  # Dagligt opdateringscheck kl. 04:00

# Data Commons cloud (DEL 6/7). Upload/modelhentning er opt-in og kun
# Self-Hosted; tidspunkterne styres af automations i DEL 6.
DEFAULT_SYSTEM_BATTERY_KWH: Final = 10.5
DEFAULT_SYSTEM_SOLAR_KWP: Final = 11.2
# Hvor systemet husker en hentet-men-ikke-anvendt global model.
PENDING_MODEL_FILE: Final = "teo_pending_model.json"
ACCOUNT_POLL_INTERVAL_SEC: Final = 10
ACCOUNT_POLL_MAX_SEC: Final = 300  # 5 minutter

# Feedback issue-typer — spec §6.1 POST /v1/feedback
FEEDBACK_ISSUE_TYPES: Final = (
    "waited_too_long",
    "acted_too_early",
    "solar_not_considered",
    "battery_already_full",
    "price_dropped_after",
    "other",
)
FEEDBACK_COMMENT_MAX_LEN: Final = 500

# ---------------------------------------------------------------------------
# Easee master/slave kredsløb — spec §4.4
# ---------------------------------------------------------------------------

EASEE_ROLE_MASTER: Final = "master"
EASEE_ROLE_SLAVE: Final = "slave"
DEFAULT_CIRCUIT_MAX_CURRENT_A: Final = 20  # Bekræftes af Jakob ved opsætning
DEFAULT_CHARGER_MAX_CURRENT_A: Final = 16
EASEE_LOCAL_API_PORT: Final = 4123

# ---------------------------------------------------------------------------
# Grid meter / AMS HAN — spec §4 / project_summary
# ---------------------------------------------------------------------------

DEFAULT_MQTT_TOPIC: Final = "ams/power"
DEFAULT_MQTT_BROKER: Final = "localhost"
DEFAULT_MQTT_PORT: Final = 1883

# ---------------------------------------------------------------------------
# Hardware-detektion — spec §8
# ---------------------------------------------------------------------------

ML_MIN_RAM_GB: Final = 2  # ml_features_enabled = False under denne grænse

# ---------------------------------------------------------------------------
# Konfigurationsnøgler (teo_config.yaml) — spec §5.1
# Centraliseret så optimizer/coordinator/config_flow deler præcis samme nøgler.
# ---------------------------------------------------------------------------

CONF_INSTALLATION: Final = "installation"
CONF_ID: Final = "id"
CONF_MODE: Final = "mode"
CONF_LANGUAGE: Final = "language"
CONF_TEO_VERSION: Final = "teo_version"
CONF_CREATED: Final = "created"

CONF_GRID: Final = "grid"
CONF_AREA: Final = "area"
CONF_TARIFF_ORE: Final = "tariff_ore_per_kwh"
CONF_VAT_PERCENT: Final = "vat_percent"

CONF_BATTERY: Final = "battery"
CONF_INTEGRATION: Final = "integration"
CONF_HOST: Final = "host"
CONF_CAPACITY_KWH: Final = "capacity_kwh"
CONF_MIN_SOC_PCT: Final = "min_soc_percent"
CONF_MAX_SOC_PCT: Final = "max_soc_percent"
CONF_EV_PROTECTION_SOC_PCT: Final = "ev_protection_soc_percent"
CONF_CHARGE_EFFICIENCY: Final = "charge_efficiency"
CONF_DISCHARGE_EFFICIENCY: Final = "discharge_efficiency"
CONF_DEGRADATION_COST: Final = "degradation_cost_dkk_per_kwh"
CONF_ENPHASE_TOKEN_PATH: Final = "enphase_token_path"

CONF_INVERTER: Final = "inverter"

CONF_SOLAR: Final = "solar"
CONF_SOLCAST_API_KEY: Final = "solcast_api_key"
CONF_AZIMUTH: Final = "azimuth_degrees"
CONF_TILT: Final = "tilt_degrees"
CONF_PEAK_KWP: Final = "peak_power_kwp"
CONF_UNCERTAINTY_FACTOR: Final = "uncertainty_factor"

CONF_EV_CHARGERS: Final = "ev_chargers"
CONF_NAME: Final = "name"
CONF_CHARGER_ID: Final = "charger_id"
CONF_MAX_CURRENT_A: Final = "max_current_a"
CONF_CIRCUIT_ID: Final = "circuit_id"
CONF_ROLE: Final = "role"

CONF_CIRCUITS: Final = "circuits"

CONF_GRID_METER: Final = "grid_meter"
CONF_MQTT_TOPIC: Final = "mqtt_topic"
CONF_MQTT_BROKER: Final = "mqtt_broker"
CONF_MQTT_PORT: Final = "mqtt_port"

CONF_OPTIMISATION: Final = "optimisation"
CONF_HORIZON_HOURS: Final = "horizon_hours"
CONF_TIMESTEP_MINUTES: Final = "timestep_minutes"
CONF_CHARGE_FROM_GRID_BELOW_ORE: Final = "charge_from_grid_below_ore"
CONF_USE_BATTERY_ABOVE_ORE: Final = "use_battery_above_ore"
CONF_RUN_AT_HOURS: Final = "run_at_hours"
CONF_RECALC_ON_SPIKE_ORE: Final = "recalculate_on_price_spike_ore"

CONF_DATA_SHARING: Final = "data_sharing"
CONF_OPT_IN: Final = "opt_in"
CONF_LAST_SENT: Final = "last_sent"

CONF_NOTIFICATIONS: Final = "notifications"
CONF_LOW_BATTERY_ALERT: Final = "low_battery_alert_soc_pct"
CONF_EV_CHARGE_COMPLETE: Final = "ev_charge_complete"
CONF_DAILY_SAVINGS_SUMMARY: Final = "daily_savings_summary"
CONF_OPTIMISATION_DECISIONS: Final = "optimisation_decisions"

CONF_HARDWARE: Final = "hardware"
CONF_DETECTED_MODEL: Final = "detected_model"
CONF_RAM_GB: Final = "ram_gb"
CONF_ML_ENABLED: Final = "ml_features_enabled"

# Coordinator-opdateringsinterval (live-data poll)
DEFAULT_UPDATE_INTERVAL_SEC: Final = 10

# ---------------------------------------------------------------------------
# Data Commons — lokal dataindsamling (CLAUDE_CODE_SAMLET_V2 DEL 1)
# ---------------------------------------------------------------------------

# SQLite-database til 5-minutters måledata + afledte tabeller. Adskilt fra
# beslutningsloggen (teo_decisions.db) så dataindsamling aldrig kan blokere
# eller korrumpere driftsloggen (designprincip #2: aldrig blokér optimering).
DATA_DB_FILE: Final = "teo_data.db"

# Fejl- og statuslog for hele Data Commons-rørledningen (spec DEL 10).
DATA_LOG_DIR: Final = "teo_logs"
DATA_COMMONS_LOG_FILE: Final = "data_commons.log"

# Ugentlig CSV-eksport (designprincip #8 i SAMLET_V2: eksportér ugentligt).
DATA_EXPORT_DIR: Final = "teo_export"

# Indsamlingskadence og opbevaring.
DATA_COLLECTION_INTERVAL_MINUTES: Final = 5
MEASUREMENTS_RETENTION_DAYS: Final = 1100      # ~3 år rå 5-min data
DAILY_SUMMARY_RETENTION_DAYS: Final = 3653     # 10 år
DECISION_OUTCOMES_RETENTION_DAYS: Final = 730  # 2 år

# HA-services som integrationen registrerer (kaldes af automations i DEL 6
# og kan trigges manuelt fra Udviklerværktøjer).
SERVICE_COLLECT_DATA: Final = "collect_data"
SERVICE_DAILY_CALIBRATION: Final = "daily_calibration"
SERVICE_PRICE_ANALYSIS: Final = "price_analysis"
SERVICE_CLOUD_UPLOAD: Final = "cloud_upload"
SERVICE_MODEL_UPDATE: Final = "model_update"
SERVICE_APPLY_MODEL: Final = "apply_model"
SERVICE_DECISION_ANALYSIS: Final = "decision_analysis"

# ---------------------------------------------------------------------------
# Vejr — Open-Meteo (ingen API-nøgle) — spec DEL 1 / DEL 8
# ---------------------------------------------------------------------------

OPEN_METEO_URL: Final = "https://api.open-meteo.com/v1/forecast"
# Vejret ændrer sig langsommere end indsamlingskadencen; cache mindsker kald.
WEATHER_CACHE_TTL_MINUTES: Final = 15
WEATHER_TIMEOUT_SEC: Final = 15

# Vejrkategorier (weather_category) — udledt af WMO weather_code.
WEATHER_SUNNY: Final = "sunny"
WEATHER_PARTLY_CLOUDY: Final = "partly_cloudy"
WEATHER_OVERCAST: Final = "overcast"
WEATHER_RAIN: Final = "rain"
WEATHER_SNOW: Final = "snow"
WEATHER_FOG: Final = "fog"

# Nedbørstyper (precipitation_type).
PRECIP_NONE: Final = "none"
PRECIP_RAIN: Final = "rain"
PRECIP_SNOW: Final = "snow"
PRECIP_SLEET: Final = "sleet"

# ---------------------------------------------------------------------------
# Sol-geometri — beregnet lokalt (astral, allerede en HA-kerneafhængighed)
# ---------------------------------------------------------------------------

# Sommersolhverv bruges som sæsonindikator (days_since_summer_solstice).
SUMMER_SOLSTICE_MONTH: Final = 6
SUMMER_SOLSTICE_DAY: Final = 21

# ---------------------------------------------------------------------------
# Helligdage og skoleferier (DK) — spec DEL 1 / DEL 8
# ---------------------------------------------------------------------------

# 'holidays'-biblioteket dækker de officielle danske helligdage.
HOLIDAYS_COUNTRY_DK: Final = "DK"

# Jul som nedtællingsreference (dansk jul fejres juleaften d. 24.).
CHRISTMAS_MONTH: Final = 12
CHRISTMAS_DAY: Final = 24

# Danske skoleferier er kommune-afhængige; her bruges det gængse nationale
# mønster (kan kalibreres pr. installation senere). Faste uger:
SCHOOL_WINTER_WEEK: Final = 7        # Vinterferie
SCHOOL_AUTUMN_WEEK: Final = 42       # Efterårsferie

# Datospænd (måned, dag) — inklusive grænser. Sommer- og juleferie.
SCHOOL_SUMMER_START: Final = (6, 28)
SCHOOL_SUMMER_END: Final = (8, 9)
SCHOOL_CHRISTMAS_START: Final = (12, 20)
SCHOOL_CHRISTMAS_END: Final = (1, 2)  # ind i det nye år

# Påskeferie relativt til påskedag: lørdag før palmesøndag → 2. påskedag.
EASTER_HOLIDAY_START_OFFSET: Final = -8
EASTER_HOLIDAY_END_OFFSET: Final = 1

# ---------------------------------------------------------------------------
# Anomali-detektion — spec DEL 2.3
# ---------------------------------------------------------------------------

# Forbrug over forventet + N×std for konteksten flagges som anomali og holdes
# UDEN FOR modeltræningen (designprincip #3 i SAMLET_V2).
ANOMALY_STD_MULTIPLIER: Final = 2.5
# "Familie fraværende": konsekvent lavt forbrug i mere end så mange dage.
ABSENT_MODE_MIN_DAYS: Final = 3
# Forbrug under denne andel af forventet tæller som "lavt" i fraværsdetektion.
ABSENT_MODE_LOW_FACTOR: Final = 0.5

# ---------------------------------------------------------------------------
# Familielæring / lastprofiler — spec DEL 2 (deles af family_learner +
# anomaly_detector så nøgleformatet altid stemmer)
# ---------------------------------------------------------------------------

# 168-punkts profil: pattern_type="weekday_hour", context_key="<ugedag>_<time>".
PATTERN_WEEKDAY_HOUR: Final = "weekday_hour"

# Aggregerede profiler (context_key = time 0-23).
PROFILE_WEEKDAY: Final = "weekday"
PROFILE_WEEKEND: Final = "weekend"
PROFILE_HOLIDAY: Final = "holiday"
PROFILE_SCHOOL_HOLIDAY: Final = "school_holiday_weekday"

# Vindue og minimumskrav for at en profil tæller som pålidelig.
FAMILY_LEARN_LOOKBACK_DAYS: Final = 90
FAMILY_MIN_SAMPLES: Final = 3
# Sæsonprofil læres over et helt år.
SEASON_LOOKBACK_DAYS: Final = 365
# Solcast-kalibrering per vejrtype: vindue i dage.
SOLCAST_CALIBRATION_LOOKBACK_DAYS: Final = 30

# Sæson-/profiltyper gemt i family_patterns (ud over PROFILE_* ovenfor).
PATTERN_SEASON_MONTH: Final = "season_month"

# ---------------------------------------------------------------------------
# Prisarbitrage-analyse — spec DEL 3 (price_analyzer, dagligt kl. 13:30)
# ---------------------------------------------------------------------------

# 3.1 Aftenspris-index: dyr aftenperiode.
EVENING_PEAK_START_HOUR: Final = 17
EVENING_PEAK_END_HOUR: Final = 21          # inklusive 17..21
EVENING_PEAK_INDEX_THRESHOLD: Final = 1.5  # >150 % af dagsgennemsnit
EVENING_TARGET_SOC_PCT: Final = 85         # mål-SOC inden kl. 17

# 3.2 Natte-ladningsvindue.
NIGHT_WINDOW_START_HOUR: Final = 0
NIGHT_WINDOW_END_HOUR: Final = 7
NIGHT_WINDOW_HOURS: Final = 3
# Kombination med Solcast-prognose for morgendagen.
SOLAR_TOMORROW_HIGH_KWH: Final = 8         # >8 kWh sol → reducer natladning
SOLAR_TOMORROW_LOW_KWH: Final = 3          # <3 kWh sol → lad aggressivt

# 3.4 Vind-pris korrelation.
HIGH_WIND_MS: Final = 8

# 3.6 Dag-scenarier.
SCENARIO_A: Final = "A"  # Sol + lav pris
SCENARIO_B: Final = "B"  # Ingen sol + lav nat
SCENARIO_C: Final = "C"  # Ingen sol + høj dag
SCENARIO_D: Final = "D"  # Sol-overskud
SCENARIO_E: Final = "E"  # Høj vind

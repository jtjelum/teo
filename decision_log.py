"""Beslutningslog — fuld transparens i klartekst (dansk + engelsk).

Spec §3.5. Designprincip #3: hver automatisk handling producerer en
log-entry med en menneskelæsbar begrundelse på begge sprog. Ingen sort boks.

Begrundelsesteksten genereres her ud fra ``action_type`` + kontekst via
translations-loaderen (designprincip #7) — fallback-modulet og optimizeren
leverer kun strukturerede data, aldrig færdig tekst.

Lagring: SQLite (``teo_decisions.db``) med 90 dages opbevaring. Metoderne er
synkrone og trådsikre; i HA bør de køres via ``hass.async_add_executor_job``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .const import (
    ACTION_BATTERY_CHARGE_GRID,
    ACTION_BATTERY_CHARGE_SOLAR,
    ACTION_BATTERY_DISCHARGE,
    ACTION_BATTERY_IDLE,
    ACTION_EV_ALLOWED,
    ACTION_EV_PAUSE_PRICE,
    ACTION_EV_PAUSE_SOC,
    ACTION_FALLBACK_ACTIVE,
    ACTION_NO_GRID_CHARGE_SOLAR,
    ACTION_OPTIMISATION_RECALCULATED,
    CONFIG_DIR,
    DECISION_LOG_MAX_DISPLAY,
    DECISION_RETENTION_DAYS,
    DECISIONS_DB_FILE,
    LANG_DA,
    LANG_EN,
)
from .translations import get_string

_LOGGER = logging.getLogger(__name__)

# action_type → nøgle i reasoning-sektionen af translations. Handlinger uden
# egen skabelon (rene status-typer) falder tilbage til en tom begrundelse.
_REASONING_KEY: dict[str, str] = {
    ACTION_BATTERY_CHARGE_GRID: "reasoning.battery_charge_grid",
    ACTION_BATTERY_CHARGE_SOLAR: "reasoning.battery_charge_solar",
    ACTION_BATTERY_DISCHARGE: "reasoning.battery_discharge",
    ACTION_BATTERY_IDLE: "reasoning.battery_idle",
    ACTION_EV_PAUSE_SOC: "reasoning.ev_pause_soc",
    ACTION_EV_PAUSE_PRICE: "reasoning.ev_pause_price",
    ACTION_EV_ALLOWED: "reasoning.ev_allowed",
    ACTION_NO_GRID_CHARGE_SOLAR: "reasoning.no_grid_charge_solar",
    ACTION_OPTIMISATION_RECALCULATED: "reasoning.optimisation_recalculated",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    action_type   TEXT    NOT NULL,
    device        TEXT    NOT NULL,
    power_kw      REAL,
    reasoning_da  TEXT    NOT NULL,
    reasoning_en  TEXT    NOT NULL,
    context       TEXT    NOT NULL,
    human_label            TEXT,
    human_explanation      TEXT,
    valid_until            TEXT,
    decision_source_summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions (timestamp);
CREATE INDEX IF NOT EXISTS idx_decisions_type ON decisions (action_type);
"""

# Kolonner tilføjet efter første udgivelse — migreres ind i eksisterende DB'er.
_ADDED_COLUMNS = (
    "human_label", "human_explanation", "valid_until", "decision_source_summary",
)

# action_type → suffiks i human.label / human.explanation (DEL 4.1/4.2).
# BATTERY_IDLE og NO_GRID_CHARGE_SOLAR håndteres særskilt (kontekst-label).
_HUMAN_SUFFIX: dict[str, str] = {
    ACTION_BATTERY_CHARGE_GRID: "battery_charge_grid",
    ACTION_BATTERY_CHARGE_SOLAR: "battery_charge_solar",
    ACTION_BATTERY_DISCHARGE: "battery_discharge",
    ACTION_EV_PAUSE_SOC: "ev_pause_soc",
    ACTION_EV_PAUSE_PRICE: "ev_pause_price",
    ACTION_EV_ALLOWED: "ev_allowed",
    ACTION_FALLBACK_ACTIVE: "fallback_active",
}


def build_human_label(action_type: str, language: str, is_fallback: bool,
                      idle_reason: Optional[str] = None) -> str:
    """Kort dansk/engelsk klartekst-label (erstatter tekniske action-navne)."""
    if is_fallback:
        return get_string("human.label.fallback_active", language=language)
    if action_type == ACTION_BATTERY_IDLE:
        return get_string(f"human.idle.{idle_reason or 'full'}", language=language)
    if action_type == ACTION_NO_GRID_CHARGE_SOLAR:
        return get_string("human.idle.solar", language=language)
    suffix = _HUMAN_SUFFIX.get(action_type)
    return get_string(f"human.label.{suffix}", language=language) if suffix else ""


def build_human_explanation(action_type: str, language: str, is_fallback: bool,
                            **template_kwargs: Any) -> str:
    """To-linjers forklaring (hvad sker nu + hvornår ændrer det sig)."""
    if is_fallback:
        suffix = "fallback_active"
    elif action_type in (ACTION_BATTERY_IDLE, ACTION_NO_GRID_CHARGE_SOLAR):
        suffix = "battery_idle"
    else:
        suffix = _HUMAN_SUFFIX.get(action_type)
    if not suffix:
        return ""
    return get_string(f"human.explanation.{suffix}", language=language,
                      **template_kwargs)


def build_reasoning(action_type: str, language: str, fallback: bool,
                    **template_kwargs: Any) -> str:
    """Byg én begrundelsesstreng på det ønskede sprog.

    Tilføjer "[FALLBACK] ..."-præfiks når beslutningen kom fra regelmotoren.
    """
    key = _REASONING_KEY.get(action_type)
    body = get_string(key, language=language, **template_kwargs) if key else ""

    if fallback:
        prefix = get_string("reasoning.fallback_prefix", language=language)
        return f"{prefix} {body}".strip()
    return body


class DecisionLog:
    """Trådsikker SQLite-baseret beslutningslog."""

    def __init__(self, db_path: Optional[str] = None,
                 config_dir: str = CONFIG_DIR) -> None:
        self._path = db_path or str(Path(config_dir) / DECISIONS_DB_FILE)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Migrér ældre DB'er: tilføj nye kolonner hvis de mangler.
            existing = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
            for col in _ADDED_COLUMNS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE decisions ADD COLUMN {col} TEXT")

    def log(
        self,
        action_type: str,
        device: str,
        context: dict[str, Any],
        power_kw: Optional[float] = None,
        timestamp: Optional[datetime] = None,
        language: str = LANG_DA,
        valid_until: Optional[datetime] = None,
        idle_reason: Optional[str] = None,
        decision_source_summary: Optional[str] = None,
        **template_kwargs: Any,
    ) -> dict[str, Any]:
        """Skriv én beslutning. Genererer dansk + engelsk begrundelse samt
        klartekst-label + 2-linjers forklaring (DEL 4).

        ``template_kwargs`` videregives til oversættelsesskabelonen (fx
        ``price=107``). ``valid_until`` (datetime) bruges både som kolonne (ISO)
        og som ``{valid_until}``-placeholder (HH:MM) i forklaringen.
        ``human_label``/``human_explanation`` gemmes på ``language``.
        """
        ts = timestamp or datetime.now()
        is_fallback = bool(context.get("fallback")) or action_type == ACTION_FALLBACK_ACTIVE

        reasoning_da = build_reasoning(action_type, LANG_DA, is_fallback, **template_kwargs)
        reasoning_en = build_reasoning(action_type, LANG_EN, is_fallback, **template_kwargs)

        # Klartekst-felter (DEL 4). valid_until → HH:MM i forklaringsteksten.
        expl_kwargs = dict(template_kwargs)
        if valid_until is not None:
            expl_kwargs.setdefault("valid_until", valid_until.strftime("%H:%M"))
        human_label = build_human_label(action_type, language, is_fallback, idle_reason)
        human_explanation = build_human_explanation(
            action_type, language, is_fallback, **expl_kwargs)
        valid_until_iso = valid_until.isoformat() if valid_until is not None else None

        entry = {
            "timestamp": ts.isoformat(),
            "action_type": action_type,
            "device": device,
            "power_kw": power_kw,
            "reasoning_da": reasoning_da,
            "reasoning_en": reasoning_en,
            "context": context,
            "human_label": human_label,
            "human_explanation": human_explanation,
            "valid_until": valid_until_iso,
            "decision_source_summary": decision_source_summary,
        }

        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO decisions
                   (timestamp, action_type, device, power_kw,
                    reasoning_da, reasoning_en, context,
                    human_label, human_explanation, valid_until,
                    decision_source_summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["timestamp"], action_type, device, power_kw,
                    reasoning_da, reasoning_en, json.dumps(context),
                    human_label, human_explanation, valid_until_iso,
                    decision_source_summary,
                ),
            )
        _LOGGER.debug("Beslutning logget: %s (%s)", action_type, device)
        return entry

    def get_recent(
        self,
        limit: int = DECISION_LOG_MAX_DISPLAY,
        action_filter: Optional[str] = None,
        device_filter: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Hent de seneste beslutninger (nyeste først), med valgfrie filtre."""
        query = "SELECT * FROM decisions"
        clauses: list[str] = []
        params: list[Any] = []
        if action_filter:
            clauses.append("action_type = ?")
            params.append(action_filter)
        if device_filter:
            clauses.append("device = ?")
            params.append(device_filter)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def purge_old(self, retention_days: int = DECISION_RETENTION_DAYS,
                  now: Optional[datetime] = None) -> int:
        """Slet entries ældre end opbevaringsgrænsen. Returnerer antal slettede."""
        cutoff = (now or datetime.now()) - timedelta(days=retention_days)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM decisions WHERE timestamp < ?", (cutoff.isoformat(),)
            )
            return cur.rowcount

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "action_type": row["action_type"],
            "device": row["device"],
            "power_kw": row["power_kw"],
            "reasoning_da": row["reasoning_da"],
            "reasoning_en": row["reasoning_en"],
            "context": json.loads(row["context"]),
            "human_label": row["human_label"] if "human_label" in keys else None,
            "human_explanation": (row["human_explanation"]
                                  if "human_explanation" in keys else None),
            "valid_until": row["valid_until"] if "valid_until" in keys else None,
            "decision_source_summary": (row["decision_source_summary"]
                                        if "decision_source_summary" in keys else None),
        }

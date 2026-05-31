"""TEO sensor-platform.

Eksponerer coordinatorens data som HA-sensorer: live-snapshot (pris, SOC, sol),
optimeringsresultat (besparelse, solver-status), plan-handling og
installations-metadata. Alle værdier kommer fra ``coordinator.data``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TEOBaseEntity
from .installation_id import get_human_readable_id


@dataclass(frozen=True, kw_only=True)
class TEOSensorDescription(SensorEntityDescription):
    """SensorEntityDescription udvidet med TEO's værdi-/attribut-funktioner."""

    value_fn: Callable[[dict], Any] = lambda d: None
    attrs_fn: Optional[Callable[[dict], dict]] = None
    # Tving et fast entity_id (uden 'sensor.'-præfiks). Bruges til økonomi-
    # sensorerne, hvis ID'er dashboardet og spec refererer eksplicit.
    object_id: Optional[str] = None


def _plan_first(data: dict, field: str) -> Any:
    plan = data.get("plan") or []
    return plan[0].get(field) if plan else None


def _cost(data: dict, period: str, field: str) -> Any:
    return (data.get("cost") or {}).get(period, {}).get(field)


SENSORS: tuple[TEOSensorDescription, ...] = (
    TEOSensorDescription(
        key="current_price",
        name="Aktuel spotpris",
        native_unit_of_measurement="øre/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        value_fn=lambda d: d.get("snapshot", {}).get("price_ore"),
    ),
    TEOSensorDescription(
        key="battery_soc",
        name="Batteriniveau",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("snapshot", {}).get("battery_soc_pct"),
    ),
    TEOSensorDescription(
        key="solar_production",
        name="Solproduktion",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_fn=lambda d: d.get("snapshot", {}).get("solar_kw"),
    ),
    TEOSensorDescription(
        key="ev_power",
        name="EV-ladeeffekt",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ev-station",
        value_fn=lambda d: d.get("snapshot", {}).get("ev_power_kw"),
    ),
    TEOSensorDescription(
        key="grid_power",
        name="Neteffekt",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower",
        value_fn=lambda d: d.get("snapshot", {}).get("grid_power_kw"),
    ),
    TEOSensorDescription(
        key="estimated_saving_today",
        name="Forventet besparelse i dag",
        native_unit_of_measurement="DKK",
        icon="mdi:piggy-bank",
        value_fn=lambda d: d.get("summary", {}).get("estimated_saving_dkk"),
    ),
    TEOSensorDescription(
        key="planned_battery_action",
        name="Planlagt batterihandling",
        icon="mdi:battery-sync",
        value_fn=lambda d: _plan_first(d, "battery_action"),
        attrs_fn=lambda d: {
            "power_kw": _plan_first(d, "battery_power_kw"),
            "ev_allowed": _plan_first(d, "ev_allowed"),
        },
    ),
    TEOSensorDescription(
        key="solver_status",
        name="Optimerings-status",
        icon="mdi:function-variant",
        value_fn=lambda d: d.get("solver_status"),
    ),
    TEOSensorDescription(
        key="algorithm_version",
        name="Algoritme-version",
        icon="mdi:tag",
        value_fn=lambda d: d.get("algorithm_version"),
    ),
    TEOSensorDescription(
        key="installation_id",
        name="Installations-ID",
        icon="mdi:identifier",
        value_fn=lambda d: d.get("installation_id"),
        attrs_fn=lambda d: {
            "human_readable": (
                get_human_readable_id(d["installation_id"])
                if d.get("installation_id") else None
            ),
            "mode": d.get("mode"),
        },
    ),
    # --- Beslutning i klartekst (DEL 4) -------------------------------
    TEOSensorDescription(
        key="decision_label",
        object_id="teo_beslutning",
        name="Beslutning",
        icon="mdi:lightbulb-on",
        value_fn=lambda d: (d.get("decision") or {}).get("human_label"),
        attrs_fn=lambda d: {
            "forklaring": (d.get("decision") or {}).get("human_explanation"),
            "gyldig_til": (d.get("decision") or {}).get("valid_until"),
            "kilde": (d.get("decision") or {}).get("decision_source_summary"),
            "handling": (d.get("decision") or {}).get("action_type"),
        },
    ),
    # --- Økonomi / besparelse (DEL 4 / DEL 5) -------------------------
    TEOSensorDescription(
        key="cost_actual_today",
        object_id="teo_cost_actual_today_dkk",
        name="Faktisk omkostning i dag",
        native_unit_of_measurement="DKK",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-minus",
        value_fn=lambda d: _cost(d, "today", "actual_cost_dkk"),
    ),
    TEOSensorDescription(
        key="cost_baseline_today",
        object_id="teo_cost_baseline_today_dkk",
        name="Baseline-omkostning i dag",
        native_unit_of_measurement="DKK",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-clock",
        value_fn=lambda d: _cost(d, "today", "baseline_cost_dkk"),
    ),
    TEOSensorDescription(
        key="saving_today",
        object_id="teo_saving_today_dkk",
        name="Besparelse i dag",
        native_unit_of_measurement="DKK",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:piggy-bank",
        value_fn=lambda d: _cost(d, "today", "saving_dkk"),
    ),
    TEOSensorDescription(
        key="avg_price_paid",
        object_id="teo_avg_price_paid_ore",
        name="Gns. pris betalt",
        native_unit_of_measurement="øre/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-check",
        value_fn=lambda d: _cost(d, "today", "avg_price_paid_ore"),
    ),
    TEOSensorDescription(
        key="avg_price_baseline",
        object_id="teo_avg_price_baseline_ore",
        name="Gns. baseline-pris",
        native_unit_of_measurement="øre/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-clock",
        value_fn=lambda d: _cost(d, "today", "avg_price_baseline_ore"),
    ),
    TEOSensorDescription(
        key="saving_month",
        object_id="teo_saving_month_dkk",
        name="Besparelse denne måned",
        native_unit_of_measurement="DKK",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:piggy-bank-outline",
        value_fn=lambda d: _cost(d, "month", "saving_dkk"),
    ),
    TEOSensorDescription(
        key="earnings_month",
        object_id="teo_earnings_month_dkk",
        name="Indtjening denne måned",
        native_unit_of_measurement="DKK",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-plus",
        value_fn=lambda d: _cost(d, "month", "earnings_dkk"),
    ),
    TEOSensorDescription(
        key="grid_cost_month",
        object_id="teo_grid_cost_month_dkk",
        name="Netomkostning denne måned",
        native_unit_of_measurement="DKK",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-export",
        value_fn=lambda d: _cost(d, "month", "grid_cost_dkk"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(TEOSensor(coordinator, desc) for desc in SENSORS)


class TEOSensor(TEOBaseEntity, SensorEntity):
    """En enkelt TEO-sensor drevet af en TEOSensorDescription."""

    entity_description: TEOSensorDescription

    def __init__(self, coordinator, description: TEOSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        # Fast entity_id når beskrivelsen kræver det (økonomi-sensorer).
        if description.object_id:
            self.entity_id = f"sensor.{description.object_id}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.data)

    @property
    def extra_state_attributes(self) -> Optional[dict]:
        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.data)
        return None

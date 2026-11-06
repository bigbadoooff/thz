"""Find the entities of a config entry that feed the advisor.

Entity ids differ by firmware, naming style and user renames, so the
advisor finds its inputs by translation key in the entity registry instead
of by entity id. Inputs the firmware does not have, or whose entity is
disabled (and so has no history), are reported, not guessed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

# Advisor input -> translation keys of sensors that provide it, best first.
SENSOR_KEYS: Mapping[str, tuple[str, ...]] = {
    "rel": ("heating_rel_power",),
    "heat_setpoint": ("heat_set_temp",),
    "heat_temp": ("heat_temp",),
    "return_temp": ("return_temp",),
    "flow_temp": ("flow_temp",),
    "outside_temp": ("outside_temp",),
    "outside_temp_filtered": ("outside_temp_filtered",),
    "room_setpoint": ("room_set_temp",),
    "room_temp": ("inside_temp_rc", "inside_temp"),
    "power_el": ("actual_power_pel",),
    "power_heat": ("actual_power_qc",),
    "flow_rate": ("flow_rate",),
}

# StiebelParams field (or room setpoint of the schedule) -> translation keys
# of number entities holding it.
PARAM_KEYS: Mapping[str, tuple[str, ...]] = {
    "gradient": ("gradient_hc1",),
    "low_end": ("low_end_hc1",),
    "room_influence": ("room_influence_hc1",),
    "flow_share": ("flow_proportion_hc1",),
    "outside_filter_h": ("out_temp_filter_time",),
    "room_day": ("room_temp_day_hc1", "room_temp_day"),
    "room_night": ("room_temp_night_hc1", "room_temp_night"),
}

# Inputs each part of the advisor needs.
SELFTEST_INPUTS = ("rel", "heat_setpoint", "heat_temp", "outside_temp_filtered")
IDENTIFY_INPUTS = ("power_el", "power_heat", "return_temp", "outside_temp")
# Heating power computed from the flow rate needs these instead of power_heat.
HEAT_FROM_FLOW_INPUTS = ("flow_temp", "return_temp")


@dataclass(frozen=True)
class InputMapping:
    """Entities found for the advisor's inputs and parameters."""

    # Advisor input -> entity_id, for enabled sensors.
    sensors: dict[str, str] = field(default_factory=dict)
    # StiebelParams field -> entity_id, for enabled number entities.
    params: dict[str, str] = field(default_factory=dict)
    # Advisor input -> unit of its sensor, where it has one.
    units: dict[str, str] = field(default_factory=dict)
    # Input or parameter -> entity_id of a disabled entity that provides it.
    disabled: dict[str, str] = field(default_factory=dict)
    # Inputs and parameters no entity of this entry provides.
    missing: tuple[str, ...] = ()

    def lacking(self, names: Iterable[str]) -> list[str]:
        """Return those of ``names`` that have no enabled entity."""
        return [n for n in names if n not in self.sensors and n not in self.params]


def _pick(
    entries: list[er.RegistryEntry], domain: str, keys: tuple[str, ...]
) -> tuple[er.RegistryEntry | None, er.RegistryEntry | None]:
    """Return the best enabled entry for ``keys``, else the best disabled one."""
    found = [
        sorted(
            (e for e in entries if e.domain == domain and e.translation_key == key),
            key=lambda e: e.entity_id,
        )
        for key in keys
    ]
    for candidates in found:
        enabled = [e for e in candidates if e.disabled_by is None]
        if enabled:
            return enabled[0], None
    for candidates in found:
        if candidates:
            return None, candidates[0]
    return None, None


def resolve_inputs(entries: Iterable[er.RegistryEntry]) -> InputMapping:
    """Map the advisor's inputs to the given registry entries.

    For each input the first translation key with an enabled entity wins,
    among several entities with that key the lowest entity_id. An input
    with only disabled entities is reported in ``disabled``.
    """
    pool = list(entries)
    sensors: dict[str, str] = {}
    params: dict[str, str] = {}
    units: dict[str, str] = {}
    disabled: dict[str, str] = {}
    missing: list[str] = []
    for domain, table, target in (
        ("sensor", SENSOR_KEYS, sensors),
        ("number", PARAM_KEYS, params),
    ):
        for name, keys in table.items():
            enabled, off = _pick(pool, domain, keys)
            if enabled is not None:
                target[name] = enabled.entity_id
                if domain == "sensor" and enabled.unit_of_measurement:
                    units[name] = enabled.unit_of_measurement
            elif off is not None:
                disabled[name] = off.entity_id
            else:
                missing.append(name)
    return InputMapping(sensors, params, units, disabled, tuple(missing))


def async_resolve_inputs(hass: HomeAssistant, entry_id: str) -> InputMapping:
    """Map the advisor's inputs to the entities of config entry ``entry_id``."""
    registry = er.async_get(hass)
    return resolve_inputs(er.async_entries_for_config_entry(registry, entry_id))


@dataclass(frozen=True)
class PlantInputs:
    """Where the building identification takes its power values from."""

    # The mapping with external sensors in place of the heat pump's own.
    mapping: InputMapping
    # Inputs to read from the recorder.
    names: tuple[str, ...]
    # Compute power_heat from flow_rate (sensor) or flow_lph and flow/return.
    heat_from_flow: bool = False
    # Fixed flow rate in l/h when no flow-rate sensor is used.
    flow_lph: float | None = None
    # power_el / power_heat -> where it comes from, for the attributes.
    sources: dict[str, str] = field(default_factory=dict)


def plant_inputs(
    inputs: InputMapping,
    *,
    power_el_entity: str | None = None,
    power_heat_entity: str | None = None,
    flow_rate_entity: str | None = None,
    flow_rate_lph: float | None = None,
    units: Mapping[str, str] | None = None,
) -> PlantInputs:
    """Choose the power sources of the building identification.

    Electric power: the external sensor if set, else the heat pump's own.
    Heating power: the external sensor if set, else the heat pump's own,
    else flow rate x (flow - return temperature), with the flow rate from
    the external sensor, the heat pump's own flow-rate sensor or the fixed
    value. ``units`` gives the units of the external sensors.
    """
    units = units or {}
    sensors = dict(inputs.sensors)
    sensor_units = dict(inputs.units)
    sources: dict[str, str] = {}

    def use(name: str, entity_id: str) -> None:
        sensors[name] = entity_id
        if entity_id in units:
            sensor_units[name] = units[entity_id]
        else:
            sensor_units.pop(name, None)

    if power_el_entity:
        use("power_el", power_el_entity)
    if "power_el" in sensors:
        sources["power_el"] = sensors["power_el"]
    names = list(IDENTIFY_INPUTS)
    heat_from_flow = False
    flow_lph = None
    if power_heat_entity:
        use("power_heat", power_heat_entity)
    if "power_heat" in sensors:
        sources["power_heat"] = sensors["power_heat"]
    elif flow_rate_entity or "flow_rate" in sensors or flow_rate_lph:
        heat_from_flow = True
        names = [n for n in names if n != "power_heat"]
        names += [n for n in HEAT_FROM_FLOW_INPUTS if n not in names]
        if flow_rate_entity:
            use("flow_rate", flow_rate_entity)
        if "flow_rate" in sensors:
            names.append("flow_rate")
            sources["power_heat"] = f"flow rate x delta T ({sensors['flow_rate']})"
        else:
            flow_lph = flow_rate_lph
            sources["power_heat"] = f"flow rate x delta T ({flow_rate_lph:g} l/h)"
    mapping = InputMapping(
        sensors,
        inputs.params,
        sensor_units,
        inputs.disabled,
        inputs.missing,
    )
    return PlantInputs(mapping, tuple(names), heat_from_flow, flow_lph, sources)

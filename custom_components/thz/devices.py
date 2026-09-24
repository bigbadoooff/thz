"""Device info for THZ entities, optionally split into functional sub-devices.

Without the split every entity belongs to the heat pump device. With
``CONF_SPLIT_DEVICES`` enabled, entities are grouped by function (heating
circuits, hot water, ventilation, compressor, solar, cooling) into
sub-devices linked to the heat pump via ``via_device``. General entities
(clock, fault memory, versions, operating mode, ...) stay on the heat pump.

The group is derived from the entity's unique_id, which carries the register
name for every entity type, so the register maps need no extra metadata.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE, CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_SPLIT_DEVICES, DOMAIN


def entry_unique_id(data: Mapping[str, Any]) -> str:
    """Return the unique id of the entry for a connection (``ip-<host>``...)."""
    return f"{data['connection_type']}-{data.get(CONF_HOST) or data.get(CONF_DEVICE)}"


SUBDEVICE_HEATING = "heating"
SUBDEVICE_HEATING_HC2 = "heating_hc2"
SUBDEVICE_DHW = "dhw"
SUBDEVICE_VENTILATION = "ventilation"
SUBDEVICE_COMPRESSOR = "compressor"
SUBDEVICE_SOLAR = "solar"
SUBDEVICE_COOLING = "cooling"

SUBDEVICES = (
    SUBDEVICE_HEATING,
    SUBDEVICE_HEATING_HC2,
    SUBDEVICE_DHW,
    SUBDEVICE_VENTILATION,
    SUBDEVICE_COMPRESSOR,
    SUBDEVICE_SOLAR,
    SUBDEVICE_COOLING,
)

# Ordered (group, substrings) rules matched against the lower-cased register
# name; the first rule with a matching substring wins and None keeps the
# entity on the heat pump itself. The order resolves names that fit several
# groups: "compressorcooling" (runtime) is the compressor, "sdewpointhc1" is
# cooling, "hcopmode" is not a COP, "p32hystdhw" is hot water and
# "p77outthermfiltertime" (outside temperature filter) is general, not
# ventilation.
_RULES: tuple[tuple[str | None, tuple[str, ...]], ...] = (
    (None, ("outtemp", "outtherm", "outside")),
    (
        SUBDEVICE_COMPRESSOR,
        (
            "compr",
            "compblock",
            "hotgas",
            "evaporator",
            "condenser",
            "p_nd",
            "p_hd",
            "pressuresensor",
            "defr",
            "relpower",
            "actualpower",
            "outputreduction",
            "outputincrease",
            "_cop",
        ),
    ),
    (SUBDEVICE_COOLING, ("cool", "passive", "dewpoint")),
    (SUBDEVICE_SOLAR, ("solar", "collector", "solpump")),
    (SUBDEVICE_HEATING_HC2, ("hc2", "circuit_2", "mixer")),
    (SUBDEVICE_DHW, ("dhw", "pasteuri", "anode")),
    (
        SUBDEVICE_VENTILATION,
        (
            "fan",
            "vent",
            "airflow",
            "filter",
            "humid",
            "shum",
            "fireplace",
            "windowopen",
            "heatrecovered",
        ),
    ),
    (
        SUBDEVICE_HEATING,
        (
            "hc",
            "heating_circuit",
            "heatingcircuit",
            "room",
            "insidetemp",
            "flowtemp",
            "returntemp",
            "flowrate",
            "heatsettemp",
            "heattemp",
            "integral",
            "hyst",
            "summermode",
            "seasonmode",
            "pumpcycles",
        ),
    ),
)


def subdevice_for(unique_id: str, device_id: str) -> str | None:
    """Return the sub-device group of an entity, or None for the heat pump.

    The device id (host or serial path, wherever it appears) and the command
    part of register unique_ids are ignored so that they cannot match a rule.
    """
    name = unique_id.replace(device_id, "").rsplit("'", 1)[-1].lower()
    for group, patterns in _RULES:
        if any(pattern in name for pattern in patterns):
            return group
    return None


def main_device_name(data: Mapping[str, Any]) -> str:
    """Return the heat pump device's name for a config entry's data."""
    return str(data.get("alias") or f"THZ {data.get('host') or data.get('device')}")


def thz_device_info(
    device_id: str,
    subdevice: str | None,
    device_name: str | None = None,
    area: str | None = None,
) -> DeviceInfo:
    """Return the DeviceInfo linking an entity to the heat pump or a sub-device.

    ``area`` is the heat pump's configured area; Home Assistant applies it
    only when it creates the sub-device, so a later change by the user stays.
    """
    if subdevice is None:
        return DeviceInfo(identifiers={(DOMAIN, device_id)})
    info = DeviceInfo(
        identifiers={(DOMAIN, subdevice_identifier(device_id, subdevice))},
        via_device=(DOMAIN, device_id),
        translation_key=subdevice,
        translation_placeholders={"device_name": device_name or device_id},
        manufacturer="Stiebel Eltron / Tecalor",
    )
    if area:
        info["suggested_area"] = area
    return info


def subdevice_identifier(device_id: str, subdevice: str) -> str:
    """Return the device registry identifier of a sub-device."""
    return f"{device_id}_{subdevice}"


def assign_subdevices(entities: Iterable[Any], data: Mapping[str, Any]) -> None:
    """Assign each entity its sub-device if the config entry enables the split.

    Must run before the entities are added, since Home Assistant reads
    ``device_info`` when it registers an entity.
    """
    if not data.get(CONF_SPLIT_DEVICES, False):
        return
    name = main_device_name(data)
    area = data.get("area") or None
    for entity in entities:
        unique_id = getattr(entity, "unique_id", None) or ""
        entity._subdevice = subdevice_for(unique_id, entity._device_id)
        entity._subdevice_device_name = name
        entity._subdevice_area = area


def _subdevice_entries(
    hass: HomeAssistant, config_entry: ConfigEntry, device_id: str
) -> list[dr.DeviceEntry]:
    identifiers = {
        (DOMAIN, subdevice_identifier(device_id, group)) for group in SUBDEVICES
    }
    return [
        device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), config_entry.entry_id
        )
        if device.identifiers & identifiers
    ]


@callback
def async_release_subdevices(
    hass: HomeAssistant, config_entry: ConfigEntry, device_id: str, main_id: str
) -> None:
    """Move every entity back to the heat pump and remove the sub-devices.

    Used when the split is disabled. Removing a device also removes the
    entity registry entries still linked to it, so the entities are moved
    first; their names, areas and enabled state are kept.
    """
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    for device in _subdevice_entries(hass, config_entry, device_id):
        for entity in er.async_entries_for_device(
            entity_reg, device.id, include_disabled_entities=True
        ):
            entity_reg.async_update_entity(entity.entity_id, device_id=main_id)
        device_reg.async_remove_device(device.id)


@callback
def async_remove_empty_subdevices(
    hass: HomeAssistant, config_entry: ConfigEntry, device_id: str
) -> None:
    """Remove sub-devices left without entities, e.g. after a group change."""
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    for device in _subdevice_entries(hass, config_entry, device_id):
        if not er.async_entries_for_device(
            entity_reg, device.id, include_disabled_entities=True
        ):
            device_reg.async_remove_device(device.id)

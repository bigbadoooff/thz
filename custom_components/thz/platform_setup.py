"""Platform setup helpers for THZ integration.

This module provides common setup logic to reduce boilerplate code
across entity platforms.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .thz_device import THZDevice
    from .register_maps.register_map_manager import RegisterMapManagerWrite

_LOGGER = logging.getLogger(__name__)


async def async_setup_write_platform(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entity_type: type,
    platform_type: str,
    entity_factory: Callable | None = None,
) -> None:
    """Generic setup for write platforms (number, switch, select, time).

    This function consolidates the common setup logic used by all write-based
    entity platforms, reducing code duplication.

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry that triggered this setup.
        async_add_entities: Callback function to register new entities.
        entity_type: The entity class to instantiate (e.g., THZNumber, THZSwitch).
        platform_type: The type filter for register entries (e.g., "number", "switch").
        entity_factory: Optional custom factory function for creating entities.
                       If provided, called with (name, entry, device, device_id, write_interval)
                       and should return a list of entities.
    """
    write_manager: RegisterMapManagerWrite = hass.data[DOMAIN]["write_manager"]
    device: THZDevice = hass.data[DOMAIN]["device"]
    device_id = hass.data[DOMAIN]["device_id"]

    # Get write interval from config, default to DEFAULT_UPDATE_INTERVAL
    write_interval = config_entry.data.get("write_interval", DEFAULT_UPDATE_INTERVAL)

    write_registers = write_manager.get_all_registers()
    _LOGGER.debug(
        "Loading %s platform with %d registers", platform_type, len(write_registers)
    )

    entities = []
    for name, entry in write_registers.items():
        if entry["type"] == platform_type:
            _LOGGER.debug(
                "Creating %s for %s with command %s",
                entity_type.__name__,
                name,
                entry["command"]
            )

            # Use custom factory if provided, otherwise use default
            if entity_factory:
                new_entities = entity_factory(name, entry, device, device_id, write_interval)
                entities.extend(new_entities if isinstance(new_entities, list) else [new_entities])
            else:
                # Create entity instance with common parameters
                entity = entity_type(
                    name=name,
                    entry=entry,
                    device=device,
                    device_id=device_id,
                    scan_interval=write_interval,
                )
                entities.append(entity)

    _LOGGER.info("Created %d %s entities", len(entities), platform_type)
    async_add_entities(entities, True)


def get_device_from_hass(hass: HomeAssistant) -> THZDevice:
    """Safely get device from hass.data.

    Args:
        hass: The Home Assistant instance.

    Returns:
        The THZ device instance.

    Raises:
        KeyError: If device is not initialized in hass.data.
    """
    try:
        return hass.data[DOMAIN]["device"]
    except KeyError as e:
        _LOGGER.error("Device not initialized in hass.data: %s", e)
        raise


def get_entry_data(hass: HomeAssistant, config_entry: ConfigEntry) -> dict:
    """Safely get entry data from hass.data.

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry.

    Returns:
        The entry data dictionary.

    Raises:
        KeyError: If entry data is not found in hass.data.
    """
    try:
        return hass.data[DOMAIN][config_entry.entry_id]
    except KeyError as e:
        _LOGGER.error("Entry data not found for %s: %s", config_entry.entry_id, e)
        raise

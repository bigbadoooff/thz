"""Platform setup helpers for THZ integration.

This module provides common setup logic to reduce boilerplate code
across entity platforms.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from ._typing_compat import get_runtime_data
from .const import DEFAULT_UPDATE_INTERVAL, get_write_group_for_key

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
                       If provided, called with
                       (name, entry, device, device_id, write_interval)
                       and should return a list of entities.
    """
    entry_data = get_runtime_data(config_entry)
    write_manager: RegisterMapManagerWrite = entry_data["write_manager"]
    device: THZDevice = entry_data["device"]
    device_id = entry_data["device_id"]

    # Get write interval from config, default to DEFAULT_UPDATE_INTERVAL
    write_interval = config_entry.data.get("write_interval", DEFAULT_UPDATE_INTERVAL)

    # Get selected write groups (if not set, all groups are enabled)
    selected_write_groups = config_entry.data.get("selected_write_groups")

    write_registers = write_manager.get_all_registers()
    _LOGGER.debug(
        "Loading %s platform with %d registers", platform_type, len(write_registers)
    )

    entities = []
    for name, entry in write_registers.items():
        if entry["type"] == platform_type:
            # Filter by selected write groups if configured
            if selected_write_groups is not None:
                group = get_write_group_for_key(name)
                if group not in selected_write_groups:
                    continue
            _LOGGER.debug(
                "Creating %s for %s with command %s",
                entity_type.__name__,
                name,
                entry["command"]
            )

            # Use custom factory if provided, otherwise use default
            if entity_factory:
                new_entities = entity_factory(
                    name, entry, device, device_id, write_interval
                )
                entities.extend(
                    new_entities if isinstance(new_entities, list) else [new_entities]
                )
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


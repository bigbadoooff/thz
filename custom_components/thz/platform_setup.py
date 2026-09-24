"""Platform setup helpers for THZ integration.

This module provides common setup logic to reduce boilerplate code
across entity platforms.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import (
    DEFAULT_WRITE_INTERVAL,
    get_write_group_for_key,
)
from .devices import assign_subdevices
from .runtime_data import THZConfigEntry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .register_maps.register_map_manager import RegisterMapManagerWrite
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_write_platform(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entity_type: type,
    platform_type: str,
) -> None:
    """Generic setup for write platforms (number, switch, select, button).

    This function consolidates the common setup logic used by all write-based
    entity platforms, reducing code duplication. (time.py has its own
    async_setup_entry since schedule entries split into two entities.)

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry that triggered this setup.
        async_add_entities: Callback function to register new entities.
        entity_type: The entity class to instantiate (e.g., THZNumber, THZSwitch).
        platform_type: The type filter for register entries (e.g., "number", "switch").
    """
    entry_data = config_entry.runtime_data
    write_manager: RegisterMapManagerWrite = entry_data.write_manager
    device: THZDevice = entry_data.device
    device_id = entry_data.device_id
    entity_id_style = entry_data.entity_id_style
    entity_visibility = entry_data.entity_visibility
    entity_id_prefix = entry_data.entity_id_prefix

    # Same default the config flow stores for new entries.
    write_interval = config_entry.data.get("write_interval", DEFAULT_WRITE_INTERVAL)

    # Get selected write groups (if not set, all groups are enabled)
    selected_write_groups = config_entry.data.get("selected_write_groups")

    params = write_manager.params()
    _LOGGER.debug("Loading %s platform with %d registers", platform_type, len(params))

    entities = []
    for name, entry in params.items():
        if entry.type == platform_type:
            # Filter by selected write groups if configured
            if selected_write_groups is not None:
                group = get_write_group_for_key(name)
                if group not in selected_write_groups:
                    continue
            _LOGGER.debug(
                "Creating %s for %s with command %s",
                entity_type.__name__,
                name,
                entry.command,
            )

            entity = entity_type(
                name=name,
                entry=entry,
                device=device,
                device_id=device_id,
                scan_interval=write_interval,
                entity_id_style=entity_id_style,
                entity_visibility=entity_visibility,
                entity_id_prefix=entity_id_prefix,
            )
            entity._coordinators = entry_data.coordinators
            entities.append(entity)

    _LOGGER.debug("Created %d %s entities", len(entities), platform_type)
    assign_subdevices(entities, config_entry.data)
    async_add_entities(entities, True)

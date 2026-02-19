"""Diagnostics support for THZ integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Keys to redact from diagnostics to protect user privacy
TO_REDACT = {
    "host",
    "device",
    "unique_id",
    "serial",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    This provides useful information for troubleshooting issues with the
    THZ integration without exposing sensitive data like IP addresses or
    serial numbers.
    """
    device = hass.data[DOMAIN]["device"]
    entry_data = hass.data[DOMAIN].get(config_entry.entry_id, {})
    coordinators = entry_data.get("coordinators", {})

    # Collect basic device information
    device_info = {
        "firmware_version": getattr(device, "firmware_version", "unknown"),
        "connection_type": getattr(device, "connection_type", "unknown"),
        "initialized": getattr(device, "_initialized", False),
        "last_access": str(getattr(device, "last_access", "never")),
    }

    # Collect coordinator information (without sensitive data)
    coordinator_info = {}
    for block_name, coordinator in coordinators.items():
        coordinator_info[block_name] = {
            "last_update_success": coordinator.last_update_success,
            "last_update_time": str(coordinator.last_update_success_time) if coordinator.last_update_success_time else None,
            "update_interval": str(coordinator.update_interval) if coordinator.update_interval else None,
            "data_length": len(coordinator.data) if coordinator.data else 0,
        }

    # Collect register information (counts only, no data)
    register_manager = hass.data[DOMAIN].get("register_manager")
    write_manager = hass.data[DOMAIN].get("write_manager")

    register_counts = {}
    if register_manager:
        all_registers = register_manager.get_all_registers()
        register_counts["read_blocks"] = len(all_registers)
        register_counts["read_sensors"] = sum(len(entries) for entries in all_registers.values())

    if write_manager:
        write_registers = write_manager.get_all_registers()
        register_counts["write_entities"] = len(write_registers)

        # Count by type
        type_counts = {}
        for entry in write_registers.values():
            entity_type = entry.get("type", "unknown")
            type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
        register_counts["write_entity_types"] = type_counts

    # Build diagnostics data
    diagnostics_data = {
        "config_entry": {
            "title": config_entry.title,
            "version": config_entry.version,
            "data": async_redact_data(config_entry.data, TO_REDACT),
        },
        "device": device_info,
        "coordinators": coordinator_info,
        "registers": register_counts,
    }

    return diagnostics_data

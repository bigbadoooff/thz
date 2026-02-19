"""Init file for THZ integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN, should_hide_entity_by_default
from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up THZ from config entry."""
    log_level_str = config_entry.data.get("log_level", "info")
    _LOGGER.setLevel(getattr(logging, log_level_str.upper(), logging.INFO))
    _LOGGER.info("Log level set to: %s", log_level_str)
    _LOGGER.debug(
        "THZ async_setup_entry called with entry: %s", config_entry.as_dict()
    )

    # Clean up any orphaned THZ entities from previous installations
    # This ensures a fresh start without ghost entities with broken names
    await _async_cleanup_orphaned_entities(hass)

    hass.data.setdefault(DOMAIN, {})

    data = config_entry.data
    conn_type = data["connection_type"]

    # 1. Initialize device
    if conn_type == "ip":
        device = THZDevice(connection="ip", host=data["host"], tcp_port=data["port"])
    elif conn_type == "usb":
        device = THZDevice(connection="usb", port=data["device"])
    else:
        raise ValueError("Invalid connection type")

    await device.async_initialize(hass)

    # 2. Query firmware version
    _LOGGER.info(
        "THZ device fully initialized (FW %s)", device.firmware_version
    )

    # --- create / update device in Home Assistant device registry using alias/area ---

    dev_reg = dr.async_get(hass)
    # prefer a stable id from the device; fall back to conn info
    unique_id = (
        getattr(device, "unique_id", None)
        or getattr(device, "serial", None)
        or f"{conn_type}-{data.get('host') or data.get('device')}"
    )
    device_name = data.get("alias") or f"THZ {data.get('host') or data.get('device')}"
    device_entry = dev_reg.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, unique_id)},
        name=device_name,
        manufacturer="Stiebel Eltron / Tecalor",
        model=f"LWZ/THZ (FW: {device.firmware_version})",
        sw_version=device.firmware_version,
        suggested_area=data.get("area"),
    )
    _LOGGER.debug("Device registry entry created/updated: %s", device_entry.id)

    # 3. Load register mappings
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["write_manager"] = device.write_register_map_manager
    hass.data[DOMAIN]["register_manager"] = device.register_map_manager

    # 4. Store device instance
    hass.data[DOMAIN]["device"] = device
    hass.data[DOMAIN]["device_id"] = unique_id

    # 5. Prepare dict for storing all coordinators
    coordinators = {}
    refresh_intervals = config_entry.data.get("refresh_intervals", {})

    # If refresh_intervals is empty or missing, populate with defaults
    # for all available blocks
    if not refresh_intervals:
        available_blocks = device.available_reading_blocks
        if available_blocks:
            _LOGGER.warning(
                "No refresh_intervals found in config, using default "
                "interval of %s seconds for %d blocks",
                DEFAULT_UPDATE_INTERVAL,
                len(available_blocks)
            )
            refresh_intervals = {
                block: DEFAULT_UPDATE_INTERVAL
                for block in available_blocks
            }
        else:
            _LOGGER.error(
                "No available reading blocks found on device "
                "and no refresh_intervals in config"
            )
            # Continue with empty dict - no coordinators or sensors will be created
    else:
        _LOGGER.debug(
            "Creating coordinators with refresh intervals: %s", refresh_intervals
        )

    # Create a coordinator for each block with its own interval
    for block, interval in refresh_intervals.items():
        _LOGGER.debug(
            "Creating coordinator for block %s with interval %s seconds",
            block, interval
        )
        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"THZ {block}",
            update_interval=timedelta(seconds=int(interval)),
            update_method=lambda b=block: _async_update_block(hass, device, b),
        )
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info(
            "Initial data fetch completed for block %s, data available: %s",
            block,
            coordinator.data is not None,
        )
        coordinators[block] = coordinator

    # Store in hass.data
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "device": device,
        "coordinators": coordinators,
    }

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(
        config_entry, ["sensor", "number", "switch", "select", "time"]
    )

    # Re-enable any entities that were previously disabled by the integration
    # This ensures the current code's visibility settings take precedence
    # over cached registry state
    await _async_enable_integration_disabled_entities(hass, config_entry)

    return True


async def _async_cleanup_orphaned_entities(hass: HomeAssistant) -> None:
    """Remove orphaned THZ entities from the entity registry.

    Orphaned entities are those with platform="thz" but config_entry_id=None.
    These can occur when the integration is deleted but HA doesn't fully clean up
    the entity registry entries, leaving "ghost" entities with broken names.
    """
    entity_reg = er.async_get(hass)
    orphaned_count = 0

    # Get all entities and filter for orphaned THZ entities
    for entity in list(entity_reg.entities.values()):
        if entity.platform == "thz" and entity.config_entry_id is None:
            entity_reg.async_remove(entity.entity_id)
            _LOGGER.debug("Removed orphaned THZ entity: %s", entity.entity_id)
            orphaned_count += 1

    if orphaned_count > 0:
        _LOGGER.info(
            "Cleaned up %d orphaned THZ entities from registry", orphaned_count
        )


async def _async_enable_integration_disabled_entities(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Sync entity registry state with current code's visibility settings.

    This function ensures the entity registry reflects the current code's visibility
    logic, overriding any cached state from previous code versions.

    It handles both directions:
    - Re-enables entities that should be visible but are cached as disabled
    - Disables entities that should be hidden but are cached as enabled
    - Updates entity names to match current code (clears cached name overrides)
    """
    entity_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)
    enabled_count = 0
    disabled_count = 0
    name_count = 0

    for entity in entities:
        # Get the entity's original name to check visibility
        entity_name = entity.original_name or ""
        should_hide = should_hide_entity_by_default(entity_name)

        # Sync visibility state
        if should_hide:
            # Entity should be hidden - disable if not already disabled by integration
            if entity.disabled_by != er.RegistryEntryDisabler.INTEGRATION:
                entity_reg.async_update_entity(
                    entity.entity_id,
                    disabled_by=er.RegistryEntryDisabler.INTEGRATION
                )
                _LOGGER.debug("Disabled entity %s (should be hidden)", entity.entity_id)
                disabled_count += 1
        else:
            # Entity should be visible - enable if disabled by integration
            if entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                entity_reg.async_update_entity(entity.entity_id, disabled_by=None)
                _LOGGER.debug(
                    "Re-enabled entity %s (should be visible)", entity.entity_id
                )
                enabled_count += 1

        # Sync entity name - clear any cached name override
        # to use current code's name
        if entity.name is not None:
            entity_reg.async_update_entity(entity.entity_id, name=None)
            _LOGGER.debug(
                "Reset entity name for %s to use original_name", entity.entity_id
            )
            name_count += 1

    if enabled_count > 0 or disabled_count > 0 or name_count > 0:
        _LOGGER.info(
            "Entity registry sync: enabled %d, disabled %d, reset %d names",
            enabled_count, disabled_count, name_count
        )


async def _async_update_block(hass: HomeAssistant, device: THZDevice, block_name: str):
    """Called by coordinator to read a data block."""
    block_bytes = bytes.fromhex(block_name.removeprefix("pxx"))
    try:
        _LOGGER.debug("Reading block %s", block_name)
        async with device.lock:
            return await hass.async_add_executor_job(device.read_block, block_bytes, "get")
    except Exception as err:
        raise UpdateFailed(f"Error reading {block_name}: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove Config Entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "select", "number", "time", "switch"]
    )
    if unload_ok:
        # Clean up device connection
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if entry_data:
            device = entry_data.get("device")
            if device:
                await hass.async_add_executor_job(device.close)
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device.

    This is called when a user manually removes a device from the UI.
    Return False to prevent removal if there's an issue.
    """
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry.

    This is called when the config entry is completely removed (not just unloaded).
    Clean up all entity registry entries to ensure a fresh start on re-setup.
    """
    # Get entity registry
    entity_reg = er.async_get(hass)

    # Get all entities for this config entry
    entities = er.async_entries_for_config_entry(entity_reg, entry.entry_id)

    # Remove all entities associated with this config entry
    for entity in entities:
        entity_reg.async_remove(entity.entity_id)
        _LOGGER.debug("Removed entity %s from registry", entity.entity_id)

    _LOGGER.info(
        "Removed %d entities from registry for config entry %s",
        len(entities),
        entry.entry_id,
    )

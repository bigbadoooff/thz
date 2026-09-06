"""Init file for THZ integration."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import timedelta
import logging
import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._typing_compat import get_runtime_data, set_runtime_data
from .clock_sync import async_setup_clock_check
from .const import (
    CONF_FIRMWARE_OVERRIDE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FIRMWARE_OVERRIDE_AUTO,
    should_hide_entity_by_default,
)
from .services import async_refresh_block as async_refresh_block
from .services import async_setup_services
from .thz_device import THZDevice, THZRegisterNotSupportedError

_LOGGER = logging.getLogger(__name__)

# Entity platforms forwarded to/unloaded from this config entry
PLATFORMS = [
    "sensor", "binary_sensor", "number", "switch", "select", "time",
    "button", "climate",
]


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

    data = config_entry.data
    conn_type = data["connection_type"]
    firmware_override = data.get(CONF_FIRMWARE_OVERRIDE, FIRMWARE_OVERRIDE_AUTO)

    # 1. Initialize device
    if conn_type == "ip":
        device = THZDevice(
            connection="ip",
            host=data["host"],
            tcp_port=data["port"],
            firmware_override=firmware_override,
        )
    elif conn_type == "usb":
        device = THZDevice(
            connection="usb",
            port=data["device"],
            firmware_override=firmware_override,
        )
    else:
        raise ValueError("Invalid connection type")

    try:
        await device.async_initialize(hass)
    except OSError as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to THZ device ({err}); will retry"
        ) from err

    # 2. Query firmware version
    _LOGGER.info(
        "THZ device fully initialized (FW %s)", device.firmware_version
    )

    # --- create / update device in Home Assistant device registry ---

    dev_reg = dr.async_get(hass)
    # prefer a stable id from the device; fall back to conn info
    unique_id = (
        getattr(device, "unique_id", None)
        or getattr(device, "serial", None)
        or f"{conn_type}-{data.get('host') or data.get('device')}"
    )
    device_name = data.get("alias") or f"THZ {data.get('host') or data.get('device')}"
    kwargs: dict = {
        "config_entry_id": config_entry.entry_id,
        "identifiers": {(DOMAIN, unique_id)},
        "name": device_name,
        "manufacturer": "Stiebel Eltron / Tecalor",
        "model": f"LWZ/THZ (FW: {device.firmware_version})",
        "sw_version": device.firmware_version,
    }
    area = data.get("area")
    if area:
        kwargs["suggested_area"] = area
    device_entry = dev_reg.async_get_or_create(**kwargs)
    _LOGGER.debug("Device registry entry created/updated: %s", device_entry.id)

    # 3. Load register mappings (local vars; stored per entry below)
    write_manager = device.write_register_map_manager
    register_manager = device.register_map_manager

    # 5. Collect paired register blocks for energy sensors (cmd2 + cmd3)
    paired_blocks = register_manager.get_paired_blocks() if register_manager else {}
    if paired_blocks:
        _LOGGER.debug(
            "Paired register blocks for dual-read: %s", paired_blocks
        )

    # 6. Prepare dict for storing all coordinators
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

    def _make_update_method(
        block_name: str,
    ) -> Callable[[], Coroutine[Any, Any, bytes | None]]:
        async def _update() -> bytes | None:
            return await _async_update_block(hass, device, block_name, paired_blocks)

        return _update

    # Create a coordinator for each block with its own interval
    unsupported_blocks: set[str] = set()
    for block, interval in refresh_intervals.items():
        _LOGGER.debug(
            "Creating coordinator for block %s with interval %s seconds",
            block, interval
        )
        # Add per-coordinator jitter (up to 10 % of the interval, min 5 s) so
        # that all coordinators do not fire at the same wall-clock second after
        # the first period expires, avoiding lock contention thundering herds.
        jitter = random.uniform(0, max(int(interval) * 0.10, 5))
        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"THZ {block}",
            update_interval=timedelta(seconds=int(interval) + jitter),
            update_method=_make_update_method(block),
        )
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady as exc:
            # A block-level failure (unsupported register, transient decode error,
            # etc.) should not abort the entire config entry setup — the device
            # connection was already verified above.  Mark the block as unsupported
            # so no entities are created for it; do not add it to coordinators so
            # it is not polled again.
            unsupported_blocks.add(block)
            _LOGGER.warning(
                "Block %s could not be read at startup (%s); "
                "no entities will be created for it.",
                block, exc,
            )
            continue
        if coordinator.data is None:
            unsupported_blocks.add(block)
            _LOGGER.info(
                "Block %s is unsupported on this firmware; "
                "no entities will be created for it.",
                block,
            )
        else:
            _LOGGER.info(
                "Initial data fetch completed for block %s", block
            )
        coordinators[block] = coordinator

    # Store per-entry runtime state on the config entry itself (not hass.data),
    # per HA's recommended runtime-data pattern.
    set_runtime_data(config_entry, {
        "device": device,
        "device_id": unique_id,
        "write_manager": write_manager,
        "register_manager": register_manager,
        "coordinators": coordinators,
        "unsupported_blocks": unsupported_blocks,
    })

    # Periodic clock-drift check (independent of per-entity polling of the
    # individual pClock* registers — see clock_sync.py). Always runs so
    # drift is logged; only writes a correction back to the device when the
    # "auto_sync_clock" option is enabled.
    entry_data = get_runtime_data(config_entry)
    entry_data["unsub_clock_check"] = async_setup_clock_check(
        hass, config_entry, device, write_manager
    )

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(
        config_entry,
        PLATFORMS,
    )

    # One-time migration: disable entities that should be hidden by default
    # (program schedules, HC2, advanced parameters) for users upgrading from
    # older versions where these entities were registered as enabled.
    await _async_migrate_disable_hidden_entities(hass, config_entry)

    # Register services
    await async_setup_services(hass)

    return True


async def _async_migrate_disable_hidden_entities(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """One-time migration: disable entities that should be hidden by default.

    When upgrading from older versions, program/schedule, HC2, and advanced
    parameter entities may already be registered as enabled. This migration
    disables them once so they no longer clutter the UI.

    Entities explicitly re-enabled by the user afterwards will stay enabled
    because the migration only runs once (guarded by a stored flag).

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry to migrate entities for.
    """
    if config_entry.data.get("_hidden_entities_migrated"):
        return

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    disabled_count = 0

    for entity_entry in entries:
        # Check unique_id for program/hc2 patterns (most reliable identifier)
        uid = (entity_entry.unique_id or "").lower()
        name = (entity_entry.original_name or entity_entry.name or "").lower()

        should_hide = (
            should_hide_entity_by_default(uid)
            or should_hide_entity_by_default(name)
            or "program" in uid
        )

        if should_hide and entity_entry.disabled_by is None:
            # RegistryEntryDisabler members are mistyped as plain `str` in
            # some older homeassistant-stubs snapshots; not a real type error.
            disabler: er.RegistryEntryDisabler = (
                er.RegistryEntryDisabler.INTEGRATION  # type: ignore[assignment]
            )
            ent_reg.async_update_entity(
                entity_entry.entity_id,
                disabled_by=disabler,
            )
            disabled_count += 1
            _LOGGER.debug(
                "Migration: disabled hidden entity %s (uid=%s)",
                entity_entry.entity_id,
                entity_entry.unique_id,
            )

    if disabled_count:
        _LOGGER.info(
            "Migration: disabled %d program/HC2/advanced entities", disabled_count
        )

    # Store flag so this migration only runs once
    hass.config_entries.async_update_entry(
        config_entry,
        data={**config_entry.data, "_hidden_entities_migrated": True},
    )


async def _async_cleanup_orphaned_entities(hass: HomeAssistant) -> None:
    """Remove orphaned THZ entities from the entity registry.

    An entity is orphaned if it has platform="thz" and its config_entry_id
    either is None, or no longer refers to any config entry that actually
    exists. Both cases can occur when the integration is deleted:

    - config_entry_id=None: HA nulled the reference out (the case this
      function originally handled).
    - config_entry_id=<stale id>: HA left the entity pointing at the
      now-deleted entry's id instead of nulling it. This is the more common
      case in practice, and the original None-only check missed it entirely
      -- the entity registry row (including its unique_id) survives every
      "Delete integration" cycle, and the *next* time the integration is
      added, entity_registry.async_get_or_create() matches the pre-existing
      unique_id and silently reattaches to this same old, stale row instead
      of creating a fresh one for the new config entry.
    """
    entity_reg = er.async_get(hass)
    orphaned_count = 0

    # Get all entities and filter for orphaned THZ entities
    for entity in list(entity_reg.entities.values()):
        if entity.platform != "thz":
            continue
        config_entry_id = entity.config_entry_id
        is_orphaned = config_entry_id is None or (
            hass.config_entries.async_get_entry(config_entry_id) is None
        )
        if is_orphaned:
            entity_reg.async_remove(entity.entity_id)
            _LOGGER.debug("Removed orphaned THZ entity: %s", entity.entity_id)
            orphaned_count += 1

    if orphaned_count > 0:
        _LOGGER.info(
            "Cleaned up %d orphaned THZ entities from registry", orphaned_count
        )


async def _async_update_block(
    hass: HomeAssistant,
    device: THZDevice,
    block_name: str,
    paired_blocks: dict[str, str] | None = None,
) -> bytes | None:
    """Called by coordinator to read a data block.

    For paired register blocks (energy sensors), both the cmd2 and cmd3
    registers are read and combined following the FHEM convention:
        combined = cmd3_value * 1000 + cmd2_value
    The result is stored as a 4-byte signed integer at the sensor offset
    so that the sensor entity can decode it transparently.
    """
    block_bytes = bytes.fromhex(block_name.removeprefix("pxx"))
    try:
        _LOGGER.debug("Reading block %s", block_name)
        result: bytes = await device.async_execute(
            hass, device.read_block, block_bytes, "get"
        )

        # If this block has a paired cmd3 register, read it too
        if paired_blocks and block_name in paired_blocks:
            cmd3_name = paired_blocks[block_name]
            cmd3_bytes = bytes.fromhex(cmd3_name.removeprefix("pxx"))
            cmd3_result = await device.async_execute(
                hass, device.read_block, cmd3_bytes, "get"
            )

            # Extract low (cmd2) and high (cmd3) values
            # Both are signed 16-bit integers at byte offset 4
            low_val = int.from_bytes(
                result[4:6], byteorder="big", signed=True
            )
            high_val = int.from_bytes(
                cmd3_result[4:6], byteorder="big", signed=True
            )
            combined = high_val * 1000 + low_val

            _LOGGER.debug(
                "Paired read %s: low=%s, high=%s (%s), combined=%s",
                block_name, low_val, high_val, cmd3_name, combined,
            )

            # Build payload with 4-byte combined value at offset 4
            buf = bytearray(max(len(result) + 2, 8))
            buf[: len(result)] = result
            buf[4:8] = combined.to_bytes(4, byteorder="big", signed=True)
            result = bytes(buf)

        return result
    except THZRegisterNotSupportedError:
        # Device permanently doesn't support this block — return None so the
        # coordinator marks the block as unsupported without triggering a reconnect
        # or raising UpdateFailed (which would propagate as ConfigEntryNotReady).
        _LOGGER.info(
            "Block %s is not supported by this device firmware; skipping.", block_name
        )
        return None
    except Exception as err:  # noqa: BLE001
        raise UpdateFailed(f"Error reading {block_name}: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove Config Entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Clean up device connection
        entry_data = get_runtime_data(entry)
        if entry_data:
            unsub_clock_check = entry_data.get("unsub_clock_check")
            if unsub_clock_check:
                unsub_clock_check()
            device = entry_data.get("device")
            if device:
                await hass.async_add_executor_job(device.close)

        # Remove services if this is the last config entry
        remaining_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining_entries:
            _LOGGER.debug("Removing THZ services (last config entry)")
            hass.services.async_remove(DOMAIN, "read_raw_register")
            hass.services.async_remove(DOMAIN, "scan_raw_registers")
            hass.services.async_remove(DOMAIN, "watch_raw_registers_changes")
            hass.services.async_remove(DOMAIN, "refresh_block")
            hass.services.async_remove(DOMAIN, "set_diverter_valve")
            hass.services.async_remove(DOMAIN, "backup_parameters")
            hass.services.async_remove(DOMAIN, "restore_parameters")
            hass.services.async_remove(DOMAIN, "list_parameter_backups")

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

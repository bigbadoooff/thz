"""Init file for THZ integration."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, time as dt_time
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    WRITE_REGISTER_LENGTH,
    WRITE_REGISTER_OFFSET,
    should_hide_entity_by_default,
)
from .thz_device import THZDevice
from .time import quarters_to_time, time_to_quarters
from .value_codec import THZValueCodec

_LOGGER = logging.getLogger(__name__)

# Hex dump formatting constants
BYTES_PER_HEX_LINE = 16  # Number of bytes to display per line in hex dumps

# Parameter backup/restore constants
BACKUP_SUBDIR = "thz_backups"
# Register types that hold a persistent, restorable value. "button" is a
# one-shot action with no state, and "ptime" is a legacy/unused type not
# consumed by any current platform, so neither is backed up.
_RESTORABLE_REGISTER_TYPES = {"number", "switch", "select", "time", "schedule"}

# The device's real-time clock is exposed as five plain "pclean" registers
# (day/month/year/hour/minute) that no platform claims as an entity, NOT as
# a "time"-typed register. They are handled specially by backup/restore/the
# periodic clock check below rather than as ordinary numeric parameters:
# restoring an old backed-up clock value would set the heat pump's clock
# back to whenever the backup was taken, and pClockYear's declared min/max
# ("12".."20") is a stale bound that would otherwise get a real year like
# 26 clamped down to 20.
_CLOCK_REGISTER_NAMES = (
    "pClockYear", "pClockMonth", "pClockDay", "pClockHour", "pClockMinutes",
)
# Device clock has no seconds field, so a little rounding slop is expected;
# only flag/act on drift beyond these thresholds.
_CLOCK_DRIFT_WARN_SECONDS = 60  # periodic check: log + optionally auto-correct
_CLOCK_DRIFT_BACKUP_SECONDS = 3600  # backup: always auto-correct past this


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
    paired_blocks = register_manager.get_paired_blocks()
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

    # Create a coordinator for each block with its own interval
    unsupported_blocks: set[str] = set()
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
            update_method=lambda b=block: _async_update_block(
                hass, device, b, paired_blocks
            ),
        )
        await coordinator.async_config_entry_first_refresh()
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

    # Store in hass.data — all per-entry so multiple config entries don't collide
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "device": device,
        "device_id": unique_id,
        "write_manager": write_manager,
        "register_manager": register_manager,
        "coordinators": coordinators,
        "unsupported_blocks": unsupported_blocks,
    }

    # Periodic clock-drift check (independent of per-entity polling of the
    # individual pClock* registers — see _async_check_and_maybe_sync_clock).
    # Always runs so drift is logged; only writes a correction back to the
    # device when the "auto_sync_clock" option is enabled.
    async def _periodic_clock_check(_now=None) -> None:
        try:
            await _async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("THZ periodic clock check failed: %s", err)

    hass.data[DOMAIN][config_entry.entry_id]["unsub_clock_check"] = (
        async_track_time_interval(hass, _periodic_clock_check, timedelta(minutes=15))
    )

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(
        config_entry,
        ["sensor", "binary_sensor", "number", "switch", "select", "time", "button", "climate"],
    )

    # One-time migration: disable entities that should be hidden by default
    # (program schedules, HC2, advanced parameters) for users upgrading from
    # older versions where these entities were registered as enabled.
    await _async_migrate_disable_hidden_entities(hass, config_entry)

    # Register services
    await _async_setup_services(hass)

    return True


# ---------------------------------------------------------------------------
# 3-way diverter valve motor control
# Commands address the motor controller directly; the heat pump firmware does
# NOT auto-stop — the caller must send "off" once the valve has moved.
# ---------------------------------------------------------------------------
_VALVE_MOTOR_HEATING  = bytes.fromhex("0A0653")  # motor direction: heating circuit
_VALVE_MOTOR_DHW      = bytes.fromhex("0A0652")  # motor direction: DHW (warm water)
_VALVE_MOTOR_ON       = bytes.fromhex("0001")     # engage motor
_VALVE_MOTOR_OFF      = bytes.fromhex("0000")     # stop motor

# Safety source: diverterValve bit in pxxF2 block (nibble 23 → byte 11, bit 2).
# Bit = 1 means the heat pump has switched flow to DHW → physically safe to move
# the valve toward DHW.  Bit = 0 means heating circuit is active → refuse.
_DIVERTER_BLOCK = "pxxF2"
_DIVERTER_BYTE  = 11   # nibble 23 // 2
_DIVERTER_BIT   = 2    # from decode_type "bit2"


def _normalize_block_name(block: str) -> str:
    """Normalise a block name to the coordinator key format ``pxxXX``.

    Accepts any of: ``"FB"``, ``"fb"``, ``"pxxFB"``, ``"0xFB"``, ``"0A0176"``.
    Always returns lowercase ``pxx`` prefix with upper-cased hex suffix.
    """
    b = block.strip()
    if b.lower().startswith("0x"):
        b = b[2:]
    if b.lower().startswith("pxx"):
        b = b[3:]
    return f"pxx{b.upper()}"


async def async_refresh_block(
    hass: HomeAssistant,
    block: str,
    entry_id: str | None = None,
) -> bool:
    """Force-refresh a specific block coordinator from the device.

    Triggers an immediate re-read of the named block and pushes updates to all
    entities that subscribe to that coordinator.

    Args:
        hass: The Home Assistant instance.
        block: Block name in any accepted form (``"FB"``, ``"pxxFB"``, etc.).
        entry_id: Config entry ID.  Required only when multiple THZ entries exist.

    Returns:
        ``True`` if at least one coordinator was refreshed, ``False`` otherwise.
    """
    normalized = _normalize_block_name(block)

    available_entries: dict[str, dict] = {
        eid: ed
        for eid, ed in hass.data.get(DOMAIN, {}).items()
        if isinstance(ed, dict) and "coordinators" in ed
    }

    if entry_id:
        entry_data = available_entries.get(entry_id)
        if entry_data is None:
            _LOGGER.error("async_refresh_block: no THZ entry for entry_id '%s'", entry_id)
            return False
        candidates = [entry_data]
    else:
        candidates = list(available_entries.values())

    found = False
    for entry_data in candidates:
        coordinator = entry_data["coordinators"].get(normalized)
        if coordinator is not None:
            await coordinator.async_request_refresh()
            _LOGGER.debug("Refreshed coordinator for block %s", normalized)
            found = True

    if not found:
        _LOGGER.warning("async_refresh_block: block '%s' not found in any coordinator", normalized)
    return found


# ---------------------------------------------------------------------------
# Parameter backup/restore helpers
# ---------------------------------------------------------------------------

def _backups_dir(hass: HomeAssistant) -> str:
    """Return the on-disk path of the parameter backups directory.

    This lives inside the HA config directory (``config/thz_backups``), so
    it is automatically swept up by Home Assistant's own Backup feature —
    creating an HA backup backs these files up too, and restoring one
    brings them back, with no extra steps.
    """
    return hass.config.path(BACKUP_SUBDIR)


def _sanitize_label(label: str | None) -> str:
    """Turn a user-supplied label into a safe filename suffix."""
    if not label:
        return ""
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label.strip())
    safe = safe.strip("_")
    return f"_{safe}" if safe else ""


def _parse_hhmm(value: str | None) -> dt_time | None:
    """Parse an ``"HH:MM"`` string (as stored in a backup) to a time, or None."""
    if not value:
        return None
    hour, minute = map(int, value.split(":"))
    return dt_time(hour, minute)


def _resolve_entry_data(
    hass: HomeAssistant, requested_entry_id: str | None
) -> tuple[dict | None, dict | None]:
    """Resolve the target THZ config entry's data dict.

    Mirrors the entry-lookup pattern used by the other THZ services. Returns
    ``(entry_data, error_response)`` — exactly one of the two is not None.
    """
    available_entries: dict[str, dict] = {
        eid: ed
        for eid, ed in hass.data.get(DOMAIN, {}).items()
        if isinstance(ed, dict) and "device" in ed
    }
    if requested_entry_id:
        entry_data = available_entries.get(requested_entry_id)
        if entry_data is None:
            return None, {
                "success": False,
                "error": f"No THZ entry found for entry_id '{requested_entry_id}'",
            }
        return entry_data, None
    if len(available_entries) > 1:
        return None, {
            "success": False,
            "error": (
                "Multiple THZ config entries found. "
                "Provide 'entry_id' to target a specific device."
            ),
        }
    if available_entries:
        return next(iter(available_entries.values())), None
    return None, {"success": False, "error": "THZ device not initialised"}


async def _async_read_device_clock(
    hass: HomeAssistant, device: THZDevice, write_manager
) -> datetime | None:
    """Read the device's current date/time from its 5 pClock* registers.

    Returns a naive datetime representing the device's own wall-clock
    reading (no timezone concept on the device side), or None if any of the
    five registers is missing from the current register map or unreadable.
    """
    write_registers = write_manager.get_all_registers()
    parts: dict[str, int] = {}
    for name in _CLOCK_REGISTER_NAMES:
        entry = write_registers.get(name)
        if entry is None:
            return None
        async with device.lock:
            value_bytes = await hass.async_add_executor_job(
                device.read_value,
                bytes.fromhex(entry["command"]),
                "get",
                WRITE_REGISTER_OFFSET,
                WRITE_REGISTER_LENGTH,
            )
        if not value_bytes:
            return None
        try:
            parts[name] = int(
                THZValueCodec.decode_number(value_bytes, 1.0, entry["decode_type"])
            )
        except (ValueError, IndexError):
            return None
    try:
        return datetime(
            2000 + parts["pClockYear"],
            parts["pClockMonth"],
            parts["pClockDay"],
            parts["pClockHour"],
            parts["pClockMinutes"],
        )
    except (KeyError, ValueError):
        return None


async def _async_write_device_clock(
    hass: HomeAssistant, device: THZDevice, write_manager, when: datetime
) -> None:
    """Write ``when`` (a local wall-clock time) onto the 5 pClock* registers.

    Bypasses each register's declared min/max (pClockYear's in particular is
    a stale "12".."20" bound) since the value being written is always a
    freshly computed, valid current date/time component, never user input.
    """
    write_registers = write_manager.get_all_registers()
    values = {
        "pClockYear": when.year % 100,
        "pClockMonth": when.month,
        "pClockDay": when.day,
        "pClockHour": when.hour,
        "pClockMinutes": when.minute,
    }
    for name, value in values.items():
        entry = write_registers.get(name)
        if entry is None:
            continue
        value_bytes = THZValueCodec.encode_number(value, 1.0, entry["decode_type"])
        async with device.lock:
            await hass.async_add_executor_job(
                device.write_value, bytes.fromhex(entry["command"]), value_bytes
            )


async def _async_check_and_maybe_sync_clock(
    hass: HomeAssistant, config_entry: ConfigEntry, device: THZDevice, write_manager
) -> None:
    """Periodic check: log clock drift, and auto-correct it if opted in.

    Runs on a fixed timer (see async_setup_entry) independently of the
    per-entity polling of the individual pClock* registers, so all five
    components are read together as one consistent snapshot rather than
    at whatever moments their individual polls happen to land.
    """
    device_dt = await _async_read_device_clock(hass, device, write_manager)
    if device_dt is None:
        return
    local_now = dt_util.now().replace(tzinfo=None, second=0, microsecond=0)
    drift = (device_dt - local_now).total_seconds()
    if abs(drift) <= _CLOCK_DRIFT_WARN_SECONDS:
        return
    _LOGGER.warning(
        "THZ device clock drifted %.0f minute(s) from local time "
        "(device=%s, local=%s)",
        drift / 60, device_dt, local_now,
    )
    if config_entry.data.get("auto_sync_clock", False):
        await _async_write_device_clock(hass, device, write_manager, local_now)
        _LOGGER.info("THZ device clock auto-corrected to %s", local_now)
        return

    # auto_sync_clock is off, so this drift can't be corrected automatically.
    # Surface it to the user — but at most once per calendar day, since this
    # check runs every 15 minutes and a persistently-drifted clock would
    # otherwise spam a fresh notification ~96 times a day.
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    today = dt_util.now().date()
    if entry_data is not None and entry_data.get("_clock_notify_date") == today:
        return
    if entry_data is not None:
        entry_data["_clock_notify_date"] = today
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "THZ Device Clock Drifted",
            "message": (
                f"The heat pump's clock is off by about {abs(drift) / 60:.0f} "
                f"minute(s) (device reads {device_dt.strftime('%Y-%m-%d %H:%M')}, "
                f"local time is {local_now.strftime('%Y-%m-%d %H:%M')}).\n\n"
                "Auto-sync clock is turned off, so this wasn't corrected "
                "automatically. Enable it under the integration's "
                "Reconfigure screen to fix this going forward."
            ),
            "notification_id": f"thz_clock_drift_{config_entry.entry_id}",
        },
        blocking=True,
    )


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the THZ integration.

    Registers the read_raw_register service that allows users to read
    raw register data from the heatpump for debugging purposes.
    This function is idempotent and will only register services once.
    """
    # Only register services once (check if already registered)
    if hass.services.has_service(DOMAIN, "read_raw_register"):
        return

    async def _async_handle_read_raw_register(call: ServiceCall) -> ServiceResponse:
        """Handle the read_raw_register service call.

        This service reads a raw register/block from the heatpump and returns
        the hex dump. It's useful for debugging firmware-specific register issues.

        Args:
            call: The service call with command field containing hex string

        Returns:
            ServiceResponse dict with command, length, hex, and formatted fields
        """
        command_str = call.data.get("command", "").strip().upper()
        requested_entry_id: str | None = call.data.get("entry_id")

        # Validate hex string
        try:
            command_bytes = bytes.fromhex(command_str)
        except ValueError as err:
            error_msg = f"Invalid hex command: {command_str} - {err}"
            _LOGGER.error(error_msg)
            # Create persistent notification for the error
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "THZ Raw Register Read Error",
                    "message": error_msg,
                    "notification_id": f"thz_raw_{command_str}",
                },
                blocking=True,
            )
            return {
                "success": False,
                "error": error_msg,
                "command": command_str,
            }

        # Locate the target device.  With a single entry no entry_id is needed.
        # With multiple entries, entry_id is required — return an error if omitted.
        available_entries: dict[str, dict] = {
            eid: ed
            for eid, ed in hass.data.get(DOMAIN, {}).items()
            if isinstance(ed, dict) and "device" in ed
        }

        device = None
        if requested_entry_id:
            entry_data_for_cmd = available_entries.get(requested_entry_id)
            if entry_data_for_cmd is None:
                error_msg = (
                    f"No THZ entry found for entry_id '{requested_entry_id}'"
                )
                _LOGGER.error(error_msg)
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "THZ Raw Register Read Error",
                        "message": error_msg,
                        "notification_id": f"thz_raw_{command_str}",
                    },
                    blocking=True,
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "command": command_str,
                }
            device = entry_data_for_cmd["device"]
        elif len(available_entries) > 1:
            error_msg = (
                "Multiple THZ config entries found. "
                "Provide 'entry_id' to target a specific device."
            )
            _LOGGER.error(error_msg)
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "THZ Raw Register Read Error",
                    "message": error_msg,
                    "notification_id": f"thz_raw_{command_str}",
                },
                blocking=True,
            )
            return {
                "success": False,
                "error": error_msg,
                "command": command_str,
            }
        elif available_entries:
            device = next(iter(available_entries.values()))["device"]
        if not device:
            error_msg = "THZ device not initialized"
            _LOGGER.error(error_msg)
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "THZ Raw Register Read Error",
                    "message": error_msg,
                    "notification_id": f"thz_raw_{command_str}",
                },
                blocking=True,
            )
            return {
                "success": False,
                "error": error_msg,
                "command": command_str,
            }

        # Read the register with device lock
        try:
            _LOGGER.info("Reading raw register: %s", command_str)
            async with device.lock:
                data = await hass.async_add_executor_job(
                    device.read_block, command_bytes, "get"
                )

            # Format the hex dump with offsets (BYTES_PER_HEX_LINE bytes per line)
            formatted_lines = []
            for i in range(0, len(data), BYTES_PER_HEX_LINE):
                chunk = data[i : i + BYTES_PER_HEX_LINE]
                hex_str = " ".join(f"{b:02x}" for b in chunk)
                formatted_lines.append(f"  {i:04x}: {hex_str}")
            formatted = "\n".join(formatted_lines)

            hex_string = data.hex()

            # Log the result
            _LOGGER.info(
                "Raw register %s read successfully (%d bytes):\n%s",
                command_str,
                len(data),
                formatted
            )

            # Create persistent notification with the result
            notification_message = (
                f"Command: {command_str}\n"
                f"Length: {len(data)} bytes\n"
                f"Hex: {hex_string}\n\n"
                f"Formatted:\n{formatted}"
            )

            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"THZ Raw Register Read: {command_str}",
                    "message": notification_message,
                    "notification_id": f"thz_raw_{command_str}",
                },
                blocking=True,
            )

            # Return service response
            return {
                "success": True,
                "command": command_str,
                "length": len(data),
                "hex": hex_string,
                "formatted": formatted,
            }

        except Exception as err:  # noqa: BLE001
            error_msg = f"Error reading register {command_str}: {err}"
            _LOGGER.error(error_msg, exc_info=True)
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "THZ Raw Register Read Error",
                    "message": error_msg,
                    "notification_id": f"thz_raw_{command_str}",
                },
                blocking=True,
            )
            return {
                "success": False,
                "error": str(err),
                "command": command_str,
            }

    async def _async_handle_refresh_block(call: ServiceCall) -> ServiceResponse:
        """Handle the refresh_block service call."""
        block = call.data.get("block", "").strip()
        requested_entry_id: str | None = call.data.get("entry_id")

        if not block:
            return {"success": False, "error": "block parameter is required"}

        normalized = _normalize_block_name(block)
        found = await async_refresh_block(hass, block, requested_entry_id)

        if found:
            _LOGGER.info("Service refresh_block: refreshed %s", normalized)
            return {"success": True, "block": normalized}

        error_msg = f"Block '{normalized}' not found in any active coordinator"
        _LOGGER.warning(error_msg)
        return {"success": False, "error": error_msg, "block": normalized}

    async def _async_handle_set_diverter_valve(call: ServiceCall) -> ServiceResponse:
        """Handle the set_diverter_valve service call.

        Moves the 3-way diverter valve motor toward the requested position.
        The motor does NOT auto-stop; send position="off" once the valve has moved.

        For the "dhw" position the diverterValve bit in pxxF2 is checked first:
        the heat pump must already be directing flow to DHW, otherwise the command
        is refused to prevent DHW water from running through the heating circuit.
        """
        position: str = call.data["position"]
        requested_entry_id: str | None = call.data.get("entry_id")

        # Locate entry (same pattern as other services)
        available_entries: dict[str, dict] = {
            eid: ed
            for eid, ed in hass.data.get(DOMAIN, {}).items()
            if isinstance(ed, dict) and "device" in ed
        }

        if requested_entry_id:
            entry_data = available_entries.get(requested_entry_id)
            if entry_data is None:
                return {"success": False, "error": f"No THZ entry for entry_id '{requested_entry_id}'"}
        elif len(available_entries) > 1:
            return {
                "success": False,
                "error": "Multiple THZ entries found. Provide 'entry_id' to target a specific device.",
            }
        elif available_entries:
            entry_data = next(iter(available_entries.values()))
        else:
            return {"success": False, "error": "THZ device not initialised"}

        # Safety guard: no valve movement in the wrong direction under pressure.
        # diverterValve bit = 1 → flow is to DHW; bit = 0 → flow is to heating circuit.
        # Moving the valve against the active flow direction is refused.
        if position in ("dhw", "heating"):
            coordinator = entry_data.get("coordinators", {}).get(_DIVERTER_BLOCK)
            if coordinator is None or coordinator.data is None:
                return {
                    "success": False,
                    "error": f"Cannot verify valve state: {_DIVERTER_BLOCK} coordinator data not available",
                }
            data: bytes = coordinator.data
            if len(data) <= _DIVERTER_BYTE:
                return {"success": False, "error": f"Insufficient data from {_DIVERTER_BLOCK} block"}
            diverter_active = bool((data[_DIVERTER_BYTE] >> _DIVERTER_BIT) & 0x01)
            if position == "dhw" and not diverter_active:
                return {
                    "success": False,
                    "error": (
                        "Heat pump is not in DHW mode (diverterValve bit = 0 in pxxF2). "
                        "Moving valve to DHW refused — heating circuit is under pressure."
                    ),
                }
            if position == "heating" and diverter_active:
                return {
                    "success": False,
                    "error": (
                        "Heat pump is in DHW mode (diverterValve bit = 1 in pxxF2). "
                        "Moving valve to heating refused — DHW circuit is under pressure."
                    ),
                }

        device: THZDevice = entry_data["device"]

        async def _stop_and_verify() -> bool:
            """Stop both motor directions, read back to confirm, retry once if not zero."""
            async with device.lock:
                await hass.async_add_executor_job(
                    device.write_value, _VALVE_MOTOR_HEATING, _VALVE_MOTOR_OFF
                )
                await hass.async_add_executor_job(
                    device.write_value, _VALVE_MOTOR_DHW, _VALVE_MOTOR_OFF
                )
                h_state = await hass.async_add_executor_job(
                    device.read_value, _VALVE_MOTOR_HEATING, "get",
                    WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH,
                )
                d_state = await hass.async_add_executor_job(
                    device.read_value, _VALVE_MOTOR_DHW, "get",
                    WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH,
                )

            if h_state != _VALVE_MOTOR_OFF or d_state != _VALVE_MOTOR_OFF:
                _LOGGER.warning(
                    "Diverter valve motor not confirmed off (heating=%s dhw=%s), retrying stop",
                    h_state.hex(), d_state.hex(),
                )
                async with device.lock:
                    await hass.async_add_executor_job(
                        device.write_value, _VALVE_MOTOR_HEATING, _VALVE_MOTOR_OFF
                    )
                    await hass.async_add_executor_job(
                        device.write_value, _VALVE_MOTOR_DHW, _VALVE_MOTOR_OFF
                    )
                return False

            return True

        try:
            # Send the motor ON command
            async with device.lock:
                if position == "heating":
                    await hass.async_add_executor_job(
                        device.write_value, _VALVE_MOTOR_HEATING, _VALVE_MOTOR_ON
                    )
                elif position == "dhw":
                    await hass.async_add_executor_job(
                        device.write_value, _VALVE_MOTOR_DHW, _VALVE_MOTOR_ON
                    )

            # Auto-stop after 3 seconds (lock released during wait so coordinators can poll)
            if position in ("heating", "dhw"):
                await asyncio.sleep(3)

            # Stop and verify — runs for explicit "off" too
            confirmed = await _stop_and_verify()

        except (RuntimeError, ConnectionError, OSError) as err:
            error_msg = f"Error sending diverter valve command: {err}"
            _LOGGER.error(error_msg)
            return {"success": False, "error": error_msg}

        _LOGGER.info("Diverter valve command sent: position=%s confirmed_off=%s", position, confirmed)
        return {"success": True, "position": position, "confirmed_off": confirmed}

    async def _async_handle_backup_parameters(call: ServiceCall) -> ServiceResponse:
        """Handle the backup_parameters service call.

        Reads the live value of every writable parameter — number, switch,
        select, time and schedule registers — and writes a timestamped JSON
        snapshot under config/thz_backups/. That folder lives inside the HA
        config directory, so it rides along with Home Assistant's own
        Backup feature automatically: no separate export/import step needed
        to keep the snapshot safe. restore_parameters is what actually pushes
        a saved snapshot's values back onto the physical heat pump — restoring
        an HA backup only restores files, it can't rewrite device registers.
        """
        requested_entry_id: str | None = call.data.get("entry_id")
        label: str | None = call.data.get("label")

        entry_data, error = _resolve_entry_data(hass, requested_entry_id)
        if error:
            _LOGGER.error("backup_parameters: %s", error["error"])
            return error

        write_manager = entry_data["write_manager"]
        device: THZDevice = entry_data["device"]
        device_id = entry_data["device_id"]
        entry_id_used = requested_entry_id or next(
            (eid for eid, ed in hass.data.get(DOMAIN, {}).items() if ed is entry_data),
            None,
        )

        write_registers = write_manager.get_all_registers()
        parameters: dict[str, dict] = {}
        read_errors: list[str] = []

        for name, entry in write_registers.items():
            reg_type = entry.get("type")
            if reg_type not in _RESTORABLE_REGISTER_TYPES:
                continue
            try:
                command = entry["command"]
                if reg_type == "schedule":
                    async with device.lock:
                        value_bytes = await hass.async_add_executor_job(
                            device.read_value, bytes.fromhex(command), "get", 4, 4
                        )
                    if not value_bytes or len(value_bytes) < 2:
                        raise ValueError("no data received")
                    start = quarters_to_time(value_bytes[0])
                    end = quarters_to_time(value_bytes[1])
                    value: Any = {
                        "start": start.strftime("%H:%M") if start else None,
                        "end": end.strftime("%H:%M") if end else None,
                    }
                else:
                    async with device.lock:
                        value_bytes = await hass.async_add_executor_job(
                            device.read_value,
                            bytes.fromhex(command),
                            "get",
                            WRITE_REGISTER_OFFSET,
                            WRITE_REGISTER_LENGTH,
                        )
                    if not value_bytes:
                        raise ValueError("no data received")

                    if reg_type == "number":
                        step_raw = entry.get("step", 1)
                        step = float(step_raw) if step_raw != "" else 1.0
                        value = THZValueCodec.decode_number(
                            value_bytes, step, entry["decode_type"]
                        )
                    elif reg_type == "switch":
                        value = THZValueCodec.decode_switch(value_bytes)
                    elif reg_type == "select":
                        value = THZValueCodec.decode_select(
                            value_bytes, entry.get("decode_type")
                        )
                    else:  # "time"
                        t = quarters_to_time(value_bytes[0])
                        value = t.strftime("%H:%M") if t else None

                parameters[name] = {"type": reg_type, "command": command, "value": value}
            except Exception as err:  # noqa: BLE001
                read_errors.append(f"{name}: {err}")
                _LOGGER.warning("backup_parameters: failed to read %s: %s", name, err)

        # Sanity-check the device's real-time clock against local time.
        # Backup is otherwise read-only, but a grossly wrong clock (over an
        # hour off — e.g. after a power loss or reset) throws off every
        # schedule the heat pump runs, so it's corrected here as a
        # deliberate exception. Smaller drift is left alone; that's what the
        # periodic auto_sync_clock check (1-minute threshold) is for.
        #
        # Read via _async_read_device_clock rather than pulling from
        # `parameters` above: the five pClock* registers are type "pclean"
        # (no platform claims that type as an entity), so they're never
        # added to `parameters` by the loop's _RESTORABLE_REGISTER_TYPES
        # filter — reading them back out of it here would always miss.
        clock_drift_seconds: float | None = None
        clock_corrected = False
        device_dt = await _async_read_device_clock(hass, device, write_manager)
        if device_dt is not None:
            local_now = dt_util.now().replace(tzinfo=None, second=0, microsecond=0)
            clock_drift_seconds = (device_dt - local_now).total_seconds()
            if abs(clock_drift_seconds) > _CLOCK_DRIFT_BACKUP_SECONDS:
                await _async_write_device_clock(hass, device, write_manager, local_now)
                clock_corrected = True
                _LOGGER.warning(
                    "backup_parameters: device clock was off by %.0f minute(s) "
                    "(device=%s, local=%s); corrected to local time.",
                    clock_drift_seconds / 60, device_dt, local_now,
                )
        else:
            _LOGGER.debug(
                "backup_parameters: could not read device clock to evaluate drift"
            )

        created = dt_util.utcnow().isoformat()
        backup_doc = {
            "created": created,
            "device_id": device_id,
            "entry_id": entry_id_used,
            "firmware_version": getattr(device, "firmware_version", None),
            "parameter_count": len(parameters),
            "parameters": parameters,
        }

        timestamp = dt_util.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"thz_backup_{timestamp}{_sanitize_label(label)}.json"

        def _write_backup_file() -> str:
            backups_dir = _backups_dir(hass)
            os.makedirs(backups_dir, exist_ok=True)
            path = os.path.join(backups_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(backup_doc, f, indent=2, sort_keys=True)
            return path

        try:
            path = await hass.async_add_executor_job(_write_backup_file)
        except OSError as err:
            error_msg = f"Failed to write backup file: {err}"
            _LOGGER.error(error_msg)
            return {"success": False, "error": error_msg}

        _LOGGER.info(
            "THZ backup_parameters: saved %d parameters to %s (%d read errors)",
            len(parameters), path, len(read_errors),
        )
        return {
            "success": True,
            "file": filename,
            "path": path,
            "parameter_count": len(parameters),
            "read_errors": read_errors[:20],
            "created": created,
            "clock_drift_seconds": clock_drift_seconds,
            "clock_corrected": clock_corrected,
        }

    async def _async_handle_restore_parameters(call: ServiceCall) -> ServiceResponse:
        """Handle the restore_parameters service call.

        Reads a JSON snapshot previously written by backup_parameters and
        pushes each value back onto the device. Every parameter's command
        and type are re-resolved from the *current* live register map by
        name — never trusted from the backup file itself — so a restore
        stays correct even if the integration's register map has changed
        since the backup was taken. Parameters no longer present are
        skipped and reported rather than failing the whole restore.
        """
        requested_entry_id: str | None = call.data.get("entry_id")
        requested_filename: str | None = call.data.get("filename")
        dry_run: bool = bool(call.data.get("dry_run", False))
        only: list[str] | None = call.data.get("only")
        only_set = set(only) if only else None

        entry_data, error = _resolve_entry_data(hass, requested_entry_id)
        if error:
            _LOGGER.error("restore_parameters: %s", error["error"])
            return error

        write_manager = entry_data["write_manager"]
        device: THZDevice = entry_data["device"]

        def _resolve_backup_path() -> str | None:
            backups_dir = _backups_dir(hass)
            if requested_filename:
                candidate = os.path.join(
                    backups_dir, os.path.basename(requested_filename)
                )
                return candidate if os.path.isfile(candidate) else None
            if not os.path.isdir(backups_dir):
                return None
            files = [
                f for f in os.listdir(backups_dir)
                if f.startswith("thz_backup_") and f.endswith(".json")
            ]
            if not files:
                return None
            files.sort(reverse=True)  # timestamp-prefixed names sort chronologically
            return os.path.join(backups_dir, files[0])

        path = await hass.async_add_executor_job(_resolve_backup_path)
        if not path:
            error_msg = (
                f"Backup file '{requested_filename}' not found"
                if requested_filename
                else "No backup files found in thz_backups/"
            )
            _LOGGER.error("restore_parameters: %s", error_msg)
            return {"success": False, "error": error_msg}

        def _read_backup() -> dict:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        try:
            backup_doc = await hass.async_add_executor_job(_read_backup)
        except (OSError, ValueError) as err:
            error_msg = f"Failed to read backup file '{path}': {err}"
            _LOGGER.error(error_msg)
            return {"success": False, "error": error_msg}

        saved_parameters: dict[str, dict] = backup_doc.get("parameters", {})
        write_registers = write_manager.get_all_registers()

        restored = 0
        skipped_missing: list[str] = []
        failed: list[str] = []

        for name, saved in saved_parameters.items():
            if name in _CLOCK_REGISTER_NAMES:
                # The device's real-time clock is never restored from a
                # backed-up value — that would set it back to whenever the
                # backup was taken. It's synced to the current local time
                # separately below instead.
                continue
            if only_set is not None and name not in only_set:
                continue
            entry = write_registers.get(name)
            if entry is None or entry.get("type") not in _RESTORABLE_REGISTER_TYPES:
                skipped_missing.append(name)
                continue

            reg_type = entry["type"]
            command = entry["command"]
            value = saved.get("value")

            try:
                if reg_type == "number":
                    step_raw = entry.get("step", 1)
                    step = float(step_raw) if step_raw != "" else 1.0
                    num_value = float(value)
                    min_raw, max_raw = entry.get("min"), entry.get("max")
                    if min_raw not in (None, ""):
                        try:
                            num_value = max(num_value, float(min_raw))
                        except (TypeError, ValueError):
                            pass
                    if max_raw not in (None, ""):
                        try:
                            num_value = min(num_value, float(max_raw))
                        except (TypeError, ValueError):
                            pass
                    value_bytes = THZValueCodec.encode_number(
                        num_value, step, entry["decode_type"]
                    )
                elif reg_type == "switch":
                    value_bytes = THZValueCodec.encode_switch(bool(value))
                elif reg_type == "select":
                    value_bytes = THZValueCodec.encode_select(
                        value, entry.get("decode_type")
                    )
                elif reg_type == "time":
                    t_value = _parse_hhmm(value)
                    num = time_to_quarters(t_value)
                    value_bytes = bytes([num, 0])
                elif reg_type == "schedule":
                    start_value = _parse_hhmm(value.get("start")) if value else None
                    end_value = _parse_hhmm(value.get("end")) if value else None
                    async with device.lock:
                        current_bytes = await hass.async_add_executor_job(
                            device.read_value, bytes.fromhex(command), "get", 4, 4
                        )
                    schedule_bytes = bytearray(current_bytes)
                    schedule_bytes[0] = time_to_quarters(start_value)
                    schedule_bytes[1] = time_to_quarters(end_value, is_end_time=True)
                    value_bytes = bytes(schedule_bytes)
                else:
                    skipped_missing.append(name)
                    continue
            except (ValueError, TypeError, KeyError, IndexError) as err:
                failed.append(f"{name}: {err}")
                continue

            if dry_run:
                restored += 1
                continue

            try:
                async with device.lock:
                    await hass.async_add_executor_job(
                        device.write_value, bytes.fromhex(command), value_bytes
                    )
                restored += 1
            except (OSError, RuntimeError, ConnectionError) as err:
                failed.append(f"{name}: {err}")

        # The device clock is always synced to the current local time as
        # part of a restore, never taken from the backup file — see the
        # skip above. dry_run skips this write too, and just reports what
        # the target time would have been.
        local_now = dt_util.now().replace(tzinfo=None, second=0, microsecond=0)
        clock_synced = False
        if not dry_run:
            try:
                await _async_write_device_clock(hass, device, write_manager, local_now)
                clock_synced = True
            except (OSError, RuntimeError, ConnectionError) as err:
                failed.append(f"<device clock>: {err}")

        _LOGGER.info(
            "THZ restore_parameters: %s%d restored, %d skipped (missing), "
            "%d failed, clock_synced=%s, from %s",
            "[DRY RUN] " if dry_run else "",
            restored, len(skipped_missing), len(failed), clock_synced, path,
        )

        notification_message = (
            f"File: {os.path.basename(path)}\n"
            f"Backup created: {backup_doc.get('created')}\n"
            f"Restored: {restored} / {len(saved_parameters)}\n"
            f"Skipped (missing): {len(skipped_missing)}\n"
            f"Failed: {len(failed)}\n"
            + (
                f"Clock synced to: {local_now.isoformat(timespec='minutes')}"
                if clock_synced
                else f"Clock: would be synced to {local_now.isoformat(timespec='minutes')} (dry run)"
                if dry_run
                else "Clock: not synced (write failed, see failed list)"
            )
        )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"THZ Parameter Restore {'(dry run) ' if dry_run else ''}Complete",
                "message": notification_message,
                "notification_id": "thz_restore_parameters",
            },
            blocking=True,
        )

        return {
            "success": True,
            "dry_run": dry_run,
            "file": os.path.basename(path),
            "backup_created": backup_doc.get("created"),
            "total_in_backup": len(saved_parameters),
            "restored": restored,
            "skipped_missing": skipped_missing[:20],
            "skipped_missing_count": len(skipped_missing),
            "failed": failed[:20],
            "failed_count": len(failed),
            "clock_synced": clock_synced,
            "clock_target": local_now.isoformat(timespec="minutes"),
        }

    async def _async_handle_list_parameter_backups(call: ServiceCall) -> ServiceResponse:
        """Handle the list_parameter_backups service call.

        Lists the parameter backup files under config/thz_backups/, newest
        first, so a filename can be picked and passed to restore_parameters.
        """

        def _list() -> list[dict]:
            backups_dir = _backups_dir(hass)
            if not os.path.isdir(backups_dir):
                return []
            results = []
            for fname in sorted(os.listdir(backups_dir), reverse=True):
                if not (fname.startswith("thz_backup_") and fname.endswith(".json")):
                    continue
                fpath = os.path.join(backups_dir, fname)
                info: dict[str, Any] = {
                    "filename": fname,
                    "size_bytes": os.path.getsize(fpath),
                }
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        doc = json.load(f)
                    info["created"] = doc.get("created")
                    info["parameter_count"] = doc.get("parameter_count")
                    info["device_id"] = doc.get("device_id")
                    info["firmware_version"] = doc.get("firmware_version")
                except (OSError, ValueError):
                    pass
                results.append(info)
            return results

        backups = await hass.async_add_executor_job(_list)
        return {"success": True, "count": len(backups), "backups": backups}

    # Register services
    hass.services.async_register(
        DOMAIN,
        "read_raw_register",
        _async_handle_read_raw_register,
        schema=vol.Schema({
            vol.Required("command"): cv.string,
            vol.Optional("entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "refresh_block",
        _async_handle_refresh_block,
        schema=vol.Schema({
            vol.Required("block"): cv.string,
            vol.Optional("entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "set_diverter_valve",
        _async_handle_set_diverter_valve,
        schema=vol.Schema({
            vol.Required("position"): vol.In(["heating", "dhw", "off"]),
            vol.Optional("entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "backup_parameters",
        _async_handle_backup_parameters,
        schema=vol.Schema({
            vol.Optional("entry_id"): cv.string,
            vol.Optional("label"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "restore_parameters",
        _async_handle_restore_parameters,
        schema=vol.Schema({
            vol.Optional("entry_id"): cv.string,
            vol.Optional("filename"): cv.string,
            vol.Optional("dry_run", default=False): cv.boolean,
            vol.Optional("only"): [cv.string],
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "list_parameter_backups",
        _async_handle_list_parameter_backups,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOGGER.info("THZ services registered")


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
            ent_reg.async_update_entity(
                entity_entry.entity_id,
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
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


async def _async_update_block(
    hass: HomeAssistant,
    device: THZDevice,
    block_name: str,
    paired_blocks: dict[str, str] | None = None,
):
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
        async with device.lock:
            result = await hass.async_add_executor_job(
                device.read_block, block_bytes, "get"
            )

            # If this block has a paired cmd3 register, read it too
            if paired_blocks and block_name in paired_blocks:
                cmd3_name = paired_blocks[block_name]
                cmd3_bytes = bytes.fromhex(cmd3_name.removeprefix("pxx"))
                cmd3_result = await hass.async_add_executor_job(
                    device.read_block, cmd3_bytes, "get"
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
    except Exception as err:  # noqa: BLE001
        raise UpdateFailed(f"Error reading {block_name}: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove Config Entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "binary_sensor", "number", "switch", "select", "time", "button", "climate"]
    )
    if unload_ok:
        # Clean up device connection
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if entry_data:
            unsub_clock_check = entry_data.get("unsub_clock_check")
            if unsub_clock_check:
                unsub_clock_check()
            device = entry_data.get("device")
            if device:
                await hass.async_add_executor_job(device.close)
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove services if this is the last config entry
        remaining_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining_entries:
            _LOGGER.debug("Removing THZ services (last config entry)")
            hass.services.async_remove(DOMAIN, "read_raw_register")
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

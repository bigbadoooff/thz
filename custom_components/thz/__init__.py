"""Init file for THZ integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import itertools
import logging

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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    WRITE_REGISTER_LENGTH,
    WRITE_REGISTER_OFFSET,
    should_hide_entity_by_default,
)
from .thz_device import THZDevice
from .value_codec import decode_raw_value
from .value_maps import SELECT_MAP

_LOGGER = logging.getLogger(__name__)

# Hex dump formatting constants
BYTES_PER_HEX_LINE = 16  # Number of bytes to display per line in hex dumps


def _resolve_target_device(
    hass: HomeAssistant, requested_entry_id: str | None
) -> THZDevice | None:
    """Resolve target THZ device from service call context.

    Returns None when target resolution fails.
    """
    available_entries: dict[str, dict] = {
        eid: ed
        for eid, ed in hass.data.get(DOMAIN, {}).items()
        if isinstance(ed, dict) and "device" in ed
    }

    if requested_entry_id:
        entry_data_for_cmd = available_entries.get(requested_entry_id)
        if entry_data_for_cmd is None:
            return None
        return entry_data_for_cmd["device"]

    if len(available_entries) > 1:
        return None

    if available_entries:
        return next(iter(available_entries.values()))["device"]

    return None


def _expand_scan_pattern(pattern: str) -> list[str]:
    """Expand a hex pattern containing X wildcards into commands.

    Example: "0A0XXX" -> ["0A0000", ..., "0A0FFF"]
    """
    normalized = pattern.strip().upper()
    if len(normalized) != 6:
        raise ValueError("Pattern must be exactly 6 characters")

    parts: list[list[str]] = []
    for ch in normalized:
        if ch == "X":
            parts.append(list("0123456789ABCDEF"))
            continue
        if ch not in "0123456789ABCDEF":
            raise ValueError(f"Invalid pattern character: {ch}")
        parts.append([ch])

    return ["".join(chars) for chars in itertools.product(*parts)]


def _expand_scan_range(start: str, end: str) -> list[str]:
    """Expand inclusive hex range to list of 6-char commands."""
    start_norm = start.strip().upper()
    end_norm = end.strip().upper()

    if len(start_norm) != 6 or len(end_norm) != 6:
        raise ValueError("start and end must be exactly 6 hex characters")

    try:
        start_val = int(start_norm, 16)
        end_val = int(end_norm, 16)
    except ValueError as err:
        raise ValueError("start/end must be valid hex") from err

    if start_val > end_val:
        raise ValueError("start must be less than or equal to end")

    return [f"{value:06X}" for value in range(start_val, end_val + 1)]


def _format_hex_dump(data: bytes) -> str:
    """Format bytes as an offset-based hex dump string."""
    formatted_lines = []
    for i in range(0, len(data), BYTES_PER_HEX_LINE):
        chunk = data[i : i + BYTES_PER_HEX_LINE]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        formatted_lines.append(f"  {i:04x}: {hex_str}")
    return "\n".join(formatted_lines)


def _guess_decode_candidates(data: bytes) -> dict[str, int | float | bool | str]:
    """Best-effort decode candidates for raw payload bytes."""
    candidates: dict[str, int | float | bool | str] = {
        "raw_hex": data.hex(),
        "raw_len": len(data),
    }

    if not data:
        return candidates

    try:
        candidates["u8"] = int.from_bytes(data[:1], byteorder="big", signed=False)
        candidates["s8"] = int.from_bytes(data[:1], byteorder="big", signed=True)
        candidates["bit0"] = bool(data[0] & 0x01)
    except Exception:  # noqa: BLE001
        pass

    if len(data) >= 2:
        two = data[:2]
        try:
            candidates["u16"] = int.from_bytes(two, byteorder="big", signed=False)
            candidates["s16"] = int.from_bytes(two, byteorder="big", signed=True)
            candidates["hex"] = decode_raw_value(two, "hex")
            candidates["hex2int"] = decode_raw_value(two, "hex2int")
        except Exception:  # noqa: BLE001
            pass

    if len(data) >= 4:
        four = data[:4]
        try:
            candidates["u32"] = int.from_bytes(
                four, byteorder="big", signed=False
            )
            candidates["s32"] = int.from_bytes(
                four, byteorder="big", signed=True
            )
        except Exception:  # noqa: BLE001
            pass

    # Generic boolean hint used by many THZ switch-like values
    try:
        candidates["bool_nonzero"] = bool(
            int.from_bytes(data[: min(2, len(data))], byteorder="big", signed=False)
        )
    except Exception:  # noqa: BLE001
        pass

    # Try known select maps against common value widths
    map_hits: dict[str, str] = {}
    try:
        width_values: dict[str, int] = {"u8": int.from_bytes(data[:1], "big")}
        if len(data) >= 2:
            width_values["u16"] = int.from_bytes(data[:2], "big")

        for map_name, mapping in SELECT_MAP.items():
            for value in width_values.values():
                key_plain = str(value)
                key_padded2 = str(value).zfill(2)
                if key_plain in mapping:
                    map_hits[map_name] = mapping[key_plain]
                    break
                if key_padded2 in mapping:
                    map_hits[map_name] = mapping[key_padded2]
                    break
    except Exception:  # noqa: BLE001
        pass

    if map_hits:
        candidates["select_candidates"] = ", ".join(
            f"{name}={value}" for name, value in sorted(map_hits.items())
        )

    return candidates


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
            update_method=lambda b=block: _async_update_block(
                hass, device, b, paired_blocks
            ),
        )
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info(
            "Initial data fetch completed for block %s, data available: %s",
            block,
            coordinator.data is not None,
        )
        coordinators[block] = coordinator

    # Store in hass.data — all per-entry so multiple config entries don't collide
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "device": device,
        "device_id": unique_id,
        "write_manager": write_manager,
        "register_manager": register_manager,
        "coordinators": coordinators,
    }

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

        # Locate the target device. With a single entry no entry_id is needed.
        # With multiple entries, entry_id is required — return an error if omitted.
        device = _resolve_target_device(hass, requested_entry_id)
        if device is None:
            available_entries: dict[str, dict] = {
                eid: ed
                for eid, ed in hass.data.get(DOMAIN, {}).items()
                if isinstance(ed, dict) and "device" in ed
            }
            if requested_entry_id and requested_entry_id not in available_entries:
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
            if len(available_entries) > 1 and not requested_entry_id:
                error_msg = (
                    "Multiple THZ config entries found. "
                    "Provide 'entry_id' to target a specific device."
                )
            else:
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

            formatted = _format_hex_dump(data)
            hex_string = data.hex()

            # Log the result
            _LOGGER.info(
                "Raw register %s read successfully (%d bytes):\n%s",
                command_str,
                len(data),
                formatted,
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

    async def _async_handle_scan_raw_registers(call: ServiceCall) -> ServiceResponse:
        """Handle the scan_raw_registers service call."""
        requested_entry_id: str | None = call.data.get("entry_id")
        pattern: str | None = call.data.get("pattern")
        start: str | None = call.data.get("start")
        end: str | None = call.data.get("end")
        include_errors = bool(call.data.get("include_errors", False))
        decode_values = bool(call.data.get("decode_values", False))
        max_results = int(call.data.get("max_results", 65535))

        if max_results <= 0:
            return {
                "success": False,
                "error": "max_results must be greater than 0",
            }

        use_pattern = bool(pattern)
        use_range = bool(start) or bool(end)
        if use_pattern == use_range:
            return {
                "success": False,
                "error": "Provide either 'pattern' or both 'start' and 'end'",
            }

        try:
            if use_pattern:
                commands = _expand_scan_pattern(pattern or "")
                scan_mode = f"pattern:{(pattern or '').strip().upper()}"
            else:
                if not start or not end:
                    raise ValueError("Both 'start' and 'end' are required")
                commands = _expand_scan_range(start, end)
                scan_mode = f"range:{start.strip().upper()}-{end.strip().upper()}"
        except ValueError as err:
            return {
                "success": False,
                "error": str(err),
            }

        if len(commands) > max_results:
            commands = commands[:max_results]

        device = _resolve_target_device(hass, requested_entry_id)
        if device is None:
            available_entries: dict[str, dict] = {
                eid: ed
                for eid, ed in hass.data.get(DOMAIN, {}).items()
                if isinstance(ed, dict) and "device" in ed
            }
            if requested_entry_id and requested_entry_id not in available_entries:
                return {
                    "success": False,
                    "error": f"No THZ entry found for entry_id '{requested_entry_id}'",
                }
            if len(available_entries) > 1 and not requested_entry_id:
                return {
                    "success": False,
                    "error": (
                        "Multiple THZ config entries found. "
                        "Provide 'entry_id' to target a specific device."
                    ),
                }
            return {
                "success": False,
                "error": "THZ device not initialized",
            }

        results: list[dict[str, str | int | bool | dict[str, int | float | bool | str]]] = []
        success_count = 0
        error_count = 0

        for command_str in commands:
            command_bytes = bytes.fromhex(command_str)
            try:
                async with device.lock:
                    data = await hass.async_add_executor_job(
                        device.read_block, command_bytes, "get"
                    )
                success_count += 1
                result_item: dict[str, str | int | bool | dict[str, int | float | bool | str]] = {
                    "command": command_str,
                    "success": True,
                    "length": len(data),
                    "hex": data.hex(),
                    "formatted": _format_hex_dump(data),
                }
                if decode_values:
                    payload = data[4:] if len(data) > 4 else b""
                    result_item["decoded"] = _guess_decode_candidates(payload)

                results.append(result_item)
            except Exception as err:  # noqa: BLE001
                error_count += 1
                if include_errors:
                    results.append(
                        {
                            "command": command_str,
                            "success": False,
                            "error": str(err),
                        }
                    )

        _LOGGER.info(
            "Raw register scan done (%s): scanned=%d, success=%d, errors=%d",
            scan_mode,
            len(commands),
            success_count,
            error_count,
        )

        response = {
            "success": True,
            "summary": {
                "mode": scan_mode,
                "scanned": len(commands),
                "success_count": success_count,
                "error_count": error_count,
                "include_errors": include_errors,
                "decode_values": decode_values,
            },
            "results": results,
        }

        preview_lines = [
            f"Mode: {scan_mode}",
            f"Scanned: {len(commands)}",
            f"Success: {success_count}",
            f"Errors: {error_count}",
        ]
        for item in results[:20]:
            if item.get("success"):
                preview_lines.append(
                    f"{item['command']} ({item['length']} B): {item['hex']}"
                )
            else:
                preview_lines.append(
                    f"{item['command']} ERROR: {item.get('error', 'unknown error')}"
                )
        if len(results) > 20:
            preview_lines.append(f"... and {len(results) - 20} more")

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"THZ Raw Register Scan ({scan_mode})",
                "message": "\n".join(preview_lines),
                "notification_id": f"thz_scan_{scan_mode.replace(':', '_')}",
            },
            blocking=True,
        )

        return response

    # Register the service
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
        "scan_raw_registers",
        _async_handle_scan_raw_registers,
        schema=vol.Schema(
            {
                vol.Exclusive("pattern", "scan_input"): cv.string,
                vol.Inclusive("start", "scan_range"): cv.string,
                vol.Inclusive("end", "scan_range"): cv.string,
                vol.Optional("entry_id"): cv.string,
                vol.Optional("include_errors", default=False): cv.boolean,
                vol.Optional("decode_values", default=False): cv.boolean,
                vol.Optional("max_results", default=65535): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
            }
        ),
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
            hass.services.async_remove(DOMAIN, "scan_raw_registers")
            hass.services.async_remove(DOMAIN, "refresh_block")
            hass.services.async_remove(DOMAIN, "set_diverter_valve")

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

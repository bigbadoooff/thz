"""Service registration and handlers for the THZ integration.

Home Assistant service calls (``thz.read_raw_register``, ``thz.scan_raw_registers``,
``thz.watch_raw_registers_changes``, ``thz.refresh_block``, ``thz.set_diverter_valve``,
``thz.backup_parameters``, ``thz.restore_parameters``, ``thz.list_parameter_backups``)
are registered and handled here. ``__init__.py`` calls :func:`async_setup_services`
once during ``async_setup_entry``.
"""

from __future__ import annotations

import asyncio
from datetime import time as dt_time
import itertools
import json
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

from ._typing_compat import get_runtime_data
from .clock_sync import (
    CLOCK_DRIFT_BACKUP_SECONDS,
    CLOCK_REGISTER_NAMES,
    async_read_device_clock,
    async_write_device_clock,
)
from .const import DOMAIN, WRITE_REGISTER_LENGTH, WRITE_REGISTER_OFFSET
from .thz_device import THZDevice, THZRegisterNotSupportedError
from .time import quarters_to_time, time_to_quarters
from .value_codec import THZValueCodec, decode_raw_value
from .value_maps import SELECT_MAP

_LOGGER = logging.getLogger(__name__)

# Hex dump formatting constants
BYTES_PER_HEX_LINE = 16  # Number of bytes to display per line in hex dumps

# Parameter backup/restore constants
BACKUP_SUBDIR = "thz_backups"
# Register types that hold a persistent, restorable value. "button" is a
# one-shot action with no state, and "ptime" is a legacy/unused type not
# consumed by any current platform, so neither is backed up.
_RESTORABLE_REGISTER_TYPES = {"number", "switch", "select", "time", "schedule"}


def _require_target_entry_data(
    hass: HomeAssistant, requested_entry_id: str | None
) -> tuple[str, dict]:
    """Resolve the target THZ config-entry id and data for a service call.

    Raises ServiceValidationError when entry_id is invalid or omitted while
    ambiguous (multiple entries loaded), or HomeAssistantError when no THZ
    device is initialized at all.
    """
    available_entries: dict[str, dict] = {
        entry.entry_id: get_runtime_data(entry)
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(get_runtime_data(entry), dict)
        and "device" in get_runtime_data(entry)
    }

    if requested_entry_id:
        entry_data = available_entries.get(requested_entry_id)
        if entry_data is None:
            raise ServiceValidationError(
                f"No THZ entry found for entry_id '{requested_entry_id}'"
            )
        return requested_entry_id, entry_data

    if len(available_entries) > 1:
        raise ServiceValidationError(
            "Multiple THZ config entries found. "
            "Provide 'entry_id' to target a specific device."
        )

    if available_entries:
        return next(iter(available_entries.items()))

    raise HomeAssistantError("THZ device not initialized")


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


def _resolve_scan_commands(
    pattern: str | None, start: str | None, end: str | None, max_results: int
) -> tuple[list[str], str]:
    """Validate and expand a pattern/range scan request into a command list.

    Shared by scan_raw_registers and watch_raw_registers_changes, which both
    accept exactly one of a wildcard ``pattern`` or a ``start``/``end`` range.

    Raises:
        ServiceValidationError: If max_results isn't positive, neither or both
            of pattern/range are provided, or the pattern/range is malformed.

    Returns:
        A tuple of (commands, scan_mode) — the expanded, max_results-truncated
        list of 6-hex-char commands, and a human-readable mode label used in
        logging and notification text.
    """
    if max_results <= 0:
        raise ServiceValidationError("max_results must be greater than 0")

    use_pattern = bool(pattern)
    use_range = bool(start) or bool(end)
    if use_pattern == use_range:
        raise ServiceValidationError(
            "Provide either 'pattern' or both 'start' and 'end'"
        )

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
        raise ServiceValidationError(str(err)) from err

    if len(commands) > max_results:
        commands = commands[:max_results]

    return commands, scan_mode


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
        entry.entry_id: get_runtime_data(entry)
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(get_runtime_data(entry), dict)
        and "coordinators" in get_runtime_data(entry)
    }

    if entry_id:
        entry_data = available_entries.get(entry_id)
        if entry_data is None:
            _LOGGER.error(
                "async_refresh_block: no THZ entry for entry_id '%s'", entry_id
            )
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
        _LOGGER.warning(
            "async_refresh_block: block '%s' not found in any coordinator", normalized
        )
    return found


async def async_setup_services(hass: HomeAssistant) -> None:
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
            _LOGGER.exception(error_msg)
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
            raise ServiceValidationError(error_msg) from err

        # Locate the target device. With a single entry no entry_id is needed.
        # With multiple entries, entry_id is required — raise if omitted.
        try:
            _, entry_data = _require_target_entry_data(hass, requested_entry_id)
        except (ServiceValidationError, HomeAssistantError) as err:
            error_msg = str(err)
            _LOGGER.exception(error_msg)
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
            raise
        device = entry_data["device"]

        # Read the register
        try:
            _LOGGER.info("Reading raw register: %s", command_str)
            data = await device.async_execute(
                hass, device.read_block, command_bytes, "get"
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
            raise HomeAssistantError(error_msg) from err

    async def _async_handle_scan_raw_registers(call: ServiceCall) -> ServiceResponse:
        """Handle the scan_raw_registers service call."""
        requested_entry_id: str | None = call.data.get("entry_id")
        pattern: str | None = call.data.get("pattern")
        start: str | None = call.data.get("start")
        end: str | None = call.data.get("end")
        include_errors = bool(call.data.get("include_errors", False))
        decode_values = bool(call.data.get("decode_values", False))
        max_results = int(call.data.get("max_results", 65535))
        preview_limit = int(call.data.get("preview_limit", 20))

        commands, scan_mode = _resolve_scan_commands(pattern, start, end, max_results)

        _, entry_data = _require_target_entry_data(hass, requested_entry_id)
        device = entry_data["device"]

        result_value = str | int | bool | dict[str, int | float | bool | str]
        results: list[dict[str, result_value]] = []
        success_count = 0
        error_count = 0

        for command_str in commands:
            command_bytes = bytes.fromhex(command_str)
            try:
                data = await device.async_execute(
                    hass, device.read_block, command_bytes, "get"
                )
                success_count += 1
                result_item: dict[str, result_value] = {
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
        preview_items = results if preview_limit == 0 else results[:preview_limit]
        for item in preview_items:
            if item.get("success"):
                preview_lines.append(
                    f"{item['command']} ({item['length']} B): {item['hex']}"
                )
            else:
                preview_lines.append(
                    f"{item['command']} ERROR: {item.get('error', 'unknown error')}"
                )
        if preview_limit != 0 and len(results) > preview_limit:
            preview_lines.append(f"... and {len(results) - preview_limit} more")

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

    async def _async_handle_watch_raw_registers_changes(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Handle the watch_raw_registers_changes service call."""
        requested_entry_id: str | None = call.data.get("entry_id")
        pattern: str | None = call.data.get("pattern")
        start: str | None = call.data.get("start")
        end: str | None = call.data.get("end")
        duration_seconds = int(call.data.get("duration_seconds", 0))
        interval_seconds = float(call.data.get("interval_seconds", 0.0))
        max_results = int(call.data.get("max_results", 65535))

        if duration_seconds < 1:
            raise ServiceValidationError(
                "duration_seconds must be greater than or equal to 1"
            )

        if interval_seconds < 0:
            raise ServiceValidationError(
                "interval_seconds must be greater than or equal to 0"
            )

        commands, scan_mode = _resolve_scan_commands(pattern, start, end, max_results)

        _, entry_data = _require_target_entry_data(hass, requested_entry_id)
        device = entry_data["device"]

        valid_registers: dict[str, str] = {}
        for command_str in commands:
            command_bytes = bytes.fromhex(command_str)
            try:
                data = await device.async_execute(
                    hass, device.read_block, command_bytes, "get"
                )
                valid_registers[command_str] = data.hex()
            except Exception:  # noqa: BLE001
                continue

        changed_registers: list[dict[str, str | int]] = []
        total_reads = 0
        iterations = 0

        start_ts = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_ts) < duration_seconds:
            iterations += 1
            for command_str, old_hex in list(valid_registers.items()):
                command_bytes = bytes.fromhex(command_str)
                try:
                    data = await device.async_execute(
                        hass, device.read_block, command_bytes, "get"
                    )
                    total_reads += 1
                    new_hex = data.hex()
                    if new_hex != old_hex:
                        changed_registers.append(
                            {
                                "command": command_str,
                                "iteration": iterations,
                                "old_hex": old_hex,
                                "new_hex": new_hex,
                            }
                        )
                        valid_registers[command_str] = new_hex
                except Exception:  # noqa: BLE001
                    # Already validated in pre-scan; skip runtime read failures.
                    continue

            if interval_seconds > 0:
                await asyncio.sleep(interval_seconds)

        _LOGGER.info(
            "Watch raw register changes done (%s): scanned=%d, valid=%d, "
            "iterations=%d, reads=%d, changes=%d",
            scan_mode,
            len(commands),
            len(valid_registers),
            iterations,
            total_reads,
            len(changed_registers),
        )

        return {
            "success": True,
            "summary": {
                "mode": scan_mode,
                "duration_seconds": duration_seconds,
                "interval_seconds": interval_seconds,
                "iterations": iterations,
                "scanned": len(commands),
                "valid_count": len(valid_registers),
                "total_reads": total_reads,
                "changes_detected": len(changed_registers),
            },
            "changed_registers": changed_registers,
        }

    # Register the service
    async def _async_handle_refresh_block(call: ServiceCall) -> ServiceResponse:
        """Handle the refresh_block service call."""
        block = call.data.get("block", "").strip()
        requested_entry_id: str | None = call.data.get("entry_id")

        if not block:
            raise ServiceValidationError("block parameter is required")

        normalized = _normalize_block_name(block)
        found = await async_refresh_block(hass, block, requested_entry_id)

        if found:
            _LOGGER.info("Service refresh_block: refreshed %s", normalized)
            return {"success": True, "block": normalized}

        error_msg = f"Block '{normalized}' not found in any active coordinator"
        _LOGGER.warning(error_msg)
        raise ServiceValidationError(error_msg)

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

        _, entry_data = _require_target_entry_data(hass, requested_entry_id)

        # Safety guard: no valve movement in the wrong direction under pressure.
        # diverterValve bit = 1 → flow is to DHW; bit = 0 → flow is to heating circuit.
        # Moving the valve against the active flow direction is refused.
        if position in ("dhw", "heating"):
            coordinator = entry_data.get("coordinators", {}).get(_DIVERTER_BLOCK)
            if coordinator is None or coordinator.data is None:
                raise HomeAssistantError(
                    f"Cannot verify valve state: {_DIVERTER_BLOCK} coordinator "
                    "data not available"
                )
            data: bytes = coordinator.data
            if len(data) <= _DIVERTER_BYTE:
                raise HomeAssistantError(
                    f"Insufficient data from {_DIVERTER_BLOCK} block"
                )
            diverter_active = bool((data[_DIVERTER_BYTE] >> _DIVERTER_BIT) & 0x01)
            if position == "dhw" and not diverter_active:
                raise HomeAssistantError(
                    "Heat pump is not in DHW mode (diverterValve bit = 0 in "
                    "pxxF2). Moving valve to DHW refused — heating circuit is "
                    "under pressure."
                )
            if position == "heating" and diverter_active:
                raise HomeAssistantError(
                    "Heat pump is in DHW mode (diverterValve bit = 1 in "
                    "pxxF2). Moving valve to heating refused — DHW circuit "
                    "is under pressure."
                )

        device: THZDevice = entry_data["device"]

        async def _stop_and_verify() -> bool:
            """Stop both motors; read back to confirm, retry once if not zero."""
            await device.async_execute(
                hass, device.write_value, _VALVE_MOTOR_HEATING, _VALVE_MOTOR_OFF
            )
            await device.async_execute(
                hass, device.write_value, _VALVE_MOTOR_DHW, _VALVE_MOTOR_OFF
            )
            h_state = await device.async_execute(
                hass, device.read_value, _VALVE_MOTOR_HEATING, "get",
                WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH,
            )
            d_state = await device.async_execute(
                hass, device.read_value, _VALVE_MOTOR_DHW, "get",
                WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH,
            )

            if h_state != _VALVE_MOTOR_OFF or d_state != _VALVE_MOTOR_OFF:
                _LOGGER.warning(
                    "Diverter valve motor not confirmed off (heating=%s dhw=%s), "
                    "retrying stop",
                    h_state.hex(), d_state.hex(),
                )
                await device.async_execute(
                    hass, device.write_value, _VALVE_MOTOR_HEATING, _VALVE_MOTOR_OFF
                )
                await device.async_execute(
                    hass, device.write_value, _VALVE_MOTOR_DHW, _VALVE_MOTOR_OFF
                )
                return False

            return True

        try:
            # Send the motor ON command
            if position == "heating":
                await device.async_execute(
                    hass, device.write_value, _VALVE_MOTOR_HEATING, _VALVE_MOTOR_ON
                )
            elif position == "dhw":
                await device.async_execute(
                    hass, device.write_value, _VALVE_MOTOR_DHW, _VALVE_MOTOR_ON
                )

            # Auto-stop after 3s (lock released during wait so coordinators can poll)
            if position in ("heating", "dhw"):
                await asyncio.sleep(3)

            # Stop and verify — runs for explicit "off" too
            confirmed = await _stop_and_verify()

        except (RuntimeError, ConnectionError, OSError) as err:
            error_msg = f"Error sending diverter valve command: {err}"
            _LOGGER.exception(error_msg)
            raise HomeAssistantError(error_msg) from err

        _LOGGER.info(
            "Diverter valve command sent: position=%s confirmed_off=%s",
            position, confirmed,
        )
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

        entry_id, entry_data = _require_target_entry_data(hass, requested_entry_id)
        write_manager = entry_data["write_manager"]
        device: THZDevice = entry_data["device"]
        device_id = entry_data.get("device_id")

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
                    value_bytes = await device.async_execute(
                        hass, device.read_value, bytes.fromhex(command), "get", 4, 4
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
                    value_bytes = await device.async_execute(
                        hass, device.read_value, bytes.fromhex(command), "get",
                        WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH,
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
            except THZRegisterNotSupportedError as err:
                read_errors.append(f"{name}: {err}")
                _LOGGER.debug(
                    "backup_parameters: skipping unsupported register %s: %s", name, err
                )
            except Exception as err:  # noqa: BLE001
                read_errors.append(f"{name}: {err}")
                _LOGGER.warning("backup_parameters: failed to read %s: %s", name, err)

        # Sanity-check the device's real-time clock against local time.
        # Backup is otherwise read-only, but a grossly wrong clock (over an
        # hour off — e.g. after a power loss or reset) throws off every
        # schedule the heat pump runs, so it's corrected here as a
        # deliberate exception. Smaller drift is left alone; that's what the
        # periodic auto_sync_clock check (1-minute threshold, see
        # clock_sync.py) is for.
        #
        # Read via async_read_device_clock rather than pulling from
        # `parameters` above: the five pClock* registers are type "pclean"
        # (no platform claims that type as an entity), so they're never
        # added to `parameters` by the loop's _RESTORABLE_REGISTER_TYPES
        # filter — reading them back out of it here would always miss.
        clock_drift_seconds: float | None = None
        clock_corrected = False
        device_dt = await async_read_device_clock(hass, device, write_manager)
        if device_dt is not None:
            local_now = dt_util.now().replace(tzinfo=None, second=0, microsecond=0)
            clock_drift_seconds = (device_dt - local_now).total_seconds()
            if abs(clock_drift_seconds) > CLOCK_DRIFT_BACKUP_SECONDS:
                await async_write_device_clock(hass, device, write_manager, local_now)
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
            "entry_id": entry_id,
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
            _LOGGER.exception("backup_parameters: failed to write backup file")
            raise HomeAssistantError(f"Failed to write backup file: {err}") from err

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

        _, entry_data = _require_target_entry_data(hass, requested_entry_id)
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
            raise HomeAssistantError(error_msg)

        def _read_backup() -> dict:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        try:
            backup_doc = await hass.async_add_executor_job(_read_backup)
        except (OSError, ValueError) as err:
            error_msg = f"Failed to read backup file '{path}': {err}"
            _LOGGER.exception(error_msg)
            raise HomeAssistantError(error_msg) from err

        saved_parameters: dict[str, dict] = backup_doc.get("parameters", {})
        write_registers = write_manager.get_all_registers()

        restored = 0
        skipped_missing: list[str] = []
        failed: list[str] = []

        for name, saved in saved_parameters.items():
            if name in CLOCK_REGISTER_NAMES:
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
                    current_bytes = await device.async_execute(
                        hass, device.read_value, bytes.fromhex(command), "get", 4, 4
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
                await device.async_execute(
                    hass, device.write_value, bytes.fromhex(command), value_bytes
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
                await async_write_device_clock(hass, device, write_manager, local_now)
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
                vol.Optional("preview_limit", default=20): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=65535)
                ),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "watch_raw_registers_changes",
        _async_handle_watch_raw_registers_changes,
        schema=vol.Schema(
            {
                vol.Exclusive("pattern", "scan_input"): cv.string,
                vol.Inclusive("start", "scan_range"): cv.string,
                vol.Inclusive("end", "scan_range"): cv.string,
                vol.Required("duration_seconds"): vol.All(
                    vol.Coerce(int), vol.Range(min=1)
                ),
                vol.Optional("interval_seconds", default=0.0): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
                vol.Optional("entry_id"): cv.string,
                vol.Optional("max_results", default=65535): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
            }
        ),
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

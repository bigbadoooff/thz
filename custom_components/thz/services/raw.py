"""Raw register services: read, scan, watch for changes, refresh a block.

These are debugging tools for mapping registers on unknown firmwares; they
read whole registers/blocks and return hex dumps, never write.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from ..notify import async_notify
from ..value_codec import decode_raw_value
from ..value_maps import SELECT_MAP
from .common import (
    _normalize_block_name,
    _require_target_entry_data,
    async_refresh_block,
)

_LOGGER = logging.getLogger(__name__)

# Hex dump formatting constants
BYTES_PER_HEX_LINE = 16  # Number of bytes to display per line in hex dumps


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

    for width in (1, 2, 4):
        if len(data) >= width:
            chunk = data[:width]
            candidates[f"u{width * 8}"] = int.from_bytes(chunk, "big")
            candidates[f"s{width * 8}"] = int.from_bytes(chunk, "big", signed=True)
    candidates["bit0"] = bool(data[0] & 0x01)
    if len(data) >= 2:
        candidates["hex"] = decode_raw_value(data[:2], "hex")
        candidates["hex2int"] = decode_raw_value(data[:2], "hex2int")

    # Generic boolean hint used by many THZ switch-like values
    candidates["bool_nonzero"] = any(data[:2])

    map_hits = _select_map_hits(data)
    if map_hits:
        candidates["select_candidates"] = ", ".join(
            f"{name}={value}" for name, value in sorted(map_hits.items())
        )
    return candidates


def _select_map_hits(data: bytes) -> dict[str, str]:
    """Return the select-map options the first one or two bytes would decode to."""
    values = [int.from_bytes(data[:1], "big")]
    if len(data) >= 2:
        values.append(int.from_bytes(data[:2], "big"))

    hits: dict[str, str] = {}
    for map_name, mapping in SELECT_MAP.items():
        for value in values:
            key = next(
                (k for k in (str(value), str(value).zfill(2)) if k in mapping), None
            )
            if key is not None:
                hits[map_name] = mapping[key]
                break
    return hits


async def async_handle_read_raw_register(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle the read_raw_register service call.

    This service reads a raw register/block from the heatpump and returns
    the hex dump. It's useful for debugging firmware-specific register issues.

    Args:
        hass: The Home Assistant instance.
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
        async_notify(
            hass,
            title="THZ Raw Register Read Error",
            message=error_msg,
            notification_id=f"thz_raw_{command_str}",
        )
        raise ServiceValidationError(error_msg) from err

    # Locate the target device. With a single entry no entry_id is needed.
    # With multiple entries, entry_id is required — raise if omitted.
    try:
        _, entry_data = _require_target_entry_data(hass, requested_entry_id)
    except (ServiceValidationError, HomeAssistantError) as err:
        error_msg = str(err)
        _LOGGER.exception(error_msg)
        async_notify(
            hass,
            title="THZ Raw Register Read Error",
            message=error_msg,
            notification_id=f"thz_raw_{command_str}",
        )
        raise
    device = entry_data["device"]

    # Read the register
    try:
        _LOGGER.info("Reading raw register: %s", command_str)
        data = await device.async_execute(hass, device.read_block, command_bytes, "get")

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

        async_notify(
            hass,
            title=f"THZ Raw Register Read: {command_str}",
            message=notification_message,
            notification_id=f"thz_raw_{command_str}",
        )

        # Return service response
        return {
            "success": True,
            "command": command_str,
            "length": len(data),
            "hex": hex_string,
            "formatted": formatted,
        }

    except Exception as err:
        error_msg = f"Error reading register {command_str}: {err}"
        _LOGGER.error(error_msg, exc_info=True)
        async_notify(
            hass,
            title="THZ Raw Register Read Error",
            message=error_msg,
            notification_id=f"thz_raw_{command_str}",
        )
        raise HomeAssistantError(error_msg) from err


async def async_handle_scan_raw_registers(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
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

    async_notify(
        hass,
        title=f"THZ Raw Register Scan ({scan_mode})",
        message="\n".join(preview_lines),
        notification_id=f"thz_scan_{scan_mode.replace(':', '_')}",
    )

    return cast("ServiceResponse", response)


async def async_handle_watch_raw_registers_changes(
    hass: HomeAssistant, call: ServiceCall
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

    return cast(
        "ServiceResponse",
        {
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
        },
    )


async def async_handle_refresh_block(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
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

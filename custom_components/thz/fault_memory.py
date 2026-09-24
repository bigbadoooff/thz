"""D1 fault-memory decoding and the guarded clear operation.

Layout (firmware 4.x, verified on a THZ 303 SOL running 4.19; the existing
``pxxD1`` read map uses the same offsets): the response echoes the command at
byte 1, byte 2 is the number of stored faults and byte 3 is reserved. Up to
ten six-byte records follow from byte 4, oldest first::

    [fault number][reserved][time: 2 bytes swapped][date: 2 bytes swapped]

Time and date are two-digit decimal pairs stored byte-swapped (see
``value_codec._dec_turnhex2time`` / ``_dec_turnhexdate``); no year is stored.

Reading is always safe. Clearing writes ``0000`` to D1 exactly once. That write
was verified on firmware 4.19 only; on other firmware the pre-read still has to
validate the D1 response and success is decided by reading D1 back.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .exceptions import DEVICE_ERRORS, THZNotSupportedError, THZProtocolError
from .value_maps import SELECT_MAP

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

FAULT_MEMORY_COMMAND = bytes.fromhex("D1")
FAULT_HEADER_SIZE = 4
FAULT_RECORD_SIZE = 6
FAULT_MAX_RECORDS = 10

FAULT_CLEAR_PAYLOAD = bytes.fromhex("0000")
CLEAR_CONFIRMATION = "CLEAR D1"


def _swapped_pair(raw: bytes) -> int | None:
    """Return the byte-swapped two-byte value as a decimal number."""
    if len(raw) != 2:
        return None
    return int.from_bytes(raw, byteorder="little")


def decode_fault_time(raw: bytes) -> str | None:
    """Return "HH:MM" for a plausible two-byte fault time, else None."""
    value = _swapped_pair(raw)
    if value is None:
        return None
    hour, minute = divmod(value, 100)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def decode_fault_date(raw: bytes) -> str | None:
    """Return "DD.MM" for a plausible two-byte fault date, else None."""
    value = _swapped_pair(raw)
    if value is None:
        return None
    day, month = divmod(value, 100)
    if 1 <= day <= 31 and 1 <= month <= 12:
        return f"{day:02d}.{month:02d}"
    return None


def fault_description(fault_number: int) -> str:
    """Return the fault name from the shared fault table."""
    faultmap = SELECT_MAP.get("faultmap", {})
    return faultmap.get(str(fault_number), f"F{fault_number:02d}_Unknown")


def decode_fault_record(data: bytes, slot: int) -> dict[str, Any]:
    """Decode one six-byte fault record."""
    offset = FAULT_HEADER_SIZE + slot * FAULT_RECORD_SIZE
    record = data[offset : offset + FAULT_RECORD_SIZE]
    result: dict[str, Any] = {
        "slot": slot,
        "raw": record.hex().upper(),
        "complete": len(record) == FAULT_RECORD_SIZE,
    }
    if len(record) != FAULT_RECORD_SIZE:
        return result

    number = record[0]
    time_text = decode_fault_time(record[2:4])
    date_text = decode_fault_date(record[4:6])
    result.update(
        {
            "fault_number": number,
            "fault_code": f"F{number:02d}",
            "description": fault_description(number),
            "time": time_text,
            "date": date_text,
        }
    )
    return result


def decode_fault_memory(data: bytes) -> dict[str, Any]:
    """Decode a complete D1 response.

    Returns ``{"valid": False, "error": ...}`` for an unusable payload,
    otherwise the reported count and the decoded ``entries`` (oldest first).
    """
    if len(data) < FAULT_HEADER_SIZE:
        return {
            "valid": False,
            "error": (
                f"D1 response too short: {len(data)} bytes, "
                f"need at least {FAULT_HEADER_SIZE}"
            ),
        }
    if data[1:2] != FAULT_MEMORY_COMMAND:
        return {
            "valid": False,
            "error": f"Unexpected D1 command echo: {data.hex().upper()}",
        }

    reported = data[2]
    available = (len(data) - FAULT_HEADER_SIZE) // FAULT_RECORD_SIZE
    count = min(reported, available, FAULT_MAX_RECORDS)
    result: dict[str, Any] = {
        "valid": True,
        "fault_count_reported": reported,
        "records_available": available,
        "entries": [decode_fault_record(data, slot) for slot in range(count)],
    }
    if reported > count:
        result["warning"] = (
            f"D1 reports {reported} faults but only {count} could be decoded"
        )
    return result


def record_fingerprints(entries: list[dict[str, Any]]) -> list[str]:
    """Return the exact six-byte fingerprint of every complete record."""
    return [
        str(entry["raw"]).upper()
        for entry in entries
        if entry.get("complete") and entry.get("raw")
    ]


def new_record_start(acknowledged: list[str], current: list[str]) -> int:
    """Return the first index in ``current`` that is newer than acknowledged.

    D1 is a rolling history of at most ten records, so the acknowledged tail
    and the current head overlap when nothing was lost. The largest overlap
    wins; with no overlap every current record counts as new.
    """
    for overlap in range(min(len(acknowledged), len(current)), 0, -1):
        if acknowledged[-overlap:] == current[:overlap]:
            return overlap
    return 0


async def read_fault_memory(hass: HomeAssistant, device: THZDevice) -> dict[str, Any]:
    """Read and decode D1. Read-only.

    Raises communication errors (and ``THZProtocolError`` for an invalid payload)
    so callers decide how to report them.
    """
    data = await device.async_execute(device.read_block, FAULT_MEMORY_COMMAND, "get")
    if data is None:
        raise THZProtocolError("D1 fault-memory read returned no data")
    raw = bytes(data)
    decoded = decode_fault_memory(raw)
    if not decoded["valid"]:
        raise THZProtocolError(decoded["error"])
    return {"length": len(raw), "raw": raw.hex().upper(), "decoded": decoded}


def _fault_count(result: dict[str, Any]) -> int:
    return int(result["decoded"]["fault_count_reported"])


async def _read_back(
    hass: HomeAssistant, device: THZDevice, attempts: int = 3
) -> tuple[dict[str, Any] | None, list[str]]:
    """Read D1 after a clear. Reads may be retried; they cannot clear again."""
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            await asyncio.sleep(1.0)
        try:
            return await read_fault_memory(hass, device), errors
        except (THZNotSupportedError, *DEVICE_ERRORS) as err:
            errors.append(f"readback {attempt}/{attempts}: {type(err).__name__}: {err}")
    return None, errors


async def clear_fault_memory(hass: HomeAssistant, device: THZDevice) -> dict[str, Any]:
    """Clear the physical D1 fault memory and verify it by readback.

    Safety properties: D1 is read and validated first; nothing is written when
    it is already empty; exactly one SET of ``0000`` is sent and it is never
    retried by this function; success is decided only by a later D1 read.

    Raises:
        THZProtocolError: D1 could not be read beforehand, the write failed, or the
            readback could not confirm the memory is empty (in that case the
            write may still have taken effect).
    """
    try:
        before = await read_fault_memory(hass, device)
    except THZNotSupportedError as err:
        raise THZProtocolError(f"D1 fault memory is not supported: {err}") from err
    except DEVICE_ERRORS as err:
        raise THZProtocolError(f"Could not read D1 before clearing: {err}") from err

    before_count = _fault_count(before)
    if before_count == 0:
        return {"cleared": False, "before_count": 0, "after_count": 0}

    _LOGGER.warning("Clearing THZ D1 fault memory (%d record(s) stored)", before_count)
    try:
        await device.async_execute(
            device.write_value, FAULT_MEMORY_COMMAND, FAULT_CLEAR_PAYLOAD
        )
    except DEVICE_ERRORS as err:
        raise THZProtocolError(
            f"Writing D1 failed ({type(err).__name__}: {err}); the fault memory "
            "may or may not have been cleared - check the D1 state"
        ) from err

    after, errors = await _read_back(hass, device)
    if after is None:
        raise THZProtocolError(
            "D1 was written but the readback failed, so the result is unknown: "
            + "; ".join(errors)
        )
    after_count = _fault_count(after)
    if after_count != 0:
        raise THZProtocolError(
            f"D1 still reports {after_count} fault(s) after the clear command"
        )
    return {"cleared": True, "before_count": before_count, "after_count": 0}

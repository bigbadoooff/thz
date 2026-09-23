"""Read and write single write-map parameters, whatever their access mode.

Most firmwares expose every parameter as its own register ("direct"): the
value sits at WRITE_REGISTER_OFFSET in the register's response and is
written with a plain SET. On 2xx firmware the register map manager instead
marks parameters with ``write_mode="block"``: ``command`` is the parent block,
``offset``/``length`` locate the value inside it, and writing requires a
read-modify-write of the whole block (THZDevice.write_block_value). Writing
such a parameter with a plain SET would overwrite the start of the block.

Some 2xx parameters are single-bit flags sharing a byte (``bit`` in the
entry, e.g. the per-weekday program switches); those read as 0/1 and write
only their own bit.

Every caller that reads or writes a write-map entry goes through these
helpers so that the access mode is honoured in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .const import WRITE_REGISTER_LENGTH, WRITE_REGISTER_OFFSET

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .thz_device import THZDevice

WRITE_MODE_BLOCK = "block"


def is_block_parameter(entry: Mapping[str, Any]) -> bool:
    """Return True if the entry lives inside a 2xx register block."""
    return entry.get("write_mode") == WRITE_MODE_BLOCK


def parameter_length(entry: Mapping[str, Any]) -> int:
    """Return the number of value bytes the entry occupies on the device."""
    if is_block_parameter(entry):
        return int(entry["length"])
    return WRITE_REGISTER_LENGTH


async def async_read_parameter(
    hass: HomeAssistant, device: THZDevice, entry: Mapping[str, Any]
) -> bytes:
    """Read the raw value bytes of a write-map entry."""
    if is_block_parameter(entry):
        offset, length = int(entry["offset"]), int(entry["length"])
    else:
        offset, length = WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH
    result: bytes = await device.async_execute(
        hass,
        device.read_value,
        bytes.fromhex(entry["command"]),
        "get",
        offset,
        length,
    )
    bit = entry.get("bit")
    if bit is not None and result:
        return bytes([(result[0] >> int(bit)) & 0x01])
    return result


async def async_write_parameter(
    hass: HomeAssistant,
    device: THZDevice,
    entry: Mapping[str, Any],
    value_bytes: bytes,
) -> None:
    """Write already-encoded value bytes to a write-map entry.

    For block parameters ``value_bytes`` must be exactly
    ``parameter_length(entry)`` bytes long.
    """
    command = bytes.fromhex(entry["command"])
    if is_block_parameter(entry):
        bit = entry.get("bit")
        if bit is not None:
            # Single-bit flag: set/clear only this bit, keep its neighbours.
            flag = 1 if any(value_bytes) else 0
            await device.async_execute(
                hass,
                device.write_block_value,
                command,
                int(entry["offset"]),
                1,
                bytes([flag << int(bit)]),
                1 << int(bit),
            )
            return
        await device.async_execute(
            hass,
            device.write_block_value,
            command,
            int(entry["offset"]),
            int(entry["length"]),
            value_bytes,
        )
    else:
        await device.async_execute(hass, device.write_value, command, value_bytes)

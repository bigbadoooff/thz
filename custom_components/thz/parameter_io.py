"""Read and write single write-map parameters, whatever their access mode.

Most firmwares expose every parameter as its own register ("direct"): the
value sits at WRITE_REGISTER_OFFSET in the register's response and is
written with a plain SET. On 2xx firmware the parameter instead has a
``block`` layout: ``command`` is the parent block, the layout's offset and
length locate the value inside it, and writing requires a read-modify-write
of the whole block (THZDevice.write_block_value). Writing
such a parameter with a plain SET would overwrite the start of the block.

Some 2xx parameters are single-bit flags sharing a byte (``block.bit``,
e.g. the per-weekday program switches); those read as 0/1 and write
only their own bit.

Every caller that reads or writes a write-map parameter goes through these
helpers so that the access mode is honoured in one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import WRITE_REGISTER_LENGTH, WRITE_REGISTER_OFFSET

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .parameter_poller import ReadKey
    from .register_maps.model import WriteParam
    from .thz_device import THZDevice


def is_block_parameter(param: WriteParam) -> bool:
    """Return True if the parameter lives inside a 2xx register block."""
    return param.block is not None


def parameter_length(param: WriteParam) -> int:
    """Return the number of value bytes the parameter occupies on the device."""
    if param.block is not None:
        return param.block.length
    return WRITE_REGISTER_LENGTH


def block_coordinator_key(param: WriteParam) -> str | None:
    """Return the coordinator key ("pxx17") of a block parameter's block."""
    if param.block is None:
        return None
    return f"pxx{param.command.upper()}"


def parameter_from_block(param: WriteParam, block_data: bytes) -> bytes | None:
    """Cut a block parameter's value out of an already-read block response.

    ``block_data`` has the layout the block coordinators store (the decoded
    response: CRC, address echo, data), i.e. the same bytes a device read of
    the block returns. Returns None if the block is too short or ``param``
    is not a block parameter.
    """
    if param.block is None:
        return None
    offset, length = param.block.offset, param.block.length
    raw = block_data[offset : offset + length]
    if len(raw) < length:
        return None
    return parameter_from_read(param, raw)


def parameter_read_key(param: WriteParam) -> ReadKey:
    """Return the register read that holds the parameter: (command, offset, length).

    Bit flags sharing a byte share the key; parameter_from_read picks
    each flag's bit out of the bytes read.
    """
    if param.block is not None:
        return param.command, param.block.offset, param.block.length
    return param.command, WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH


def parameter_from_read(param: WriteParam, raw: bytes) -> bytes:
    """Return the parameter's value bytes from a read of its read key."""
    bit = param.block.bit if param.block is not None else None
    if bit is not None and raw:
        return bytes([(raw[0] >> bit) & 0x01])
    return raw


async def async_read_parameter(
    hass: HomeAssistant, device: THZDevice, param: WriteParam
) -> bytes:
    """Read the raw value bytes of a write-map parameter."""
    command, offset, length = parameter_read_key(param)
    result: bytes = await device.async_execute(
        device.read_value,
        bytes.fromhex(command),
        "get",
        offset,
        length,
    )
    return parameter_from_read(param, result)


async def async_write_parameter(
    hass: HomeAssistant,
    device: THZDevice,
    param: WriteParam,
    value_bytes: bytes,
) -> None:
    """Write already-encoded value bytes to a write-map parameter.

    For block parameters ``value_bytes`` must be exactly
    ``parameter_length(param)`` bytes long.
    """
    command = bytes.fromhex(param.command)
    block = param.block
    if block is None:
        await device.async_execute(device.write_value, command, value_bytes)
        return
    if block.bit is not None:
        # Single-bit flag: set/clear only this bit, keep its neighbours.
        flag = 1 if any(value_bytes) else 0
        await device.async_execute(
            device.write_block_value,
            command,
            block.offset,
            1,
            bytes([flag << block.bit]),
            1 << block.bit,
        )
        return
    await device.async_execute(
        device.write_block_value,
        command,
        block.offset,
        block.length,
        value_bytes,
    )

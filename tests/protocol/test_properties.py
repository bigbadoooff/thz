"""Property-based tests (hypothesis) for the protocol and value codec.

These state invariants that must hold for *every* input rather than for a
few hand-picked examples: encoding round-trips, escaping, frame parsing
across arbitrary read-chunk boundaries, time quantisation, and that a 2xx
block write only ever changes the bytes (or bits) of its own parameter.
"""

import asyncio
from datetime import time as dt_time

from hypothesis import given, settings, strategies as st
import pytest

from custom_components.thz.parameter_io import (
    async_read_parameter,
    async_write_parameter,
    is_block_parameter,
)
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManagerWrite,
)
from custom_components.thz.thz_device import THZDevice
from custom_components.thz.time import quarters_to_time, time_to_quarters
from custom_components.thz.value_codec import THZValueCodec
from tests.helpers import (
    ScriptedTransport,
    Simulated2xxDevice,
    device_with_transport,
)

_DEVICE = THZDevice(connection="usb", port="/dev/null")


# ---------------------------------------------------------------------------
# Value codec
# ---------------------------------------------------------------------------


@given(
    steps=st.integers(min_value=-32768, max_value=32767),
    step=st.sampled_from([0.01, 0.1, 0.5, 1.0]),
)
def test_signed_number_round_trips(steps, step):
    value = round(steps * step, 2)
    encoded = THZValueCodec.encode_number(value, step, "hex2int", 2)
    assert len(encoded) == 2
    assert THZValueCodec.decode_number(encoded, step, "hex2int") == pytest.approx(value)


@given(steps=st.integers(min_value=0, max_value=255), step=st.sampled_from([0.1, 1.0]))
def test_unsigned_single_byte_round_trips(steps, step):
    value = round(steps * step, 1)
    encoded = THZValueCodec.encode_number(value, step, "pClean", 1)
    assert THZValueCodec.decode_number(
        encoded, step, "pClean", signed=False
    ) == pytest.approx(value)


@given(value=st.integers(min_value=0, max_value=255))
def test_0clean_keeps_the_value_in_the_first_byte(value):
    encoded = THZValueCodec.encode_number(float(value), 1.0, "0clean")
    assert encoded == bytes([value, 0])
    assert THZValueCodec.decode_number(encoded, 1.0, "0clean") == value


@given(tenths=st.integers(min_value=-128, max_value=127))
def test_4temp_round_trips(tenths):
    value = tenths / 10
    encoded = THZValueCodec.encode_number(value, 0.1, "4temp")
    assert encoded[1] == 0  # value lives in the high byte
    assert THZValueCodec.decode_number(encoded, 0.1, "4temp") == pytest.approx(value)


# ---------------------------------------------------------------------------
# Telegram escaping and framing
# ---------------------------------------------------------------------------

# Payload bytes biased towards the protocol's special values, so that
# escaped 0x10 / 0x2B next to 0x03 actually occur.
_PROTOCOL_BYTES = st.one_of(
    st.sampled_from([0x10, 0x03, 0x2B, 0x18]), st.integers(0, 255)
)


@given(data=st.lists(_PROTOCOL_BYTES, max_size=64).map(bytes))
def test_unescape_inverts_escape(data):
    assert _DEVICE.unescape(_DEVICE.escape(data)) == data


@given(data=st.lists(_PROTOCOL_BYTES, max_size=64).map(bytes))
def test_escaped_data_never_contains_a_bare_escape_byte(data):
    escaped = _DEVICE.escape(data)
    # Every 0x10 comes in pairs, and every 0x2B is followed by 0x18.
    assert escaped.count(b"\x10") % 2 == 0
    assert escaped.count(b"\x2b") == escaped.count(b"\x2b\x18")


def _response_frame(payload: bytes) -> bytes:
    crc = _DEVICE.thz_checksum(b"\x01\x00\x00" + payload)
    return b"\x01\x00" + _DEVICE.escape(crc + payload) + b"\x10\x03"


@settings(max_examples=300)
@given(
    payload=st.lists(_PROTOCOL_BYTES, min_size=3, max_size=48).map(bytes),
    cuts=st.lists(st.integers(min_value=1, max_value=120), max_size=8),
)
def test_frame_is_read_completely_across_any_chunking(payload, cuts):
    frame = _response_frame(payload)
    bounds = sorted({c for c in cuts if c < len(frame)})
    chunks = [
        frame[start:end]
        for start, end in zip([0, *bounds], [*bounds, len(frame)], strict=True)
    ]
    device = device_with_transport(ScriptedTransport(chunks), read_timeout=1.0)
    received = asyncio.run(device._receive_data_telegram())

    assert received == frame
    crc = _DEVICE.thz_checksum(b"\x01\x00\x00" + payload)
    assert device.decode_response(received) == crc + payload


# ---------------------------------------------------------------------------
# Schedule times
# ---------------------------------------------------------------------------


@given(quarters=st.integers(min_value=0, max_value=95))
def test_quarters_round_trip(quarters):
    assert time_to_quarters(quarters_to_time(quarters)) == quarters


@given(hour=st.integers(0, 23), minute=st.integers(0, 59))
def test_time_is_floored_to_quarter_hours(hour, minute):
    stored = quarters_to_time(time_to_quarters(dt_time(hour, minute)))
    assert stored == dt_time(hour, minute - minute % 15)


# ---------------------------------------------------------------------------
# 2xx block writes touch only their own parameter
# ---------------------------------------------------------------------------

_BLOCK_PARAMS = {
    name: param
    for firmware in ("206", "214")
    for name, param in RegisterMapManagerWrite(firmware).params().items()
    if param.type == "number" and is_block_parameter(param)
}


@settings(max_examples=200, deadline=None)
@given(
    name=st.sampled_from(sorted(_BLOCK_PARAMS)),
    block=st.binary(min_size=48, max_size=48),
    raw=st.integers(min_value=0, max_value=0xFFFF),
)
def test_block_write_changes_only_its_own_parameter(name, block, raw):
    entry = _BLOCK_PARAMS[name]
    layout = entry.block
    addr = bytes.fromhex(entry.command)
    device = Simulated2xxDevice({addr: block})
    length = layout.length
    value = (raw % (1 << (8 * length))).to_bytes(length, "big")
    if layout.bit is not None:
        value = bytes([raw & 1])

    asyncio.run(async_write_parameter(None, device, entry, value))
    after = device.blocks[addr]

    start = layout.offset - 2  # CRC and address echo precede the data
    if layout.bit is not None:
        mask = 1 << layout.bit
        assert after[start] & ~mask & 0xFF == block[start] & ~mask & 0xFF
        assert bool(after[start] & mask) == bool(raw & 1)
        changed = range(start, start + 1)
    else:
        assert after[start : start + length] == value
        changed = range(start, start + length)
    for index in range(len(block)):
        if index not in changed:
            assert after[index] == block[index], index
    assert asyncio.run(async_read_parameter(None, device, entry)) == value

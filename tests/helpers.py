"""Test doubles shared by several test modules."""

import asyncio

from custom_components.thz.thz_device import THZDevice
from custom_components.thz.transport import THZTransport


class Simulated2xxDevice(THZDevice):
    """THZDevice whose transport is an in-memory 2xx block store."""

    def __init__(self, blocks: dict[bytes, bytes]) -> None:
        super().__init__(connection="usb", port="/dev/null")
        self.blocks = dict(blocks)
        self.sent: list[bytes] = []

    async def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        self.sent.append(telegram)
        # header (2) + escaped(CRC + address + data) + footer (2)
        body = self.unescape(telegram[2:-2])[1:]
        if get_or_set == "set":
            addr = body[:1]
            assert len(body) - 1 == len(self.blocks[addr]), (
                "block SET must carry the whole block exactly once"
            )
            self.blocks[addr] = body[1:]
            return b""
        addr = body[:1]
        data = addr + self.blocks[addr]
        crc = self.thz_checksum(b"\x01\x00\x00" + data)
        return self.escape(b"\x01\x00" + crc + data) + b"\x10\x03"


class ScriptedTransport(THZTransport):
    """In-memory transport: hands out scripted chunks or a responder's answers.

    ``chunks`` are returned by successive reads. ``responder`` is called with
    every written byte string and returns the bytes the device sends back.
    A read with nothing queued waits ``max_wait`` like the real transport.
    """

    def __init__(self, chunks=(), responder=None) -> None:
        super().__init__()
        self.incoming: list[bytes] = list(chunks)
        self.responder = responder
        self.written: list[bytes] = []
        self.alive = True
        self.connects = 0
        self.closes = 0
        self.resets = 0

    async def connect(self) -> None:
        self.connects += 1
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    async def write(self, data: bytes) -> None:
        self.written.append(data)
        if self.responder is not None:
            answer = self.responder(data)
            if answer:
                self.incoming.append(answer)

    async def read(self, max_wait: float) -> bytes:
        if self.incoming:
            return self.incoming.pop(0)
        await asyncio.sleep(max_wait)
        return b""

    async def reset_input_buffer(self) -> None:
        self.resets += 1
        if self.responder is not None:
            # Scripted chunks are the test's input; a responder's leftovers
            # (e.g. the answer to the closing 0x02) are stale input.
            self.incoming.clear()

    def close(self) -> None:
        self.closes += 1
        self.alive = False


def heat_pump_responder(frame: bytes):
    """Responder answering one exchange like the heat pump: 10, 10 02, frame."""

    def respond(data: bytes) -> bytes:
        if data == b"\x02":
            return b"\x10"
        if data == b"\x10":
            return frame
        return b"\x10\x02"

    return respond


def device_with_transport(transport, **kwargs) -> THZDevice:
    """A THZDevice talking to ``transport``, with a short read timeout."""
    kwargs.setdefault("connection", "usb")
    kwargs.setdefault("port", "/dev/null")
    kwargs.setdefault("read_timeout", 0.05)
    device = THZDevice(**kwargs)
    device._transport = transport
    return device


class FakeRegisterManager:
    """Read-map manager over hand-written block tuples, as the real one sees them.

    ``blocks`` maps a block ("pxxFB") to its map tuples
    ``(name, offset, length, decode, factor[, meta])``.
    """

    def __init__(self, blocks) -> None:
        from custom_components.thz.register_maps.model import ReadField

        self._blocks = {block: list(entries) for block, entries in blocks.items()}
        self._fields = {
            block: [ReadField.from_tuple(block, e) for e in entries]
            for block, entries in self._blocks.items()
        }

    def get_all_registers(self):
        return self._blocks

    def get_registers_for_block(self, block):
        return self._blocks.get(block, [])

    def fields(self):
        return self._fields

    def block_fields(self, block):
        return self._fields.get(block, [])

    def find_field(self, block, name):
        from custom_components.thz.register_maps.model import normalize_field_name

        wanted = normalize_field_name(name)
        return next((f for f in self.block_fields(block) if f.name == wanted), None)


def write_param(entry=None, name="test_param", **fields):
    """A WriteParam from a write-map style dict (missing keys get neutral values)."""
    from custom_components.thz.register_maps.model import WriteParam

    if isinstance(entry, WriteParam) and not fields:
        return entry
    data = {"command": "0A0000", "type": "number", "decode_type": "", **(entry or {})}
    data.update(fields)
    return WriteParam.from_entry(name, data)


class FakeWriteManager:
    """Write-map manager over hand-written dicts, typed like the real one."""

    def __init__(self, registers) -> None:
        self._registers = dict(registers)
        self._params = {
            name: write_param(entry, name=name) if isinstance(entry, dict) else entry
            for name, entry in registers.items()
        }

    def get_all_registers(self):
        return self._registers

    def params(self):
        return self._params

    def param(self, name):
        return self._params.get(name)


def make_climate(**kwargs):
    """THZClimate from the individual pieces a ClimateConfig is made of.

    Accepts write-map dicts for the ``*_entry`` arguments, block positions as
    ``*_offset``/``*_length`` pairs and the pxx0A0176 status coordinator and
    bits, and builds the entity's ClimateConfig from them.
    """
    from custom_components.thz.climate import ClimateConfig, StatusBits, THZClimate

    def param(key):
        value = kwargs.pop(key, None)
        return write_param(value, name=key) if isinstance(value, dict) else value

    def position(name):
        offset = kwargs.pop(f"{name}_offset", None)
        length = kwargs.pop(f"{name}_length", None)
        return None if offset is None or length is None else (offset, length)

    status_coordinator = kwargs.pop("cooling_coordinator", None)
    bits = {
        "byte": kwargs.pop("cooling_byte", None),
        "cooling_bit": kwargs.pop("cooling_bit", None),
        "compressor_bit": kwargs.pop("compressor_bit", None),
    }
    status = (
        StatusBits(coordinator=status_coordinator, **bits)
        if status_coordinator is not None or any(v is not None for v in bits.values())
        else None
    )
    config = ClimateConfig(
        target=position("target_temp"),
        current=position("current_temp"),
        op_mode=position("op_mode"),
        heat_setpoint=param("heat_setpoint_entry"),
        night_setpoint=param("night_setpoint_entry"),
        cool_switch=param("cool_switch_entry"),
        cool_setpoint=param("cool_setpoint_entry"),
        opmode=param("opmode_entry"),
        status=status,
    )
    coordinator = kwargs.pop("coordinator")
    return THZClimate(coordinator, config, **kwargs)


def make_runtime_data(**fields):
    """Build THZRuntimeData for tests; unspecified fields get neutral values."""
    from unittest.mock import MagicMock

    from custom_components.thz.runtime_data import THZRuntimeData

    fields.setdefault("device", MagicMock())
    fields.setdefault("device_id", "test_device")
    fields.setdefault("write_manager", None)
    fields.setdefault("register_manager", None)
    return THZRuntimeData(**fields)


def as_runtime_data(value):
    """Turn a non-empty dict into THZRuntimeData; other values pass through.

    An empty dict (or None) stands for an entry that is not loaded.
    """
    if isinstance(value, dict) and value:
        return make_runtime_data(**value)
    return value

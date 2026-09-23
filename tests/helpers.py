"""Test doubles shared by several test modules."""

from custom_components.thz.thz_device import THZDevice


class Simulated2xxDevice(THZDevice):
    """THZDevice whose transport is an in-memory 2xx block store."""

    def __init__(self, blocks: dict[bytes, bytes]) -> None:
        super().__init__(connection="usb", port="/dev/null")
        self.blocks = dict(blocks)
        self.sent: list[bytes] = []

    def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
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

    async def async_execute(self, hass, fn, *args, timeout: float = 8.0):  # noqa: ASYNC109
        return fn(*args)


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

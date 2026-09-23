"""Fixtures for tests against a real Home Assistant.

Uses pytest-homeassistant-custom-component (see requirements_test_ha.txt).

Unlike tests/, nothing here stubs Home Assistant: the integration is set up
through the real config-entry, entity-registry, translation and service
machinery. Only the serial/TCP line is replaced by FakeTHZDevice, a real
THZDevice whose send_request answers from in-memory registers.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import ClassVar
from unittest.mock import patch

import pytest

from custom_components.thz.thz_device import THZDevice

pytest_plugins = "pytest_homeassistant_custom_component"

FIRMWARE = 439
BLOCK_SIZE = 120


class FakeTHZDevice(THZDevice):
    """THZDevice speaking the real telegram format to in-memory registers."""

    instances: ClassVar[list[FakeTHZDevice]] = []
    # Firmware reported in register FD and extra register contents; tests
    # change these on the class before the integration creates the device.
    firmware: ClassVar[int] = FIRMWARE
    initial_registers: ClassVar[dict[bytes, bytes]] = {}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.registers: dict[bytes, bytes] = {
            b"\xfd": self.firmware.to_bytes(2, "big") + bytes(4),
            **self.initial_registers,
        }
        self.sent: list[bytes] = []
        self.closed = False
        FakeTHZDevice.instances.append(self)

    async def _connect(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        self.sent.append(telegram)
        body = self.unescape(telegram[2:-2])[1:]  # drop header, footer, CRC
        # 4.x parameters use 3-byte commands (0A/0B/0C...), blocks 1 byte.
        size = 3 if body[:1] in (b"\x0a", b"\x0b", b"\x0c") and len(body) >= 3 else 1
        command, data = body[:size], body[size:]
        if get_or_set == "set":
            self.registers[command] = data
            return b""
        default = bytes(2) if size == 3 else bytes(BLOCK_SIZE)
        payload = command + self.registers.get(command, default)
        crc = self.thz_checksum(b"\x01\x00\x00" + payload)
        return self.escape(b"\x01\x00" + crc + payload) + b"\x10\x03"

    def sets_for(self, command: str) -> list[bytes]:
        """Data bytes of every SET sent to a 3-byte command, oldest first."""
        cmd = bytes.fromhex(command)
        result = []
        for telegram in self.sent:
            if telegram[:2] != b"\x01\x80":
                continue
            body = self.unescape(telegram[2:-2])[1:]
            if body[:3] == cmd:
                result.append(body[3:])
        return result


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/thz in every test."""
    return


@pytest.fixture
def fake_device() -> Generator[type[FakeTHZDevice]]:
    """Replace the device class used by setup and the config flow."""
    FakeTHZDevice.instances = []
    FakeTHZDevice.firmware = FIRMWARE
    FakeTHZDevice.initial_registers = {}
    with (
        patch("custom_components.thz.THZDevice", FakeTHZDevice),
        patch("custom_components.thz.config_flow.THZDevice", FakeTHZDevice),
    ):
        yield FakeTHZDevice

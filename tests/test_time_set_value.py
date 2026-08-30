"""Tests for THZTime and THZScheduleTime's async_set_value().

Regression coverage for a bug where both entity classes defined
``async_set_native_value`` (the NumberEntity/SelectEntity override point)
instead of ``async_set_value`` (the real TimeEntity override point). Because
neither class actually overrode ``async_set_value``, every ``time.set_value``
service call silently fell through to the base ``TimeEntity``'s own
unimplemented ``set_value()``, raising ``NotImplementedError`` before ever
reaching the device -- shown to the user as
"Failed to perform the action time/set_value. unknown error" on every
attempted write, regardless of which entity or how many concurrent writes.

These tests instantiate the real entity classes against a mocked device and
hass, closely following the pattern used in test_async_update_block.py and
test_climate.py's TestTHZClimateEntity.
"""

import asyncio
from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_hass():
    """Create a mock hass whose async_add_executor_job actually calls through.

    Mirrors the real HomeAssistant.async_add_executor_job contract closely
    enough that the wrapped device method is genuinely invoked (and its
    call args captured) rather than merely returning a canned value.
    """
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    return hass


def _make_device(read_return: bytes | None = None):
    """Create a minimal mock THZDevice with a real asyncio lock."""
    device = MagicMock()
    device.lock = asyncio.Lock()
    if read_return is not None:
        device.read_value = MagicMock(return_value=read_return)
    return device


class TestTimeEntityOverridePoint:
    """Guard against regressing to the wrong TimeEntity override method name."""

    def test_thz_time_defines_async_set_value(self):
        """THZTime must override async_set_value (the real TimeEntity hook)."""
        from custom_components.thz.time import THZTime
        assert "async_set_value" in vars(THZTime)

    def test_thz_time_does_not_define_async_set_native_value(self):
        """async_set_native_value is the Number/Select convention, not Time's."""
        from custom_components.thz.time import THZTime
        assert "async_set_native_value" not in vars(THZTime)

    def test_thz_schedule_time_defines_async_set_value(self):
        """THZScheduleTime must override async_set_value too."""
        from custom_components.thz.time import THZScheduleTime
        assert "async_set_value" in vars(THZScheduleTime)

    def test_thz_schedule_time_does_not_define_async_set_native_value(self):
        """Same regression guard for the schedule start/end entity."""
        from custom_components.thz.time import THZScheduleTime
        assert "async_set_native_value" not in vars(THZScheduleTime)


class TestTHZTimeSetValue:
    """Tests for THZTime.async_set_value()."""

    @staticmethod
    def _make_entity(device):
        from custom_components.thz.time import THZTime
        entity = THZTime(
            name="Test Time",
            entry={"command": "0B0005"},
            device=device,
            device_id="test_device",
        )
        entity.hass = _make_hass()
        entity.async_write_ha_state = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_set_value_writes_correct_quarters(self):
        """14:30 -> 58 quarters, written as a 2-byte [num, 0] payload."""
        device = _make_device()
        device.write_value = MagicMock()
        entity = self._make_entity(device)

        await entity.async_set_value(time(14, 30))

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0005"), bytes([58, 0])
        )

    @pytest.mark.asyncio
    async def test_set_value_updates_native_value_and_writes_state(self):
        """The entity should optimistically reflect the newly-applied value."""
        device = _make_device()
        device.write_value = MagicMock()
        entity = self._make_entity(device)

        await entity.async_set_value(time(6, 0))

        assert entity.native_value == time(6, 0)
        entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_midnight_is_zero_quarters(self):
        """A plain (non-schedule) time entity treats 00:00 as 0, not end-of-day."""
        device = _make_device()
        device.write_value = MagicMock()
        entity = self._make_entity(device)

        await entity.async_set_value(time(0, 0))

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0005"), bytes([0, 0])
        )


class TestTHZScheduleTimeSetValue:
    """Tests for THZScheduleTime.async_set_value() (start and end)."""

    @staticmethod
    def _make_entity(device, time_type):
        from custom_components.thz.time import THZScheduleTime
        entity = THZScheduleTime(
            name=f"Test Schedule {time_type.title()}",
            base_name="programHC1_Mo_0",
            entry={"command": "0B0100"},
            device=device,
            device_id="test_device",
            time_type=time_type,
        )
        entity.hass = _make_hass()
        entity.async_write_ha_state = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_start_time_modifies_only_first_byte(self):
        """Setting the start time must preserve the existing end byte."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "start")

        await entity.async_set_value(time(1, 30))  # 1:30 -> 6 quarters

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0100"), bytes([6, 20, 0, 0])
        )

    @pytest.mark.asyncio
    async def test_end_time_modifies_only_second_byte(self):
        """Setting the end time must preserve the existing start byte."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "end")

        await entity.async_set_value(time(2, 0))  # 2:00 -> 8 quarters

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0100"), bytes([10, 8, 0, 0])
        )

    @pytest.mark.asyncio
    async def test_end_time_midnight_encodes_as_end_of_day(self):
        """00:00 on an end-time slot means 24:00 (end of day) -> 96, not 0."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "end")

        await entity.async_set_value(time(0, 0))

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0100"), bytes([10, 96, 0, 0])
        )

    @pytest.mark.asyncio
    async def test_start_time_midnight_stays_zero(self):
        """00:00 on a start-time slot is a normal midnight start -> 0, not 96."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "start")

        await entity.async_set_value(time(0, 0))

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0100"), bytes([0, 20, 0, 0])
        )

    @pytest.mark.asyncio
    async def test_set_value_updates_native_value_and_writes_state(self):
        """The schedule entity should also optimistically update its own state."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "start")

        await entity.async_set_value(time(3, 45))

        assert entity.native_value == time(3, 45)
        entity.async_write_ha_state.assert_called_once()

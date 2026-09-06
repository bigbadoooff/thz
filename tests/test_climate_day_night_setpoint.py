"""Tests for THZClimate's day/night setpoint write logic.

Regression coverage: HC1, HC2, and DHW each have independently-scheduled
day and night setpoint registers (e.g. p01RoomTempDayHC1 /
p02RoomTempNightHC1); the device itself decides which one is currently
active and reports its value via roomSetTemp. The old code always wrote the
day register, which silently no-op'd from the user's point of view whenever
night mode was the one actually in effect -- the write would "succeed" but
the device would keep using whatever the night register already held.
_async_write_heat_setpoint now reads both registers fresh and writes to
whichever one currently matches the live roomSetTemp reading, falling back
to the day register if neither matches closely (e.g. right at a day/night
transition) or if no night register is configured at all.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.thz.climate import THZClimate


_DAY_ENTRY = {"command": "0A0080", "min": "10", "max": "30", "step": "0.1"}
_NIGHT_ENTRY = {"command": "0A0081", "min": "10", "max": "30", "step": "0.1"}


def _make_entity(*, heat_setpoint_entry=_DAY_ENTRY, night_setpoint_entry=None):
    coordinator = MagicMock()
    coordinator.data = None

    device = MagicMock()
    device.lock = asyncio.Lock()

    entity = THZClimate(
        coordinator=coordinator,
        cooling_coordinator=None,
        device=device,
        device_id="test_device",
        translation_key="Heating Circuit 1",
        current_temp_offset=0,
        current_temp_length=2,
        target_temp_offset=2,
        target_temp_length=2,
        op_mode_offset=24,
        op_mode_length=1,
        heat_setpoint_entry=heat_setpoint_entry,
        cool_switch_entry=None,
        cool_setpoint_entry=None,
        night_setpoint_entry=night_setpoint_entry,
    )
    entity.hass = MagicMock()
    entity.name = "Test Entity"
    # target_temperature reads from coordinator.data via _read_temp; patch it
    # directly instead, since these tests care about setpoint selection, not
    # temperature decoding.
    return entity


class TestWriteHeatSetpointWithoutNightRegister:
    """No night register configured -- behaves exactly as before."""

    @pytest.mark.asyncio
    async def test_writes_day_register(self):
        entity = _make_entity()
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        await entity._async_write_heat_setpoint(21.5)

        entity._device.async_execute.assert_called_once()
        write_call = entity._device.async_execute.call_args
        assert write_call[0][1] == entity._device.write_value
        assert write_call[0][2] == bytes.fromhex(_DAY_ENTRY["command"])

    @pytest.mark.asyncio
    async def test_warns_and_noops_with_no_entries_at_all(self):
        entity = _make_entity(heat_setpoint_entry=None)
        entity._device.async_execute = AsyncMock()

        await entity._async_write_heat_setpoint(21.5)

        entity._device.async_execute.assert_not_called()


class TestWriteHeatSetpointWithNightRegister:
    """Night register configured -- writes to whichever is currently active."""

    @pytest.mark.asyncio
    async def test_writes_night_register_when_night_is_active(self):
        entity = _make_entity(night_setpoint_entry=_NIGHT_ENTRY)

        async def fake_read_setpoint(entry):
            if entry is _NIGHT_ENTRY:
                return 18.0
            return 21.0  # day register reads something different

        entity._async_read_setpoint = fake_read_setpoint
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        # Live roomSetTemp reports 18.0 -- matches the night setpoint value.
        with patch.object(
            type(entity), "target_temperature", new_callable=PropertyMock
        ) as mock_target_temp:
            mock_target_temp.return_value = 18.0
            await entity._async_write_heat_setpoint(17.0)

        write_call = entity._device.async_execute.call_args
        assert write_call[0][2] == bytes.fromhex(_NIGHT_ENTRY["command"])

    @pytest.mark.asyncio
    async def test_writes_day_register_when_day_is_active(self):
        entity = _make_entity(night_setpoint_entry=_NIGHT_ENTRY)

        async def fake_read_setpoint(entry):
            if entry is _NIGHT_ENTRY:
                return 18.0
            return 21.0

        entity._async_read_setpoint = fake_read_setpoint
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            type(entity), "target_temperature", new_callable=PropertyMock
        ) as mock_target_temp:
            mock_target_temp.return_value = 21.0
            await entity._async_write_heat_setpoint(22.0)

        write_call = entity._device.async_execute.call_args
        assert write_call[0][2] == bytes.fromhex(_DAY_ENTRY["command"])

    @pytest.mark.asyncio
    async def test_falls_back_to_day_when_neither_register_matches(self):
        """At a day/night transition, or if reads fail, default to day."""
        entity = _make_entity(night_setpoint_entry=_NIGHT_ENTRY)

        async def fake_read_setpoint(entry):
            if entry is _NIGHT_ENTRY:
                return 18.0
            return 21.0

        entity._async_read_setpoint = fake_read_setpoint
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            type(entity), "target_temperature", new_callable=PropertyMock
        ) as mock_target_temp:
            mock_target_temp.return_value = 19.5  # matches neither register
            await entity._async_write_heat_setpoint(20.0)

        write_call = entity._device.async_execute.call_args
        assert write_call[0][2] == bytes.fromhex(_DAY_ENTRY["command"])

    @pytest.mark.asyncio
    async def test_falls_back_to_day_when_target_temperature_unknown(self):
        """No live roomSetTemp reading yet -- skip the day/night probe."""
        entity = _make_entity(night_setpoint_entry=_NIGHT_ENTRY)

        entity._async_read_setpoint = AsyncMock()
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            type(entity), "target_temperature", new_callable=PropertyMock
        ) as mock_target_temp:
            mock_target_temp.return_value = None
            await entity._async_write_heat_setpoint(20.0)

        entity._async_read_setpoint.assert_not_called()
        write_call = entity._device.async_execute.call_args
        assert write_call[0][2] == bytes.fromhex(_DAY_ENTRY["command"])


class TestAsyncReadSetpoint:
    @pytest.mark.asyncio
    async def test_decodes_value_from_device(self):
        entity = _make_entity()
        entity._device.async_execute = AsyncMock(
            return_value=bytes.fromhex("00d2")  # 210 * step(0.1) -> 21.0
        )

        result = await entity._async_read_setpoint(_DAY_ENTRY)

        assert result == 21.0

    @pytest.mark.asyncio
    async def test_returns_none_on_device_error(self):
        entity = _make_entity()
        entity._device.async_execute = AsyncMock(
            side_effect=ConnectionError("device unreachable")
        )

        result = await entity._async_read_setpoint(_DAY_ENTRY)

        assert result is None

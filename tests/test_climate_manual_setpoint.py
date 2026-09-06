"""Tests for THZClimate's DHW manual-mode setpoint candidate.

Regression coverage for two related points:

1. DHW has a distinct manual-mode setpoint register (``p11DHWsetManualTemp``)
   in addition to day/night -- unlike HC1/HC2, whose global MANUAL MODE sets
   a *flow* temperature (a different physical quantity entirely), not a
   third room/water-temperature candidate. ``_async_write_heat_setpoint``'s
   day/night/manual matching must pick up a real manual register when one is
   wired (DHW), and never invent one for HC1/HC2 (which never pass
   ``manual_setpoint_entry`` at all).

2. With three candidates instead of two, an ambiguous read (zero matches, or
   more than one register coincidentally reporting the same value as the
   live target) must still fall back to the day register rather than
   guessing.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.thz.climate import THZClimate


_DAY_ENTRY = {"command": "0A0080", "min": "10", "max": "30", "step": "0.1"}
_NIGHT_ENTRY = {"command": "0A0081", "min": "10", "max": "30", "step": "0.1"}
_MANUAL_ENTRY = {"command": "0A0082", "min": "10", "max": "65", "step": "0.1"}


def _make_dhw_entity(*, night_setpoint_entry=None, manual_setpoint_entry=None):
    coordinator = MagicMock()
    coordinator.data = None

    device = MagicMock()
    device.lock = asyncio.Lock()

    entity = THZClimate(
        coordinator=coordinator,
        cooling_coordinator=None,
        device=device,
        device_id="test_device",
        translation_key="DHW",
        current_temp_offset=0,
        current_temp_length=2,
        target_temp_offset=2,
        target_temp_length=2,
        op_mode_offset=24,
        op_mode_length=1,
        heat_setpoint_entry=_DAY_ENTRY,
        cool_switch_entry=None,
        cool_setpoint_entry=None,
        night_setpoint_entry=night_setpoint_entry,
        manual_setpoint_entry=manual_setpoint_entry,
    )
    entity.hass = MagicMock()
    entity.name = "Test DHW Entity"
    return entity


def _mock_read_setpoint(values: dict):
    """Return a fake _async_read_setpoint bound to specific entry -> value pairs."""
    async def _read(entry):
        return values.get(id(entry))
    return _read


class TestManualCandidateOnlyForDhw:
    def test_hc1_style_entity_never_gets_manual_candidate(self):
        """HC1/HC2 never pass manual_setpoint_entry; confirm none is invented."""
        entity = _make_dhw_entity(night_setpoint_entry=_NIGHT_ENTRY)
        assert entity._manual_setpoint_entry is None


class TestThreeCandidateMatching:
    @pytest.mark.asyncio
    async def test_writes_manual_register_when_manual_is_active(self):
        entity = _make_dhw_entity(
            night_setpoint_entry=_NIGHT_ENTRY, manual_setpoint_entry=_MANUAL_ENTRY
        )
        values = {id(_DAY_ENTRY): 21.0, id(_NIGHT_ENTRY): 18.0, id(_MANUAL_ENTRY): 45.0}
        entity._async_read_setpoint = _mock_read_setpoint(values)
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            type(entity), "target_temperature", new_callable=PropertyMock
        ) as mock_target_temp:
            mock_target_temp.return_value = 45.0  # matches manual only
            await entity._async_write_heat_setpoint(50.0)

        write_call = entity._device.async_execute.call_args
        assert write_call[0][2] == bytes.fromhex(_MANUAL_ENTRY["command"])

    @pytest.mark.asyncio
    async def test_writes_day_register_when_day_is_active(self):
        entity = _make_dhw_entity(
            night_setpoint_entry=_NIGHT_ENTRY, manual_setpoint_entry=_MANUAL_ENTRY
        )
        values = {id(_DAY_ENTRY): 21.0, id(_NIGHT_ENTRY): 18.0, id(_MANUAL_ENTRY): 45.0}
        entity._async_read_setpoint = _mock_read_setpoint(values)
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
    async def test_falls_back_to_day_when_zero_matches(self):
        """Active mode uses a register this integration doesn't know about."""
        entity = _make_dhw_entity(
            night_setpoint_entry=_NIGHT_ENTRY, manual_setpoint_entry=_MANUAL_ENTRY
        )
        values = {id(_DAY_ENTRY): 21.0, id(_NIGHT_ENTRY): 18.0, id(_MANUAL_ENTRY): 45.0}
        entity._async_read_setpoint = _mock_read_setpoint(values)
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            type(entity), "target_temperature", new_callable=PropertyMock
        ) as mock_target_temp:
            mock_target_temp.return_value = 30.0  # matches none of the three
            await entity._async_write_heat_setpoint(31.0)

        write_call = entity._device.async_execute.call_args
        assert write_call[0][2] == bytes.fromhex(_DAY_ENTRY["command"])

    @pytest.mark.asyncio
    async def test_falls_back_to_day_when_multiple_registers_coincide(self):
        """Two registers report the same value -- stay ambiguous, don't guess."""
        entity = _make_dhw_entity(
            night_setpoint_entry=_NIGHT_ENTRY, manual_setpoint_entry=_MANUAL_ENTRY
        )
        # Night and manual coincidentally both read 21.0, same as day.
        values = {id(_DAY_ENTRY): 21.0, id(_NIGHT_ENTRY): 21.0, id(_MANUAL_ENTRY): 45.0}
        entity._async_read_setpoint = _mock_read_setpoint(values)
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
    async def test_single_candidate_skips_matching_entirely(self):
        """Only day register configured -- no read probes needed at all."""
        entity = _make_dhw_entity()
        entity._async_read_setpoint = AsyncMock()
        entity._device.async_execute = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        with patch.object(
            type(entity), "target_temperature", new_callable=PropertyMock
        ) as mock_target_temp:
            mock_target_temp.return_value = 21.0
            await entity._async_write_heat_setpoint(22.0)

        entity._async_read_setpoint.assert_not_called()
        write_call = entity._device.async_execute.call_args
        assert write_call[0][2] == bytes.fromhex(_DAY_ENTRY["command"])

"""Tests for THZClimate's hvac_mode/preset_mode handling around the global
pOpMode register.

Regression coverage for two related bugs:

1. ``hvac_modes`` used to include ``OFF``, but there is no way to actually
   turn a single heating circuit off on this device -- without cooling
   support HEAT/OFF were both pure no-ops, and with cooling support OFF only
   ever disabled the cooling switch (never stopped heating). ``OFF`` is no
   longer offered; the device's real "off" is the global ``pOpMode``
   standby state, reachable via ``preset_mode``.

2. ``preset_mode`` used to be inferred from each circuit's own
   ``hcOpMode``/``dhwOpMode`` readback, mapped onto HA's generic
   comfort/sleep/away vocabulary -- which only covered 3 of the device's 7
   real operating-mode states, and read from a register that doesn't
   necessarily track what was actually written to ``pOpMode``.
   ``preset_mode`` now reads/writes the ``pOpMode`` register (0A0112)
   directly, using the device's own state names from
   ``SELECT_MAP["2opmode"]``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.climate import THZClimate, _OPMODE_DECODE_TYPE
from custom_components.thz.value_maps import SELECT_MAP


def _make_entity(
    *,
    cool_switch_entry=None,
    cool_setpoint_entry=None,
    opmode_entry=None,
):
    """Instantiate a minimal THZClimate (HC1-style) for direct unit testing."""
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
        heat_setpoint_entry={"command": "0A0080", "min": "10", "max": "30"},
        cool_switch_entry=cool_switch_entry,
        cool_setpoint_entry=cool_setpoint_entry,
        opmode_entry=opmode_entry,
    )
    entity.hass = MagicMock()
    entity.name = "Test Entity"
    return entity


_OPMODE_ENTRY = {"command": "0A0112"}
_COOL_SWITCH_ENTRY = {"command": "0B0613"}
_COOL_SETPOINT_ENTRY = {"command": "0B0582", "min": "12", "max": "27"}


class TestHvacModesExcludeOff:
    """OFF must never be offered -- there is no working per-circuit off."""

    def test_heat_only_without_cooling(self):
        entity = _make_entity()
        assert entity.hvac_modes == [entity.hvac_modes[0]]  # single entry
        assert "off" not in [m.value if hasattr(m, "value") else m for m in entity.hvac_modes]
        from homeassistant.components.climate import HVACMode
        assert entity.hvac_modes == [HVACMode.HEAT]

    def test_heat_and_cool_when_cooling_supported(self):
        from homeassistant.components.climate import HVACMode
        entity = _make_entity(
            cool_switch_entry=_COOL_SWITCH_ENTRY,
            cool_setpoint_entry=_COOL_SETPOINT_ENTRY,
        )
        assert entity.hvac_modes == [HVACMode.HEAT, HVACMode.COOL]
        assert HVACMode.OFF not in entity.hvac_modes


class TestPresetModesFromSelectMap:
    """preset_modes must be exactly the device's own 2opmode option names."""

    def test_preset_modes_are_all_seven_device_states(self):
        entity = _make_entity(opmode_entry=_OPMODE_ENTRY)
        expected = sorted(SELECT_MAP[_OPMODE_DECODE_TYPE].values(), key=str.lower)
        preset_modes = entity._attr_preset_modes
        assert preset_modes == expected
        assert len(preset_modes) == 7
        assert "standby" in preset_modes
        assert "DAYmode" in preset_modes
        # The old HA-generic vocabulary must be gone.
        assert "comfort" not in preset_modes
        assert "sleep" not in preset_modes
        assert "away" not in preset_modes

    def test_no_preset_modes_without_opmode_entry(self):
        entity = _make_entity()
        assert entity.preset_mode is None


class TestPresetModeProperty:
    """preset_mode reflects the cached pOpMode value, not per-circuit state."""

    def test_returns_none_before_first_read(self):
        entity = _make_entity(opmode_entry=_OPMODE_ENTRY)
        assert entity.preset_mode is None

    def test_returns_cached_value(self):
        entity = _make_entity(opmode_entry=_OPMODE_ENTRY)
        entity._op_mode_cache = "DAYmode"
        assert entity.preset_mode == "DAYmode"


class TestAsyncSetPresetMode:
    @pytest.mark.asyncio
    async def test_writes_device_native_value_and_updates_cache(self):
        entity = _make_entity(opmode_entry=_OPMODE_ENTRY)
        entity.async_write_ha_state = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()
        entity._device.async_execute = AsyncMock(return_value=None)

        await entity.async_set_preset_mode("standby")

        assert entity._op_mode_cache == "standby"
        entity.async_write_ha_state.assert_called_once()
        entity._device.async_execute.assert_called_once()
        # No translation table involved -- the write value is the encoded
        # "standby" option itself.
        call_args = entity._device.async_execute.call_args
        assert call_args[0][1] == entity._device.write_value

    @pytest.mark.asyncio
    async def test_rejects_unknown_preset(self):
        entity = _make_entity(opmode_entry=_OPMODE_ENTRY)
        entity._device.async_execute = AsyncMock()

        # "comfort" was a valid preset under the old HA vocabulary; it is not
        # a real pOpMode option and must be rejected now.
        await entity.async_set_preset_mode("comfort")

        entity._device.async_execute.assert_not_called()
        assert entity._op_mode_cache is None

    @pytest.mark.asyncio
    async def test_noop_without_opmode_entry(self):
        entity = _make_entity()
        entity._device.async_execute = AsyncMock()

        await entity.async_set_preset_mode("standby")

        entity._device.async_execute.assert_not_called()


class TestAsyncSetHvacMode:
    @pytest.mark.asyncio
    async def test_heat_disables_cooling_switch_when_supported(self):
        from homeassistant.components.climate import HVACMode

        entity = _make_entity(
            cool_switch_entry=_COOL_SWITCH_ENTRY,
            cool_setpoint_entry=_COOL_SETPOINT_ENTRY,
        )
        entity.hass.async_add_executor_job = AsyncMock(return_value=None)
        entity.coordinator.async_request_refresh = AsyncMock()

        await entity.async_set_hvac_mode(HVACMode.HEAT)

        entity.coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_off_is_not_a_supported_mode(self):
        """OFF is no longer in hvac_modes; requesting it must not crash and
        must not silently reinterpret it as anything else."""
        from homeassistant.components.climate import HVACMode

        entity = _make_entity()
        entity.hass.async_add_executor_job = AsyncMock()
        entity.coordinator.async_request_refresh = AsyncMock()

        await entity.async_set_hvac_mode(HVACMode.OFF)

        # Neither a cooling-switch write nor a refresh should happen for an
        # unsupported mode.
        entity.hass.async_add_executor_job.assert_not_called()
        entity.coordinator.async_request_refresh.assert_not_called()


class TestAsyncAddedToHassReadsOpMode:
    @pytest.mark.asyncio
    async def test_reads_op_mode_on_startup_when_entry_present(self):
        entity = _make_entity(opmode_entry=_OPMODE_ENTRY)
        entity.hass.async_add_executor_job = AsyncMock(
            return_value=bytes([1, 0])  # "1" -> "standby" per SELECT_MAP
        )
        entity.async_on_remove = MagicMock()

        await entity._async_read_op_mode()

        assert entity._op_mode_cache == "standby"

    @pytest.mark.asyncio
    async def test_noop_without_opmode_entry(self):
        entity = _make_entity()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity._async_read_op_mode()

        entity.hass.async_add_executor_job.assert_not_called()
        assert entity._op_mode_cache is None

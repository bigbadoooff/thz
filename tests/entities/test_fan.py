"""Tests for fan.py (THZFan and async_setup_entry)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.fan import THZFan, async_setup_entry
from tests.helpers import FakeWriteManager, make_runtime_data, write_param

_STAGE = {"command": "0A056C", "min": "0", "max": "3", "decode_type": "1clean"}
_BOOST = {"command": "0A05DD", "min": "0", "max": "3", "decode_type": "1clean"}


def _device(read=None):
    device = MagicMock()
    device.async_execute = AsyncMock(return_value=read)
    return device


def _fan(*, boost=_BOOST, device=None):
    entity = THZFan(
        stage=write_param(_STAGE, name="p07FanStageDay"),
        boost=write_param(boost, name="p99startUnschedVent") if boost else None,
        device=device or _device(),
        device_id="dev1",
    )
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    return entity


def _written(fan):
    """(command, value bytes) of each write the fan sent."""
    return [
        (call.args[2], call.args[3])
        for call in fan._device.async_execute.await_args_list
    ]


def _stage_bytes(stage):
    return stage.to_bytes(2, "big", signed=True)


class TestAsyncSetupEntry:
    @staticmethod
    def _config_entry(registers):
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {}
        config_entry.runtime_data = make_runtime_data(
            write_manager=FakeWriteManager(registers), device_id="dev1"
        )
        return config_entry

    @pytest.mark.asyncio
    async def test_creates_fan_with_boost(self):
        add = MagicMock()
        config_entry = self._config_entry(
            {"p07FanStageDay": _STAGE, "p99startUnschedVent": _BOOST}
        )
        await async_setup_entry(MagicMock(), config_entry, add)
        entities, update_before_add = add.call_args[0]
        assert update_before_add is True
        assert len(entities) == 1
        assert entities[0]._boost_param is not None

    @pytest.mark.asyncio
    async def test_creates_fan_without_boost(self):
        add = MagicMock()
        config_entry = self._config_entry({"p07FanStageDay": _STAGE})
        await async_setup_entry(MagicMock(), config_entry, add)
        (entities, _) = add.call_args[0]
        assert entities[0]._boost_param is None

    @pytest.mark.asyncio
    async def test_no_fan_stage_no_entity(self):
        add = MagicMock()
        await async_setup_entry(MagicMock(), self._config_entry({}), add)
        add.assert_not_called()


class TestState:
    def test_features_with_boost(self):
        from homeassistant.components.fan import FanEntityFeature

        fan = _fan()
        assert fan._attr_supported_features & FanEntityFeature.PRESET_MODE
        assert fan._attr_supported_features & FanEntityFeature.SET_SPEED
        assert fan._attr_preset_modes == ["boost"]
        assert fan._attr_speed_count == 3
        assert fan._attr_unique_id == "thz_dev1_fan_ventilation"

    def test_features_without_boost(self):
        from homeassistant.components.fan import FanEntityFeature

        fan = _fan(boost=None)
        assert not fan._attr_supported_features & FanEntityFeature.PRESET_MODE

    def test_unknown_before_first_read(self):
        fan = _fan()
        assert fan.is_on is None
        assert fan.percentage is None
        assert fan.preset_mode is None

    @pytest.mark.parametrize(
        ("stage", "is_on", "percentage"),
        [(0, False, 0), (1, True, 33), (2, True, 66), (3, True, 100)],
    )
    @pytest.mark.asyncio
    async def test_update_reads_stage(self, stage, is_on, percentage):
        fan = _fan(device=_device(_stage_bytes(stage)))
        await fan.async_update()
        assert fan.is_on is is_on
        assert fan.percentage == percentage

    @pytest.mark.asyncio
    async def test_update_without_data_keeps_state(self):
        fan = _fan(device=_device(b""))
        await fan.async_update()
        assert fan.percentage is None

    @pytest.mark.asyncio
    async def test_update_decode_error_keeps_state(self, monkeypatch):
        from custom_components.thz import fan as fan_module

        monkeypatch.setattr(
            fan_module.THZValueCodec,
            "decode_number",
            MagicMock(side_effect=ValueError("bad")),
        )
        fan = _fan(device=_device(_stage_bytes(2)))
        await fan.async_update()
        assert fan.percentage is None


class TestWrites:
    @pytest.mark.parametrize(
        ("percentage", "stage"),
        [(0, 0), (1, 1), (33, 1), (34, 2), (66, 2), (67, 3), (100, 3)],
    )
    @pytest.mark.asyncio
    async def test_set_percentage(self, percentage, stage):
        fan = _fan()
        await fan.async_set_percentage(percentage)
        assert _written(fan) == [(bytes.fromhex("0A056C"), _stage_bytes(stage))]
        assert fan.is_on is (stage > 0)
        fan.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off_then_on_restores_last_stage(self):
        fan = _fan()
        await fan.async_set_percentage(66)
        await fan.async_turn_off()
        assert fan.is_on is False
        await fan.async_turn_on()
        assert _written(fan)[-1] == (bytes.fromhex("0A056C"), _stage_bytes(2))
        assert fan.is_on is True

    @pytest.mark.asyncio
    async def test_turn_on_default_stage_is_one(self):
        fan = _fan()
        await fan.async_turn_on()
        assert _written(fan) == [(bytes.fromhex("0A056C"), _stage_bytes(1))]

    @pytest.mark.asyncio
    async def test_turn_on_with_percentage(self):
        fan = _fan()
        await fan.async_turn_on(percentage=100)
        assert _written(fan) == [(bytes.fromhex("0A056C"), _stage_bytes(3))]

    @pytest.mark.asyncio
    async def test_turn_on_with_boost(self):
        fan = _fan()
        await fan.async_turn_on(preset_mode="boost")
        assert _written(fan) == [(bytes.fromhex("0A05DD"), _stage_bytes(3))]

    @pytest.mark.asyncio
    async def test_boost_writes_stage_three(self):
        fan = _fan()
        await fan.async_set_preset_mode("boost")
        assert _written(fan) == [(bytes.fromhex("0A05DD"), _stage_bytes(3))]
        assert fan.preset_mode is None

    @pytest.mark.asyncio
    async def test_unknown_preset_is_ignored(self):
        fan = _fan()
        await fan.async_set_preset_mode("sleep")
        fan._device.async_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_boost_without_parameter_is_ignored(self):
        fan = _fan(boost=None)
        await fan.async_set_preset_mode("boost")
        fan._device.async_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_boost_device_error_is_logged(self):
        device = _device()
        device.async_execute.side_effect = OSError("boom")
        fan = _fan(device=device)
        await fan.async_set_preset_mode("boost")  # Should not raise.

    @pytest.mark.asyncio
    async def test_stage_device_error_keeps_state(self):
        device = _device()
        device.async_execute.side_effect = OSError("boom")
        fan = _fan(device=device)
        await fan.async_set_percentage(100)
        assert fan.percentage is None
        fan.async_write_ha_state.assert_not_called()

"""Coverage tests for switch.py (THZSwitch entity and async_setup_entry)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.switch import THZSwitch, async_setup_entry


def _make_device():
    device = MagicMock()
    device.lock = asyncio.Lock()
    device.write_value = MagicMock()
    device.async_execute = AsyncMock()
    return device


def _switch_entry(command="0A0700"):
    return {"command": command, "type": "switch", "icon": "mdi:toggle-switch"}


def _make_entity(name="pSwitchTest", entry=None, device=None):
    entity = THZSwitch(
        name=name,
        entry=entry or _switch_entry(),
        device=device or _make_device(),
        device_id="dev1",
    )
    entity.name = name
    return entity


class TestAsyncSetupEntry:
    """Tests for switch.py's async_setup_entry via async_setup_write_platform."""

    @pytest.mark.asyncio
    async def test_creates_switch_entities(self):
        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "pSwitchOne": _switch_entry("0A0701"),
            "pNumberOne": {"command": "0A0702", "type": "number"},
        }

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "entry1": {
                    "write_manager": write_manager,
                    "device": _make_device(),
                    "device_id": "dev1",
                }
            }
        }
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {}

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities, update_before_add = async_add_entities.call_args[0]
        assert len(entities) == 1
        assert isinstance(entities[0], THZSwitch)
        assert update_before_add is True


class TestTHZSwitchInit:
    """Tests for THZSwitch initialization."""

    def test_init_defaults(self):
        entity = _make_entity()
        assert entity.is_on is False
        assert entity._command == "0A0700"


class TestTHZSwitchUpdate:
    """Tests for THZSwitch.async_update."""

    @pytest.mark.asyncio
    async def test_async_update_on(self):
        entity = _make_entity()
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=bytes([0, 1]))

        await entity.async_update()

        assert entity.is_on is True

    @pytest.mark.asyncio
    async def test_async_update_off(self):
        entity = _make_entity()
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=bytes([0, 0]))

        await entity.async_update()

        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_async_update_no_data_keeps_previous(self):
        entity = _make_entity()
        entity._is_on = True
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=b"")

        await entity.async_update()

        assert entity.is_on is True

    @pytest.mark.asyncio
    async def test_async_update_decode_error_keeps_previous(self, monkeypatch):
        entity = _make_entity()
        entity._is_on = False
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=bytes([0, 1]))

        from custom_components.thz import switch as switch_mod

        def _raise(*_args, **_kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(switch_mod.THZValueCodec, "decode_switch", _raise)

        await entity.async_update()

        assert entity.is_on is False  # unchanged on error


class TestTHZSwitchTurnOnOff:
    """Tests for THZSwitch.async_turn_on / async_turn_off."""

    @pytest.mark.asyncio
    async def test_async_turn_on_success(self):
        device = _make_device()
        entity = _make_entity(device=device)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_on()

        assert entity.is_on is True
        entity.async_write_ha_state.assert_called_once()
        write_call = device.async_execute.call_args[0]
        assert write_call[1] == device.write_value
        assert write_call[3] == bytes([0, 1])

    @pytest.mark.asyncio
    async def test_async_turn_off_success(self):
        device = _make_device()
        entity = _make_entity(device=device)
        entity._is_on = True
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_off()

        assert entity.is_on is False
        entity.async_write_ha_state.assert_called_once()
        write_call = device.async_execute.call_args[0]
        assert write_call[3] == bytes([0, 0])

    @pytest.mark.asyncio
    async def test_async_turn_on_encode_error_logged_not_raised(self, monkeypatch):
        entity = _make_entity()
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        from custom_components.thz import switch as switch_mod

        def _raise(*_args, **_kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(switch_mod.THZValueCodec, "encode_switch", _raise)

        # Should not raise; error is caught and logged.
        await entity.async_turn_on()

        entity._device.async_execute.assert_not_awaited()
        entity.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_turn_off_encode_error_logged_not_raised(self, monkeypatch):
        entity = _make_entity()
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        from custom_components.thz import switch as switch_mod

        def _raise(*_args, **_kwargs):
            raise TypeError("boom")

        monkeypatch.setattr(switch_mod.THZValueCodec, "encode_switch", _raise)

        await entity.async_turn_off()

        entity._device.async_execute.assert_not_awaited()
        entity.async_write_ha_state.assert_not_called()

"""Coverage tests for select.py (THZSelect entity and async_setup_entry)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.select import THZSelect, async_setup_entry


def _make_device():
    device = MagicMock()
    device.lock = asyncio.Lock()
    device.write_value = MagicMock()
    device.async_execute = AsyncMock()
    return device


def _select_entry(command="0A0900", decode_type="2opmode"):
    return {
        "command": command,
        "type": "select",
        "icon": "mdi:format-list-bulleted",
        "decode_type": decode_type,
    }


def _make_entity(name="pOpMode", entry=None, device=None):
    entity = THZSelect(
        name=name,
        entry=entry if entry is not None else _select_entry(),
        device=device or _make_device(),
        device_id="dev1",
    )
    entity.name = name
    return entity


class TestAsyncSetupEntry:
    """Tests for select.py's async_setup_entry via async_setup_write_platform."""

    @pytest.mark.asyncio
    async def test_creates_select_entities(self):
        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "pOpMode": _select_entry("0A0901"),
            "pNumberOne": {"command": "0A0902", "type": "number"},
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
        assert isinstance(entities[0], THZSelect)
        assert update_before_add is True


class TestTHZSelectInit:
    """Tests for THZSelect initialization."""

    def test_init_with_known_decode_type_sets_options(self):
        entity = _make_entity(entry=_select_entry(decode_type="2opmode"))
        assert entity._attr_options != []
        assert entity.current_option is None

    def test_init_with_unknown_decode_type_empty_options(self):
        entity = _make_entity(entry=_select_entry(decode_type="totallyUnknownType"))
        assert entity._attr_options == []

    def test_init_with_none_decode_type_empty_options(self):
        entry = _select_entry()
        entry["decode_type"] = None
        entity = _make_entity(entry=entry)
        assert entity._attr_options == []


class TestTHZSelectUpdate:
    """Tests for THZSelect.async_update."""

    @pytest.mark.asyncio
    async def test_async_update_success(self):
        entity = _make_entity(entry=_select_entry(decode_type="2opmode"))
        entity.hass = MagicMock()
        # value 11 -> "automatic" in 2opmode map, first byte used
        entity._device.async_execute = AsyncMock(return_value=bytes([11, 0]))

        await entity.async_update()

        assert entity.current_option == "automatic"

    @pytest.mark.asyncio
    async def test_async_update_no_data_keeps_previous(self):
        entity = _make_entity(entry=_select_entry(decode_type="2opmode"))
        entity._attr_current_option = "standby"
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=b"")

        await entity.async_update()

        assert entity.current_option == "standby"

    @pytest.mark.asyncio
    async def test_async_update_unmapped_value_logs_warning(self):
        entity = _make_entity(entry=_select_entry(decode_type="2opmode"))
        entity._attr_current_option = "standby"
        entity.hass = MagicMock()
        # 250 is not a mapped 2opmode value
        entity._device.async_execute = AsyncMock(return_value=bytes([250, 0]))

        await entity.async_update()

        # decode_select returns None, so current_option is left unchanged
        assert entity.current_option == "standby"

    @pytest.mark.asyncio
    async def test_async_update_decode_error_keeps_previous(self, monkeypatch):
        entity = _make_entity(entry=_select_entry(decode_type="2opmode"))
        entity._attr_current_option = "standby"
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=bytes([1, 0]))

        from custom_components.thz import select as select_mod

        def _raise(*_args, **_kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(select_mod.THZValueCodec, "decode_select", _raise)

        await entity.async_update()

        assert entity.current_option == "standby"


class TestTHZSelectSelectOption:
    """Tests for THZSelect.async_select_option."""

    @pytest.mark.asyncio
    async def test_async_select_option_success(self):
        device = _make_device()
        entity = _make_entity(entry=_select_entry(decode_type="2opmode"), device=device)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_select_option("automatic")

        assert entity.current_option == "automatic"
        entity.async_write_ha_state.assert_called_once()
        write_call = device.async_execute.call_args[0]
        assert write_call[1] == device.write_value

    @pytest.mark.asyncio
    async def test_async_select_option_invalid_option_logged(self):
        entity = _make_entity(entry=_select_entry(decode_type="2opmode"))
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Should not raise - encode_select raises ValueError internally, caught.
        await entity.async_select_option("not_a_real_option")

        entity._device.async_execute.assert_not_awaited()
        entity.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_select_option_unknown_decode_type_logged(self):
        entity = _make_entity(entry=_select_entry(decode_type="totallyUnknownType"))
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_select_option("automatic")

        entity._device.async_execute.assert_not_awaited()
        entity.async_write_ha_state.assert_not_called()

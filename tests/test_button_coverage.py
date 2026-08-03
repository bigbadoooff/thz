"""Coverage tests for button.py (THZButton entity and async_setup_entry)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.button import THZButton, async_setup_entry


def _make_device():
    device = MagicMock()
    device.lock = asyncio.Lock()
    device.write_value = MagicMock()
    device.async_execute = AsyncMock()
    return device


def _button_entry(command="D1"):
    return {
        "command": command,
        "type": "button",
        "icon": "mdi:trash-can-outline",
    }


def _make_entity(name="zResetLast10errors", entry=None, device=None):
    entity = THZButton(
        name=name,
        entry=entry if entry is not None else _button_entry(),
        device=device or _make_device(),
        device_id="dev1",
    )
    entity.name = name
    return entity


class TestAsyncSetupEntry:
    """Tests for button.py's async_setup_entry via async_setup_write_platform."""

    @pytest.mark.asyncio
    async def test_creates_button_entities(self):
        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "zResetLast10errors": _button_entry("D1"),
            "pNumberOne": {"command": "0A0802", "type": "number"},
        }

        hass = MagicMock()
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {}
        config_entry.runtime_data = {
            "write_manager": write_manager,
            "device": _make_device(),
            "device_id": "dev1",
        }

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities, update_before_add = async_add_entities.call_args[0]
        assert len(entities) == 1
        assert isinstance(entities[0], THZButton)
        assert update_before_add is True


class TestTHZButtonInit:
    """Tests for THZButton initialization."""

    def test_init_default_icon_without_translation_key(self):
        entry = _button_entry()
        entry["icon"] = None
        entity = _make_entity(name="customUntranslatedButton", entry=entry)
        assert entity._attr_icon == "mdi:gesture-tap-button"

    def test_init_custom_icon_without_translation_key(self):
        entry = _button_entry()
        entry["icon"] = "mdi:trash-can-outline"
        entity = _make_entity(name="customUntranslatedButton", entry=entry)
        assert entity._attr_icon == "mdi:trash-can-outline"

    def test_init_icon_from_translation_key_leaves_no_attr_icon(self):
        # "zResetLast10errors" has a known translation key -> icon comes
        # from icons.json (icon translations) instead of a hardcoded value.
        entity = _make_entity()
        assert not hasattr(entity, "_attr_icon")


class TestTHZButtonLifecycle:
    """Tests for THZButton's overridden lifecycle/no-op methods."""

    @pytest.mark.asyncio
    async def test_async_added_to_hass_is_noop(self):
        entity = _make_entity()
        # Should return without raising, and not touch _unsub_update.
        result = await entity.async_added_to_hass()
        assert result is None
        assert entity._unsub_update is None

    @pytest.mark.asyncio
    async def test_async_update_is_noop(self):
        entity = _make_entity()
        result = await entity.async_update()
        assert result is None


class TestTHZButtonPress:
    """Tests for THZButton.async_press."""

    @pytest.mark.asyncio
    async def test_async_press_success(self):
        device = _make_device()
        entity = _make_entity(device=device)
        entity.hass = MagicMock()

        await entity.async_press()

        write_call = device.async_execute.call_args[0]
        assert write_call[1] == device.write_value
        assert write_call[3] == b"\x00"

    @pytest.mark.asyncio
    async def test_async_press_error_raises_home_assistant_error(self):
        from custom_components.thz.button import HomeAssistantError

        entity = _make_entity()
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(
            side_effect=ConnectionError("device unreachable")
        )

        with pytest.raises(HomeAssistantError):
            await entity.async_press()

    @pytest.mark.asyncio
    async def test_async_press_runtime_error_raises_home_assistant_error(self):
        from custom_components.thz.button import HomeAssistantError

        entity = _make_entity()
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        with pytest.raises(HomeAssistantError):
            await entity.async_press()

    @pytest.mark.asyncio
    async def test_async_press_os_error_raises_home_assistant_error(self):
        from custom_components.thz.button import HomeAssistantError

        entity = _make_entity()
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(side_effect=OSError("boom"))

        with pytest.raises(HomeAssistantError):
            await entity.async_press()

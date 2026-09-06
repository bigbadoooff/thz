"""Tests for async_clear_value() and the ``thz.clear_value`` service that exposes it.

Home Assistant's built-in ``time.set_value`` service cannot represent "no
time" -- its schema requires a real ``datetime.time`` -- so there is no way
to send the device's own "unset" state (sentinel byte 0x80, see
``TIME_VALUE_UNSET`` in const.py) through it. This adds a dedicated entity
service instead, registered via ``entity_platform.async_register_entity_service``
in ``time.py``'s ``async_setup_entry``, targetable at any time entity and
calling ``async_clear_value()`` on it directly.

Follows the same instantiate-the-real-entity-against-a-mock-device/hass
pattern as test_time_set_value.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_hass():
    """Create a mock hass whose async_add_executor_job actually calls through."""
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


class TestClearValueOverridePoint:
    """Both entity classes must expose async_clear_value for the service to target."""

    def test_thz_time_defines_async_clear_value(self):
        from custom_components.thz.time import THZTime
        assert "async_clear_value" in vars(THZTime)

    def test_thz_schedule_time_defines_async_clear_value(self):
        from custom_components.thz.time import THZScheduleTime
        assert "async_clear_value" in vars(THZScheduleTime)


class TestThzTimeClearValue:
    """Tests for THZTime.async_clear_value()."""

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
    async def test_clear_value_writes_sentinel_byte(self):
        """Clearing writes the 0x80 sentinel, not a real quarters count."""
        device = _make_device()
        device.write_value = MagicMock()
        entity = self._make_entity(device)

        await entity.async_clear_value()

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0005"), bytes([0x80, 0])
        )

    @pytest.mark.asyncio
    async def test_clear_value_sets_native_value_none(self):
        """After clearing, native_value should read back as unset (None)."""
        device = _make_device()
        device.write_value = MagicMock()
        entity = self._make_entity(device)
        entity._attr_native_value = __import__("datetime").time(9, 0)

        await entity.async_clear_value()

        assert entity.native_value is None
        entity.async_write_ha_state.assert_called_once()


class TestThzScheduleTimeClearValue:
    """Tests for THZScheduleTime.async_clear_value() (start and end)."""

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
    async def test_clear_start_only_touches_first_byte(self):
        """Clearing the start time must preserve the existing end byte."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "start")

        await entity.async_clear_value()

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0100"), bytes([0x80, 20, 0, 0])
        )

    @pytest.mark.asyncio
    async def test_clear_end_only_touches_second_byte(self):
        """Clearing the end time must preserve the existing start byte."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "end")

        await entity.async_clear_value()

        device.write_value.assert_called_once_with(
            bytes.fromhex("0B0100"), bytes([10, 0x80, 0, 0])
        )

    @pytest.mark.asyncio
    async def test_clear_value_sets_native_value_none(self):
        """The schedule entity should also read back as unset after clearing."""
        device = _make_device(read_return=bytes([10, 20, 0, 0]))
        device.write_value = MagicMock()
        entity = self._make_entity(device, "start")

        await entity.async_clear_value()

        assert entity.native_value is None
        entity.async_write_ha_state.assert_called_once()


class TestClearValueServiceRegistration:
    """async_setup_entry must register the thz.clear_value entity service."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_registers_clear_value_service(self):
        from custom_components.thz.time import async_setup_entry
        from homeassistant.helpers import entity_platform as ep_mock

        platform_mock = MagicMock()
        ep_mock.async_get_current_platform = MagicMock(return_value=platform_mock)

        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "testTimeEntry": {"command": "0B0005", "type": "time"},
        }
        device = MagicMock()
        hass = MagicMock()
        entry_id = "test_entry"
        config_entry = MagicMock()
        config_entry.entry_id = entry_id
        config_entry.data = {}
        config_entry.runtime_data = {
            "write_manager": write_manager,
            "device": device,
            "device_id": "dev1",
            "entity_id_style": "default",
            "entity_visibility": "default",
            "entity_id_prefix": None,
        }
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        platform_mock.async_register_entity_service.assert_called_once_with(
            "clear_value", {}, "async_clear_value"
        )
        async_add_entities.assert_called_once()

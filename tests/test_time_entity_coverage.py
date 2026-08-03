"""Coverage tests for time.py entity classes (THZTime, THZScheduleTime).

These tests exercise async_setup_entry, the _create_time_entities factory,
and the read/write paths of both time entity classes, which are not covered
by the pure-function tests in test_time_conversion.py / test_time_extended.py.
"""
import asyncio
from datetime import time as dtime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.time import (
    THZScheduleTime,
    THZTime,
    _create_time_entities,
    async_setup_entry,
)


def _make_device():
    """Create a mock THZDevice with a real asyncio.Lock."""
    device = MagicMock()
    device.lock = asyncio.Lock()
    device.async_execute = AsyncMock()
    return device


def _make_hass():
    """Create a plain mock hass (device.async_execute carries the I/O mock now)."""
    return MagicMock()


def _time_entry(command="0A0600"):
    return {"command": command, "type": "time", "icon": "mdi:clock"}


def _schedule_entry(command="0A0500"):
    return {"command": command, "type": "schedule", "icon": "mdi:calendar-clock"}


class TestCreateTimeEntitiesFactory:
    """Tests for the _create_time_entities factory function."""

    def test_schedule_type_creates_two_entities(self):
        device = _make_device()
        entry = _schedule_entry()
        result = _create_time_entities(
            "programHC1_Mo_0", entry, device, "dev1", 600
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(e, THZScheduleTime) for e in result)
        assert result[0]._time_type == "start"
        assert result[1]._time_type == "end"

    def test_plain_time_type_creates_single_entity(self):
        device = _make_device()
        entry = _time_entry()
        result = _create_time_entities(
            "pHolidayBeginTime", entry, device, "dev1", 600
        )
        assert isinstance(result, THZTime)


class TestAsyncSetupEntry:
    """Tests for time.py's async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_time_and_schedule_entities(self):
        device = _make_device()
        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "pHolidayBeginTime": _time_entry("0A0601"),
            "programHC1_Mo_0": _schedule_entry("0A0501"),
            "p01RoomTempDayHC1": {"command": "0A0701", "type": "number"},
        }

        hass = MagicMock()
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {}
        config_entry.runtime_data = {
            "write_manager": write_manager,
            "device": device,
            "device_id": "dev1",
        }

        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities, update_before_add = async_add_entities.call_args[0]
        # 1 plain time entity + 2 schedule entities (start/end) = 3
        assert len(entities) == 3
        assert update_before_add is True
        types = sorted(type(e).__name__ for e in entities)
        assert types == ["THZScheduleTime", "THZScheduleTime", "THZTime"]

    @pytest.mark.asyncio
    async def test_no_matching_entries_creates_nothing(self):
        device = _make_device()
        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "p01RoomTempDayHC1": {"command": "0A0701", "type": "number"},
        }

        hass = MagicMock()
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {"write_interval": 300}
        config_entry.runtime_data = {
            "write_manager": write_manager,
            "device": device,
            "device_id": "dev1",
        }

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        assert entities == []


class TestTHZTime:
    """Tests for the THZTime entity class."""

    def test_init_defaults(self):
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry={"command": "0A0601", "type": "time"},
            device=device,
            device_id="dev1",
        )
        assert entity._attr_has_entity_name is True
        assert entity.native_value is None
        assert entity._command == "0A0601"

    def test_init_icon_from_translation_key_leaves_no_attr_icon(self):
        # Names with a known translation key rely on icons.json (icon
        # translations) instead of a hardcoded _attr_icon.
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry={"command": "0A0601", "type": "time", "icon": "mdi:custom"},
            device=device,
            device_id="dev1",
        )
        assert not hasattr(entity, "_attr_icon")

    def test_init_custom_icon_without_translation_key(self):
        device = _make_device()
        entity = THZTime(
            name="customUntranslatedTime",
            entry={"command": "0A0601", "type": "time", "icon": "mdi:custom"},
            device=device,
            device_id="dev1",
        )
        assert entity._attr_icon == "mdi:custom"

    @pytest.mark.asyncio
    async def test_async_update_success(self):
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=_time_entry(),
            device=device,
            device_id="dev1",
        )
        entity.name = "pHolidayBeginTime"
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=b"\x06\x00")

        await entity.async_update()

        assert entity.native_value == dtime(1, 30)  # 6 quarters = 1:30

    @pytest.mark.asyncio
    async def test_async_update_no_data_keeps_previous(self):
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=_time_entry(),
            device=device,
            device_id="dev1",
        )
        entity.name = "pHolidayBeginTime"
        entity._attr_native_value = dtime(5, 0)
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=b"")

        await entity.async_update()

        assert entity.native_value == dtime(5, 0)

    @pytest.mark.asyncio
    async def test_becomes_unavailable_on_connection_error(self):
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=_time_entry(),
            device=device,
            device_id="dev1",
        )
        entity.name = "pHolidayBeginTime"
        entity.hass = _make_hass()
        assert entity.available is True
        device.async_execute = AsyncMock(side_effect=ConnectionError("lost"))

        await entity.async_update()

        assert entity.available is False

    @pytest.mark.asyncio
    async def test_becomes_available_again_after_recovery(self):
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=_time_entry(),
            device=device,
            device_id="dev1",
        )
        entity.name = "pHolidayBeginTime"
        entity._attr_available = False
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=b"\x06\x00")

        await entity.async_update()

        assert entity.available is True
        assert entity.native_value == dtime(1, 30)

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        device = _make_device()
        device.write_value = MagicMock()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=_time_entry(),
            device=device,
            device_id="dev1",
        )
        entity.name = "pHolidayBeginTime"
        entity.hass = _make_hass()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value("12:30")

        assert entity.native_value == dtime(12, 30)
        entity.async_write_ha_state.assert_called_once()
        # 12*4 + 30//15 = 50
        device.async_execute.assert_awaited()
        call_args = device.async_execute.call_args[0]
        assert call_args[1] == device.write_value
        assert call_args[3] == bytes([50, 0])

    @pytest.mark.asyncio
    async def test_async_set_native_value_none(self):
        device = _make_device()
        device.write_value = MagicMock()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=_time_entry(),
            device=device,
            device_id="dev1",
        )
        entity.name = "pHolidayBeginTime"
        entity.hass = _make_hass()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(None)

        assert entity.native_value is None
        call_args = device.async_execute.call_args[0]
        assert call_args[3] == bytes([0x80, 0])


class TestTHZScheduleTime:
    """Tests for the THZScheduleTime entity class."""

    def test_init_start(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        assert entity._time_type == "start"
        # base_name has a known translation key -> icon comes from icons.json
        assert not hasattr(entity, "_attr_icon")
        assert entity._attr_unique_id.endswith("_start")

    def test_init_end_custom_icon_without_translation_key(self):
        device = _make_device()
        entry = _schedule_entry()
        entry["icon"] = "mdi:custom-clock"
        entity = THZScheduleTime(
            name="totallyUnknownSchedule_Mo_0 End",
            base_name="totallyUnknownSchedule_Mo_0",
            entry=entry,
            device=device,
            device_id="dev1",
            time_type="end",
        )
        assert entity._attr_icon == "mdi:custom-clock"
        assert entity._attr_unique_id.endswith("_end")

    def test_init_translation_key_none_for_unmapped_base_name(self):
        """When base_name has no known translation key, translation_key is None."""
        device = _make_device()
        entity = THZScheduleTime(
            name="totallyUnknownSchedule_Mo_0 Start",
            base_name="totallyUnknownSchedule_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        # Falls back to _attr_name since translation_key is None
        assert getattr(entity, "_attr_translation_key", None) is None
        assert entity._attr_name == "totallyUnknownSchedule_Mo_0 Start"

    @pytest.mark.asyncio
    async def test_async_update_start(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        # value_bytes[0] = start (8 quarters = 02:00), value_bytes[1] = end
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=bytes([8, 16]))

        await entity.async_update()

        assert entity.native_value == dtime(2, 0)

    @pytest.mark.asyncio
    async def test_async_update_end(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 End",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="end",
        )
        entity.name = "programHC1_Mo_0 End"
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=bytes([8, 16]))

        await entity.async_update()

        assert entity.native_value == dtime(4, 0)  # 16 quarters = 4:00

    @pytest.mark.asyncio
    async def test_async_update_no_data(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        entity._attr_native_value = dtime(9, 0)
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=b"")

        await entity.async_update()

        assert entity.native_value == dtime(9, 0)

    @pytest.mark.asyncio
    async def test_async_update_short_data(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        entity._attr_native_value = dtime(9, 0)
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=bytes([8]))  # len < 2

        await entity.async_update()

        assert entity.native_value == dtime(9, 0)

    @pytest.mark.asyncio
    async def test_becomes_unavailable_on_connection_error(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        entity.hass = _make_hass()
        assert entity.available is True
        device.async_execute = AsyncMock(side_effect=RuntimeError("comm error"))

        await entity.async_update()

        assert entity.available is False

    @pytest.mark.asyncio
    async def test_becomes_available_again_after_recovery(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        entity._attr_available = False
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=bytes([8, 16]))

        await entity.async_update()

        assert entity.available is True
        assert entity.native_value == dtime(2, 0)

    @pytest.mark.asyncio
    async def test_async_set_native_value_start(self):
        device = _make_device()
        device.write_value = MagicMock()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=bytes([0, 0]))
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value("08:15")

        assert entity.native_value == dtime(8, 15)
        entity.async_write_ha_state.assert_called_once()
        # write_value call is the second async_execute call
        write_call = device.async_execute.call_args_list[-1]
        written_bytes = write_call[0][3]
        assert written_bytes[0] == 8 * 4 + 1  # 8:15 -> 33 quarters

    @pytest.mark.asyncio
    async def test_async_set_native_value_end_midnight_is_end_of_day(self):
        device = _make_device()
        device.write_value = MagicMock()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 End",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="end",
        )
        entity.name = "programHC1_Mo_0 End"
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=bytes([0, 0]))
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value("00:00")

        assert entity.native_value == dtime(0, 0)
        write_call = device.async_execute.call_args_list[-1]
        written_bytes = write_call[0][3]
        assert written_bytes[1] == 96  # end-of-day sentinel

    @pytest.mark.asyncio
    async def test_async_set_native_value_none(self):
        device = _make_device()
        device.write_value = MagicMock()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        entity.hass = _make_hass()
        device.async_execute = AsyncMock(return_value=bytes([5, 5]))
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(None)

        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_async_set_native_value_invalid_format_raises(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"

        with pytest.raises(ValueError):
            await entity.async_set_native_value("1230")

    @pytest.mark.asyncio
    async def test_async_set_native_value_out_of_range_raises(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"

        with pytest.raises(ValueError):
            await entity.async_set_native_value("25:00")

    @pytest.mark.asyncio
    async def test_async_set_native_value_non_string_raises_attribute_error(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=_schedule_entry(),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"

        with pytest.raises(AttributeError):
            await entity.async_set_native_value(1230)

"""Tests for time.py entity classes (THZTime, THZScheduleTime).

These tests exercise async_setup_entry, the _create_time_entities factory,
and the read/write paths of both time entity classes, which are not covered
by the pure-function tests in test_conversion.py and
test_conversion_edge_cases.py.
"""

import asyncio
from datetime import time as dtime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.exceptions import THZProtocolError
from custom_components.thz.time import (
    THZScheduleTime,
    THZTime,
    _create_time_entities,
    async_setup_entry,
)
from tests.helpers import (
    FakeWriteManager,
    RegisterDevice,
    make_runtime_data,
    write_param,
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
            "programHC1_Mo_0", write_param(entry), device, "dev1"
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
            "pHolidayBeginTime", write_param(entry), device, "dev1"
        )
        assert len(result) == 1
        assert isinstance(result[0], THZTime)


class TestAsyncSetupEntry:
    """Tests for time.py's async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_time_and_schedule_entities(self):
        device = _make_device()
        write_manager = FakeWriteManager(
            {
                "pHolidayBeginTime": _time_entry("0A0601"),
                "programHC1_Mo_0": _schedule_entry("0A0501"),
                "p01RoomTempDayHC1": {"command": "0A0701", "type": "number"},
            }
        )
        hass = MagicMock()
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {}
        config_entry.runtime_data = make_runtime_data(
            **{
                "write_manager": write_manager,
                "device": device,
                "device_id": "dev1",
            }
        )

        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        (entities,) = async_add_entities.call_args[0]
        # 1 plain time entity + 2 schedule entities (start/end) = 3
        assert len(entities) == 3
        assert all(e._poller is config_entry.runtime_data.poller for e in entities)
        types = sorted(type(e).__name__ for e in entities)
        assert types == ["THZScheduleTime", "THZScheduleTime", "THZTime"]

    @pytest.mark.asyncio
    async def test_no_matching_entries_creates_nothing(self):
        device = _make_device()
        write_manager = FakeWriteManager(
            {
                "p01RoomTempDayHC1": {"command": "0A0701", "type": "number"},
            }
        )
        hass = MagicMock()
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {"write_interval": 300}
        config_entry.runtime_data = make_runtime_data(
            **{
                "write_manager": write_manager,
                "device": device,
                "device_id": "dev1",
            }
        )

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)

        (entities,) = async_add_entities.call_args[0]
        assert entities == []


class TestTHZTime:
    """Tests for the THZTime entity class."""

    def test_init_defaults(self):
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=write_param({"command": "0A0601", "type": "time"}),
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
            entry=write_param(
                {"command": "0A0601", "type": "time", "icon": "mdi:custom"}
            ),
            device=device,
            device_id="dev1",
        )
        assert not hasattr(entity, "_attr_icon")

    def test_init_custom_icon_without_translation_key(self):
        device = _make_device()
        entity = THZTime(
            name="customUntranslatedTime",
            entry=write_param(
                {"command": "0A0601", "type": "time", "icon": "mdi:custom"}
            ),
            device=device,
            device_id="dev1",
        )
        assert entity._attr_icon == "mdi:custom"

    def test_value_too_short_for_the_second_byte_is_ignored(self):
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=write_param(
                {"command": "0A0601", "type": "time"}, decode_type="9holy"
            ),
            device=_make_device(),
            device_id="dev1",
        )
        entity._apply_value(b"\x10")
        assert entity.native_value is None
        entity._apply_value(b"\x80\x10")
        assert entity.native_value == dtime(4, 0)

    @pytest.mark.asyncio
    async def test_async_update_success(self):
        device = _make_device()
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=write_param(_time_entry()),
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
            entry=write_param(_time_entry()),
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
            entry=write_param(_time_entry()),
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
            entry=write_param(_time_entry()),
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


class TestTHZScheduleTime:
    """Tests for the THZScheduleTime entity class."""

    def test_init_start(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=write_param(_schedule_entry()),
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
            entry=write_param(entry),
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
            entry=write_param(_schedule_entry()),
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
            entry=write_param(_schedule_entry()),
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
            entry=write_param(_schedule_entry()),
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
            entry=write_param(_schedule_entry()),
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
            entry=write_param(_schedule_entry()),
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
            entry=write_param(_schedule_entry()),
            device=device,
            device_id="dev1",
            time_type="start",
        )
        entity.name = "programHC1_Mo_0 Start"
        entity.hass = _make_hass()
        assert entity.available is True
        device.async_execute = AsyncMock(side_effect=THZProtocolError("comm error"))

        await entity.async_update()

        assert entity.available is False

    @pytest.mark.asyncio
    async def test_becomes_available_again_after_recovery(self):
        device = _make_device()
        entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=write_param(_schedule_entry()),
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


class TestHolidayAndPartyTimeByte:
    """FHEM keeps 9holy / 8party start times in the second data byte."""

    @staticmethod
    def _entity(decode_type, read_bytes):
        from unittest.mock import MagicMock

        from custom_components.thz.time import THZTime

        device = RegisterDevice(read_bytes)
        entity = THZTime(
            name="pHolidayBeginTime",
            entry=write_param({"command": "0A05D3", "decode_type": decode_type}),
            device=device,
            device_id="dev",
        )
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity, device

    @pytest.mark.asyncio
    async def test_holiday_time_read_from_second_byte(self):
        from datetime import time

        entity, _ = self._entity("9holy", bytes([0x00, 0x1E]))
        await entity.async_update()
        assert entity.native_value == time(7, 30)

    @pytest.mark.asyncio
    async def test_party_start_write_keeps_the_end_byte(self):
        from datetime import time

        entity, device = self._entity("8party", bytes([0x50, 0x10]))
        await entity.async_set_value(time(7, 30))
        written = device.writes[-1][1]
        assert written == bytes([0x50, 0x1E])


class TestPartyStartAndEnd:
    """The party register holds start (second byte) and end (first byte)."""

    @staticmethod
    def _pair(read_bytes):
        device = RegisterDevice(read_bytes)
        entry = write_param(
            {"command": "0A05D1", "type": "time", "decode_type": "8party"}
        )
        start, end = _create_time_entities("party-time", entry, device, "dev1")
        for entity in (start, end):
            entity.hass = MagicMock()
            entity.async_write_ha_state = MagicMock()
        return start, end, device

    def test_two_entities_the_start_keeps_its_identity(self):
        start, end, _ = self._pair(b"")
        assert start._attr_unique_id == "thz_dev1_set_0a05d1_party-time"
        assert start._attr_translation_key == "party_time"
        assert end._attr_unique_id == "thz_dev1_set_0a05d1_party-time_end"
        assert end._attr_translation_key == "party_time_end"

    @pytest.mark.asyncio
    async def test_each_reads_its_own_byte(self):
        start, end, _ = self._pair(bytes([0x5A, 0x1C]))
        await start.async_update()
        await end.async_update()
        assert (start.native_value, end.native_value) == (dtime(7, 0), dtime(22, 30))

    @pytest.mark.asyncio
    async def test_end_write_keeps_the_start_and_writes_midnight_as_24h(self):
        _, end, device = self._pair(bytes([0x5A, 0x1C]))
        await end.async_set_value(dtime(0, 0))
        written = device.writes[-1][1]
        assert written == bytes([96, 0x1C])
        assert end.native_value == dtime(0, 0)

    @pytest.mark.asyncio
    async def test_short_answer_writes_nothing(self):
        from homeassistant.exceptions import HomeAssistantError

        start, _, device = self._pair(b"")
        with pytest.raises(HomeAssistantError):
            await start.async_set_value(dtime(7, 30))
        assert device.writes == []

    @pytest.mark.asyncio
    async def test_clearing_the_end_keeps_the_start(self):
        _, end, device = self._pair(bytes([0x5A, 0x1C]))
        await end.async_clear_value()
        written = device.writes[-1][1]
        assert written == bytes([0x80, 0x1C])

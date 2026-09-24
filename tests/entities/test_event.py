"""Tests for event.py (new fault and filter change events)."""

from unittest.mock import MagicMock

import pytest

from custom_components.thz.event import (
    THZFaultEvent,
    THZFilterEvent,
    async_setup_entry,
)
from tests.helpers import FakeRegisterManager, make_runtime_data


def _record(number, hhmm, ddmm):
    t = int(hhmm.replace(":", ""))
    d = int(ddmm.replace(".", ""))
    return bytes([number, 0]) + t.to_bytes(2, "little") + d.to_bytes(2, "little")


def _d1(*records):
    return bytes([0x00, 0xD1, len(records), 0x00]) + b"".join(records)


R3 = _record(3, "08:15", "05.01")
R5 = _record(5, "23:59", "31.12")

D1_MAP = [("fault0CODE:", 8, 2, "faultmap", 1, {})]
FILTER_MAP = [
    ("filterBoth:", 9, 1, "bit0", 1, {}),
    ("filterUp:", 8, 1, "bit0", 1, {}),
    ("filterDown:", 8, 1, "bit1", 1, {}),
]


def _coordinator(data=None):
    coordinator = MagicMock()
    coordinator.data = data
    return coordinator


async def _added(entity):
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    await entity.async_added_to_hass()
    return entity


def _update(entity, data):
    entity.coordinator.data = data
    entity._handle_coordinator_update()
    return entity.__dict__.get("triggered", [])


class TestSetup:
    @staticmethod
    def _config_entry(coordinators, blocks):
        config_entry = MagicMock()
        config_entry.data = {}
        config_entry.runtime_data = make_runtime_data(
            register_manager=FakeRegisterManager(blocks),
            coordinators=coordinators,
            device_id="dev1",
        )
        return config_entry

    @pytest.mark.asyncio
    async def test_creates_both_events(self):
        add = MagicMock()
        config_entry = self._config_entry(
            {"pxxD1": _coordinator(), "pxx0A0176": _coordinator()},
            {"pxxD1": D1_MAP, "pxx0A0176": FILTER_MAP},
        )
        await async_setup_entry(MagicMock(), config_entry, add)
        (entities,) = add.call_args[0]
        assert [type(e) for e in entities] == [THZFaultEvent, THZFilterEvent]
        assert entities[0]._attr_unique_id == "thz_dev1_new_fault"
        assert entities[1]._attr_event_types == [
            "filter_both",
            "filter_up",
            "filter_down",
        ]

    @pytest.mark.asyncio
    async def test_no_events_without_polled_blocks(self):
        add = MagicMock()
        config_entry = self._config_entry(
            {}, {"pxxD1": D1_MAP, "pxx0A0176": FILTER_MAP}
        )
        await async_setup_entry(MagicMock(), config_entry, add)
        add.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_no_fault_event_for_the_2xx_layout(self):
        add = MagicMock()
        config_entry = self._config_entry(
            {"pxxD1": _coordinator()},
            {"pxxD1": [("fault0CODE:", 4, 4, "faultmap", 1, {})]},
        )
        await async_setup_entry(MagicMock(), config_entry, add)
        add.assert_called_once_with([])


class TestFaultEvent:
    @pytest.mark.asyncio
    async def test_history_at_start_fires_nothing(self):
        event = await _added(THZFaultEvent(_coordinator(_d1(R3)), "dev1"))
        assert _update(event, _d1(R3)) == []
        event.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_record_fires_with_its_details(self):
        event = await _added(THZFaultEvent(_coordinator(_d1(R3)), "dev1"))
        assert _update(event, _d1(R3, R5)) == [
            (
                "fault",
                {
                    "fault_number": 5,
                    "fault_code": "F05",
                    "description": event_description(5),
                    "time": "23:59",
                    "date": "31.12",
                },
            )
        ]
        # The same data again fires nothing.
        assert len(_update(event, _d1(R3, R5))) == 1

    @pytest.mark.asyncio
    async def test_first_data_after_start_is_the_baseline(self):
        event = await _added(THZFaultEvent(_coordinator(None), "dev1"))
        assert _update(event, _d1(R3)) == []
        assert len(_update(event, _d1(R3, R5))) == 1

    @pytest.mark.asyncio
    async def test_invalid_data_is_ignored(self):
        event = await _added(THZFaultEvent(_coordinator(_d1(R3)), "dev1"))
        assert _update(event, b"\x00\x01") == []
        assert _update(event, _d1(R3)) == []

    def test_device_info(self):
        from custom_components.thz.const import DOMAIN

        event = THZFaultEvent(_coordinator(), "dev1")
        assert (DOMAIN, "dev1") in event.device_info["identifiers"]


def event_description(number):
    from custom_components.thz.fault_memory import fault_description

    return fault_description(number)


def _flags(up=False, down=False, both=False):
    """Byte 4 of the block: filterUp/-Down in the high nibble, filterBoth low."""
    data = bytearray(12)
    data[4] = (up << 4) | (down << 5) | both
    return bytes(data)


class TestFilterEvent:
    @staticmethod
    def _event(data):
        manager = FakeRegisterManager({"pxx0A0176": FILTER_MAP})
        filters = {
            "filter_both": manager.find_field("pxx0A0176", "filterBoth"),
            "filter_up": manager.find_field("pxx0A0176", "filterUp"),
            "filter_down": manager.find_field("pxx0A0176", "filterDown"),
        }
        return THZFilterEvent(_coordinator(data), "dev1", filters)

    @pytest.mark.asyncio
    async def test_a_filter_that_becomes_due_fires_once(self):
        event = await _added(self._event(_flags()))
        assert _update(event, _flags(down=True)) == [("filter_down", None)]
        assert _update(event, _flags(down=True)) == [("filter_down", None)]

    @pytest.mark.asyncio
    async def test_due_at_start_fires_nothing_until_due_again(self):
        event = await _added(self._event(_flags(both=True)))
        assert _update(event, _flags(both=True)) == []
        _update(event, _flags())
        assert _update(event, _flags(both=True)) == [("filter_both", None)]

    @pytest.mark.asyncio
    async def test_short_or_missing_data_is_ignored(self):
        event = await _added(self._event(None))
        assert _update(event, bytes(4)) == []
        assert _update(event, _flags(up=True)) == []  # baseline
        assert _update(event, _flags(up=True, down=True)) == [("filter_down", None)]

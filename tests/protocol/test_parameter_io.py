"""Tests for parameter_io: one read/write path honouring write_mode="block".

Uses the real firmware 206 write map and a simulated 2xx device that keeps
its register blocks in memory and speaks the real telegram format, so the
tests cover the whole path from write-map entry to bytes on the wire.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.thz.climate import THZClimate
from custom_components.thz.clock_sync import (
    async_read_device_clock,
    async_write_device_clock,
)
from custom_components.thz.parameter_io import (
    async_read_parameter,
    async_write_parameter,
    is_block_parameter,
    parameter_length,
)
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManagerWrite,
)
from custom_components.thz.value_codec import THZValueCodec
from tests.helpers import Simulated2xxDevice, make_climate, write_param


@pytest.fixture
def write_map_206():
    return RegisterMapManagerWrite("206").params()


def _block_17() -> bytes:
    # p01 room day 21.0, p02 room night 18.0, p03 standby 15.0, then filler.
    return bytes.fromhex("00D200B40096") + bytes(range(1, 30))


class TestHelpers:
    def test_direct_entry_defaults(self):
        entry = write_param({"command": "0A0005", "type": "number"})
        assert not is_block_parameter(entry)
        assert parameter_length(entry) == 2

    def test_parameter_from_block_needs_a_block_parameter(self, write_map_206):
        from custom_components.thz.parameter_io import parameter_from_block

        direct = write_param({"command": "0A0005"})
        assert parameter_from_block(direct, bytes(40)) is None
        # A block response too short to hold the parameter.
        assert parameter_from_block(write_map_206["p02RoomTempNight"], b"\x00") is None

    def test_block_entry_uses_map_length(self, write_map_206):
        entry = write_map_206["p07FanStageDay"]
        assert is_block_parameter(entry)
        assert parameter_length(entry) == entry.block.length == 1

    @pytest.mark.asyncio
    async def test_direct_write_uses_plain_set(self):
        device = MagicMock()
        device.async_execute = AsyncMock()
        await async_write_parameter(
            None, device, write_param({"command": "0A0005"}), b"\x00\x01"
        )
        device.async_execute.assert_awaited_once_with(
            device.write_value, bytes.fromhex("0A0005"), b"\x00\x01"
        )

    @pytest.mark.asyncio
    async def test_block_write_uses_read_modify_write(self, write_map_206):
        device = MagicMock()
        device.async_execute = AsyncMock()
        entry = write_map_206["p02RoomTempNight"]
        await async_write_parameter(None, device, entry, b"\x00\xaa")
        device.async_execute.assert_awaited_once_with(
            device.write_block_value,
            b"\x17",
            entry.block.offset,
            entry.block.length,
            b"\x00\xaa",
        )


class TestSimulated2xxDevice:
    @pytest.mark.asyncio
    async def test_read_returns_the_parameter_not_the_block_start(self, write_map_206):
        device = Simulated2xxDevice({b"\x17": _block_17()})
        day = await async_read_parameter(None, device, write_map_206["p01RoomTempDay"])
        night = await async_read_parameter(
            None, device, write_map_206["p02RoomTempNight"]
        )
        assert day == bytes.fromhex("00D2")
        assert night == bytes.fromhex("00B4")

    @pytest.mark.asyncio
    async def test_write_changes_only_the_target_parameter(self, write_map_206):
        before = _block_17()
        device = Simulated2xxDevice({b"\x17": before})
        entry = write_map_206["p02RoomTempNight"]
        value = THZValueCodec.encode_number(
            18.5, float(entry.step), entry.decode_type, parameter_length(entry)
        )

        await async_write_parameter(None, device, entry, value)

        after = device.blocks[b"\x17"]
        assert after[2:4] == bytes.fromhex("00B9")
        assert after[:2] == before[:2]
        assert after[4:] == before[4:]

    @pytest.mark.asyncio
    async def test_every_206_number_round_trips(self, write_map_206):
        """Each block parameter writes into its own slot and reads back."""
        numbers = {
            name: e
            for name, e in write_map_206.items()
            if e.type == "number" and is_block_parameter(e)
        }
        assert numbers
        blocks = {bytes.fromhex(e.command): bytes(64) for e in numbers.values()}
        device = Simulated2xxDevice(blocks)
        for entry in numbers.values():
            raw = bytes([0x01] * parameter_length(entry))
            await async_write_parameter(None, device, entry, raw)
            assert await async_read_parameter(None, device, entry) == raw


class TestClockSyncOn2xx:
    @pytest.mark.asyncio
    async def test_clock_round_trips_through_block_fc(self):
        manager = RegisterMapManagerWrite("206")
        # FC block data: weekday, hour, minute, second, year, ?, month, day, ...
        device = Simulated2xxDevice({b"\xfc": bytes(12)})
        when = datetime(2026, 9, 23, 14, 35)

        assert await async_write_device_clock(None, device, manager, when)
        assert await async_read_device_clock(None, device, manager) == when


class TestBitFlagsOn2xx:
    @pytest.mark.asyncio
    async def test_weekday_flag_writes_only_its_own_bit(self, write_map_206):
        tuesday = write_map_206["progHC1Tuesday"]
        monday = write_map_206["progHC1Monday"]
        # Both live in the low nibble of the same byte (nibble 13).
        assert tuesday.block.offset == monday.block.offset
        assert (tuesday.block.bit, monday.block.bit) == (1, 0)

        data = bytearray(16)
        data[tuesday.block.offset - 2] = 0b1111_0001  # Monday on, high nibble set
        device = Simulated2xxDevice({b"\x0b": bytes(data)})

        await async_write_parameter(None, device, tuesday, b"\x01")

        byte = device.blocks[b"\x0b"][tuesday.block.offset - 2]
        assert byte == 0b1111_0011
        assert await async_read_parameter(None, device, tuesday) == b"\x01"
        assert await async_read_parameter(None, device, monday) == b"\x01"

        await async_write_parameter(None, device, monday, b"\x00")
        assert device.blocks[b"\x0b"][tuesday.block.offset - 2] == 0b1111_0010

    def test_high_nibble_flags_are_shifted(self, write_map_206):
        # Friday sits at the even nibble 12, i.e. the byte's high nibble.
        assert write_map_206["progHC1Friday"].block.bit == 4


class TestClimateOn2xx:
    @pytest.mark.asyncio
    async def test_heat_setpoint_is_written_into_its_block_slot(self, write_map_206):
        device = Simulated2xxDevice({b"\x17": _block_17()})
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.async_request_refresh = AsyncMock()
        entity = make_climate(
            coordinator=coordinator,
            cooling_coordinator=None,
            device=device,
            device_id="test_device",
            translation_key="heating_circuit",
            current_temp_offset=0,
            current_temp_length=2,
            target_temp_offset=2,
            target_temp_length=2,
            op_mode_offset=24,
            op_mode_length=1,
            heat_setpoint_entry=write_map_206["p01RoomTempDay"],
            night_setpoint_entry=write_map_206["p02RoomTempNight"],
            cool_switch_entry=None,
            cool_setpoint_entry=None,
        )
        entity.hass = MagicMock()

        # Night setback (18.0) is active, so the night register is written.
        with patch.object(
            THZClimate,
            "target_temperature",
            new_callable=PropertyMock,
            return_value=18.0,
        ):
            await entity._async_write_heat_setpoint(18.5)

        block = device.blocks[b"\x17"]
        assert block[0:2] == bytes.fromhex("00D2")  # day unchanged
        assert block[2:4] == bytes.fromhex("00B9")  # night 18.5
        assert block[4:] == _block_17()[4:]


class TestNumberReadsFromBlockCoordinator:
    """2xx numbers take their value from the block coordinator's data."""

    @staticmethod
    def _number(entry, device, coordinator):
        from custom_components.thz.number import THZNumber

        number = THZNumber("p02RoomTempNight", entry, device, "dev")
        number.hass = MagicMock()
        number.async_write_ha_state = MagicMock()
        number._coordinators = {"pxx17": coordinator} if coordinator else {}
        return number

    @staticmethod
    def _coordinator(data, success=True):
        coordinator = MagicMock()
        coordinator.data = data
        coordinator.last_update_success = success
        coordinator.async_request_refresh = AsyncMock()
        return coordinator

    @pytest.mark.asyncio
    async def test_value_comes_from_coordinator_without_device_read(
        self, write_map_206
    ):
        device = Simulated2xxDevice({b"\x17": _block_17()})
        coordinator = self._coordinator(
            await device.read_write_register(b"\x17", "get")
        )
        device.sent.clear()
        number = self._number(write_map_206["p02RoomTempNight"], device, coordinator)

        number._handle_block_update()

        assert number.native_value == pytest.approx(18.0)
        assert device.sent == []

    @pytest.mark.asyncio
    async def test_update_entity_reads_the_device(self, write_map_206):
        device = Simulated2xxDevice({b"\x17": _block_17()})
        coordinator = self._coordinator(b"stale", success=False)
        number = self._number(write_map_206["p02RoomTempNight"], device, coordinator)

        await number.async_update()

        assert number.native_value == pytest.approx(18.0)
        assert device.sent

    @pytest.mark.asyncio
    async def test_write_refreshes_the_block_coordinator(self, write_map_206):
        device = Simulated2xxDevice({b"\x17": _block_17()})
        coordinator = self._coordinator(
            await device.read_write_register(b"\x17", "get")
        )
        number = self._number(write_map_206["p02RoomTempNight"], device, coordinator)

        await number.async_set_native_value(18.5)

        coordinator.async_request_refresh.assert_awaited_once()
        assert device.blocks[b"\x17"][2:4] == bytes.fromhex("00B9")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", ["p02RoomTempNight", "progHC1Tuesday"])
    async def test_block_slice_equals_device_read(self, write_map_206, name):
        from custom_components.thz.parameter_io import parameter_from_block

        entry = write_map_206[name]
        addr = bytes.fromhex(entry.command)
        device = Simulated2xxDevice({addr: bytes(range(7, 55))})
        response = await device.read_write_register(addr, "get")

        from_block = parameter_from_block(entry, response)
        from_device = await async_read_parameter(None, device, entry)
        assert from_block == from_device


class TestEveryWriteEntityUsesParameterIo:
    """Select, switch, button and time write through parameter_io too.

    None of them sits in a 2.x block today; if one ever does, it must be
    written by read-modify-write of its block instead of a plain SET that
    would overwrite the block's start.
    """

    @staticmethod
    def _block_param(**fields):
        layout = {"write_mode": "block", "offset": 4, "length": 2, "signed": False}
        return write_param({"command": "17", **layout, **fields})

    @staticmethod
    def _prepare(entity):
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_switch_in_a_block_writes_only_its_slot(self):
        from custom_components.thz.switch import THZSwitch

        device = Simulated2xxDevice({b"\x17": _block_17()})
        switch = self._prepare(
            THZSwitch("pSwitchInBlock", self._block_param(type="switch"), device, "d")
        )
        await switch.async_turn_on()

        block = device.blocks[b"\x17"]
        assert block[2:4] == b"\x00\x01"
        assert block[:2] == _block_17()[:2]
        assert block[4:] == _block_17()[4:]
        await switch.async_update()
        assert switch.is_on is True

    @pytest.mark.asyncio
    async def test_select_in_a_block_writes_only_its_slot(self):
        from custom_components.thz.select import THZSelect

        device = Simulated2xxDevice({b"\x17": _block_17()})
        select = self._prepare(
            THZSelect(
                "pSelectInBlock",
                self._block_param(type="select", decode_type="1clean"),
                device,
                "d",
            )
        )
        await select.async_select_option(select._attr_options[1])

        block = device.blocks[b"\x17"]
        assert block[2:4] == b"\x00\x01"
        assert block[4:] == _block_17()[4:]
        await select.async_update()
        assert select.current_option == select._attr_options[1]

    @pytest.mark.asyncio
    async def test_time_in_a_block_writes_only_its_slot(self):
        from datetime import time as dt_time

        from custom_components.thz.time import THZTime

        device = Simulated2xxDevice({b"\x17": _block_17()})
        entity = self._prepare(
            THZTime("pTimeInBlock", self._block_param(type="time"), device, "d")
        )
        await entity.async_set_value(dt_time(1, 0))

        block = device.blocks[b"\x17"]
        assert block[2:4] == b"\x04\x00"  # 1:00 = 4 quarters in the first byte
        assert block[4:] == _block_17()[4:]
        await entity.async_update()
        assert entity.native_value == dt_time(1, 0)

    @pytest.mark.asyncio
    async def test_button_in_a_block_writes_only_its_slot(self):
        from custom_components.thz.button import THZButton

        device = Simulated2xxDevice({b"\x17": _block_17()})
        button = self._prepare(
            THZButton(
                "pButtonInBlock",
                write_param(
                    {"command": "17", "type": "button", "write_mode": "block"},
                    offset=5,
                    length=1,
                ),
                device,
                "d",
            )
        )
        await button.async_press()

        # Offset 5 is data byte 3 (0xB4, the low byte of p02) before the press.
        block = device.blocks[b"\x17"]
        assert block[3] == 0x00
        assert block[:3] == _block_17()[:3]
        assert block[4:] == _block_17()[4:]

"""Tests for water_heater.py (THZWaterHeater and async_setup_entry)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.water_heater import THZWaterHeater, async_setup_entry
from tests.helpers import (
    FakeRegisterManager,
    FakeWriteManager,
    make_runtime_data,
    write_param,
)

_F3_ENTRIES = [
    ("dhwTemp:", 4, 4, "hex2int", 10, {}),
    ("dhwSetTemp:", 12, 4, "hex2int", 10, {}),
    ("dhwOpMode:", 34, 2, "opmodehc", 1, {}),
]
_DAY = {
    "command": "0A0013",
    "min": "10",
    "max": "65",
    "step": "0.1",
    "decode_type": "5temp",
}
_NIGHT = {**_DAY, "command": "0A0014"}


def _block(current=48.5, target=50.0, op_mode=1) -> bytes:
    data = bytearray(20)
    data[2:4] = int(current * 10).to_bytes(2, "big", signed=True)
    data[6:8] = int(target * 10).to_bytes(2, "big", signed=True)
    data[17] = op_mode
    return bytes(data)


def _coordinator(data=None):
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _device():
    device = MagicMock()
    device.async_execute = AsyncMock()
    return device


def _heater(data=None, *, day=_DAY, night=_NIGHT, op_mode=(17, 1), device=None):
    entity = THZWaterHeater(
        _coordinator(data),
        device=device or _device(),
        device_id="dev1",
        current=(2, 2),
        target=(6, 2),
        op_mode=op_mode,
        day_setpoint=write_param(day, name="p04DHWsetDayTemp") if day else None,
        night_setpoint=(
            write_param(night, name="p05DHWsetNightTemp") if night else None
        ),
        entity_id_style="default",
        entity_id_prefix=None,
    )
    entity.hass = MagicMock()
    return entity


def _config_entry(blocks, coordinators, write_registers):
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    config_entry.data = {}
    config_entry.runtime_data = make_runtime_data(
        register_manager=FakeRegisterManager(blocks),
        write_manager=FakeWriteManager(write_registers),
        coordinators=coordinators,
        device_id="dev1",
    )
    return config_entry


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_creates_water_heater(self):
        config_entry = _config_entry(
            {"pxxF3": _F3_ENTRIES},
            {"pxxF3": _coordinator()},
            {"p04DHWsetDayTemp": _DAY, "p05DHWsetNightTemp": _NIGHT},
        )
        add = MagicMock()
        await async_setup_entry(MagicMock(), config_entry, add)
        (entities,) = add.call_args[0]
        assert len(entities) == 1
        heater = entities[0]
        assert isinstance(heater, THZWaterHeater)
        assert heater._day_setpoint.command == "0A0013"
        assert heater._night_setpoint.command == "0A0014"

    @pytest.mark.asyncio
    async def test_no_coordinator_no_entity(self):
        config_entry = _config_entry({"pxxF3": _F3_ENTRIES}, {}, {})
        add = MagicMock()
        await async_setup_entry(MagicMock(), config_entry, add)
        add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_temperature_fields_no_entity(self):
        config_entry = _config_entry(
            {"pxxF3": [_F3_ENTRIES[2]]}, {"pxxF3": _coordinator()}, {}
        )
        add = MagicMock()
        await async_setup_entry(MagicMock(), config_entry, add)
        add.assert_not_called()


class TestState:
    def test_attributes(self):
        from homeassistant.components.water_heater import WaterHeaterEntityFeature

        heater = _heater()
        assert heater._attr_unique_id == "thz_dev1_water_heater_dhw"
        assert heater._attr_supported_features == (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
        )
        assert heater._attr_min_temp == 10.0
        assert heater._attr_max_temp == 65.0

    def test_without_day_setpoint_is_read_only(self):
        heater = _heater(day=None)
        assert not getattr(heater, "_attr_supported_features", 0)
        assert heater._attr_min_temp == 10.0
        assert heater._attr_max_temp == 65.0

    def test_temperatures(self):
        heater = _heater(_block(current=48.5, target=50.0))
        assert heater.current_temperature == pytest.approx(48.5)
        assert heater.target_temperature == pytest.approx(50.0)

    def test_no_data(self):
        heater = _heater(None)
        assert heater.current_temperature is None
        assert heater.target_temperature is None
        assert heater.current_operation == "performance"

    @pytest.mark.parametrize(
        ("op_mode", "expected"),
        [(1, "performance"), (2, "eco"), (3, "off"), (4, "performance")],
    )
    def test_current_operation(self, op_mode, expected):
        assert _heater(_block(op_mode=op_mode)).current_operation == expected

    def test_current_operation_without_op_mode_field(self):
        assert _heater(_block(op_mode=2), op_mode=None).current_operation == (
            "performance"
        )

    def test_current_operation_unreadable(self):
        assert _heater(_block(), op_mode=(40, 1)).current_operation is None

    def test_device_info(self):
        from custom_components.thz.const import DOMAIN

        heater = _heater()
        assert (DOMAIN, "dev1") in heater.device_info["identifiers"]


class TestSetTemperature:
    @pytest.mark.asyncio
    async def test_performance_writes_day_setpoint(self):
        heater = _heater(_block(op_mode=1))
        await heater.async_set_temperature(temperature=52.0)
        device = heater._device
        _, _, command, value = device.async_execute.await_args[0]
        assert command == bytes.fromhex("0A0013")
        assert value == (520).to_bytes(2, "big", signed=True)
        heater.coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_eco_writes_night_setpoint(self):
        heater = _heater(_block(op_mode=2))
        await heater.async_set_temperature(temperature=40.0)
        _, _, command, _ = heater._device.async_execute.await_args[0]
        assert command == bytes.fromhex("0A0014")

    @pytest.mark.asyncio
    async def test_eco_without_night_setpoint_writes_day(self):
        heater = _heater(_block(op_mode=2), night=None)
        await heater.async_set_temperature(temperature=40.0)
        _, _, command, _ = heater._device.async_execute.await_args[0]
        assert command == bytes.fromhex("0A0013")

    @pytest.mark.asyncio
    async def test_no_temperature_is_noop(self):
        heater = _heater(_block())
        await heater.async_set_temperature()
        heater._device.async_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_setpoint_is_noop(self):
        heater = _heater(_block(), day=None, night=None)
        await heater.async_set_temperature(temperature=50.0)
        heater._device.async_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_device_error_is_logged(self):
        device = _device()
        device.async_execute.side_effect = OSError("boom")
        heater = _heater(_block(), device=device)
        await heater.async_set_temperature(temperature=50.0)
        heater.coordinator.async_request_refresh.assert_not_awaited()

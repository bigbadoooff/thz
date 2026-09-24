"""Tests for fan.py (THZFan and async_setup_entry)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz import fan as fan_module
from custom_components.thz.fan import FanParams, THZFan, async_setup_entry
from tests.helpers import (
    FakeRegisterManager,
    FakeWriteManager,
    make_runtime_data,
    write_param,
)

_NUMBER = {"decode_type": "1clean", "step": 1}
START = {**_NUMBER, "command": "0A05DD", "min": "0", "max": "3"}
REGISTERS = {
    "p99startUnschedVent": START,
    "p46UnschedVent0": {**_NUMBER, "command": "0A0571"},
    "p45UnschedVent1": {**_NUMBER, "command": "0A0572"},
    "p44UnschedVent2": {**_NUMBER, "command": "0A0573"},
    "p43UnschedVent3": {**_NUMBER, "command": "0A0574"},
    "p37Fanstage1AirflowInlet": {**_NUMBER, "command": "0A0575"},
    "p38Fanstage2AirflowInlet": {**_NUMBER, "command": "0A0576"},
    "p39Fanstage3AirflowInlet": {**_NUMBER, "command": "0A0577"},
    "p07FanStageDay": {**_NUMBER, "command": "0A056C"},
    "p08FanStageNight": {**_NUMBER, "command": "0A056D"},
    "programFan_Mo_0": {"command": "0A1D10", "decode_type": "7prog"},
    "programFan_Mo_1": {"command": "0A1D11", "decode_type": "7prog"},
}
# A Monday, 08:00.
MONDAY_8 = datetime(2026, 9, 21, 8, 0)
_AIRFLOW = (2, 2)


def _word(value):
    return value.to_bytes(2, "big")


def _window(start_hour, end_hour):
    return bytes([start_hour * 4, end_hour * 4])


class FakeDevice:
    """Answers parameter reads from ``values`` and records writes."""

    def __init__(self, values=None, fail=False):
        # The second program window is unset unless a test sets it.
        self.values = {"0A1D11": bytes([0x80, 0x80]), **(values or {})}
        self.writes = []
        self.fail = fail
        self.async_execute = AsyncMock(side_effect=self._execute)

    def read_value(self):
        """Stand-in; THZFan passes it to async_execute."""

    def write_value(self):
        """Stand-in; THZFan passes it to async_execute."""

    async def _execute(self, hass, func, command, *args):
        if self.fail:
            raise OSError("boom")
        if func == self.write_value:
            self.writes.append((command.hex().upper(), args[0]))
            return None
        return self.values.get(command.hex().upper(), b"")


@pytest.fixture
def now(monkeypatch):
    clock = {"now": MONDAY_8}
    monkeypatch.setattr(fan_module.dt_util, "now", lambda: clock["now"])
    return clock


def _fan(device=None, *, registers=REGISTERS, airflow=_AIRFLOW, e8=None):
    params = {name: write_param(entry, name=name) for name, entry in registers.items()}
    entity = THZFan(
        start=params["p99startUnschedVent"],
        params=FanParams(params),
        airflow=airflow,
        device=device or FakeDevice(),
        device_id="dev1",
    )
    if e8 is not None:
        coordinator = MagicMock()
        coordinator.data = e8
        entity._coordinators = {"pxxE8": coordinator}
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    return entity


def _e8(airflow):
    return bytes(2) + _word(airflow) + bytes(4)


_AIRFLOWS = {"0A0575": _word(90), "0A0576": _word(150), "0A0577": _word(220)}


class TestAsyncSetupEntry:
    @staticmethod
    def _config_entry(registers, blocks=None):
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {}
        config_entry.runtime_data = make_runtime_data(
            write_manager=FakeWriteManager(registers),
            register_manager=FakeRegisterManager(blocks or {}),
            device_id="dev1",
        )
        return config_entry

    @pytest.mark.asyncio
    async def test_creates_fan_with_airflow_field(self):
        add = MagicMock()
        config_entry = self._config_entry(
            REGISTERS,
            {"pxxE8": [("pFanstageXAirflowInlet:", 62, 4, "hex", 1, {})]},
        )
        await async_setup_entry(MagicMock(), config_entry, add)
        entities, update_before_add = add.call_args[0]
        assert update_before_add is True
        assert entities[0]._airflow == (31, 2)
        assert entities[0]._params.day_stage.command == "0A056C"

    @pytest.mark.asyncio
    async def test_creates_fan_without_airflow_field(self):
        add = MagicMock()
        await async_setup_entry(MagicMock(), self._config_entry(REGISTERS), add)
        (entities, _) = add.call_args[0]
        assert entities[0]._airflow is None

    @pytest.mark.asyncio
    async def test_no_start_parameter_no_entity(self):
        add = MagicMock()
        registers = {"p07FanStageDay": REGISTERS["p07FanStageDay"]}
        await async_setup_entry(MagicMock(), self._config_entry(registers), add)
        add.assert_not_called()


class TestState:
    def test_attributes(self):
        from homeassistant.components.fan import FanEntityFeature

        fan = _fan()
        assert fan._attr_unique_id == "thz_dev1_fan_ventilation"
        assert fan._attr_speed_count == 3
        assert fan._attr_supported_features & FanEntityFeature.SET_SPEED
        assert not fan._attr_supported_features & FanEntityFeature.PRESET_MODE

    def test_unknown_before_first_read(self):
        fan = _fan()
        assert fan.is_on is None
        assert fan.percentage is None

    @pytest.mark.parametrize(
        ("airflow", "stage", "percentage"),
        [(0, 0, 0), (90, 1, 33), (150, 2, 66), (220, 3, 100)],
    )
    @pytest.mark.asyncio
    async def test_stage_from_airflow(self, now, airflow, stage, percentage):
        fan = _fan(FakeDevice(_AIRFLOWS), e8=_e8(airflow))
        await fan.async_update()
        assert fan._stage == stage
        assert fan.percentage == percentage
        assert fan.is_on is (stage > 0)

    @pytest.mark.asyncio
    async def test_ambiguous_airflow_falls_back_to_program(self, now):
        values = {
            **_AIRFLOWS,
            "0A0576": _word(90),
            "0A1D10": _window(6, 9),
            "0A056C": _word(2),
        }
        fan = _fan(FakeDevice(values), e8=_e8(90))
        await fan.async_update()
        assert fan._stage == 2

    @pytest.mark.asyncio
    async def test_short_e8_data_falls_back_to_program(self, now):
        values = {"0A1D10": _window(6, 9), "0A056C": _word(2)}
        fan = _fan(FakeDevice(values), e8=bytes(3))
        await fan.async_update()
        assert fan._stage == 2

    @pytest.mark.asyncio
    async def test_inside_program_window_is_day_stage(self, now):
        values = {
            "0A1D10": _window(6, 9),
            "0A1D11": bytes([0x80, 0x80]),
            "0A056C": _word(2),
            "0A056D": _word(1),
        }
        fan = _fan(FakeDevice(values), airflow=None)
        await fan.async_update()
        assert fan._stage == 2

    @pytest.mark.asyncio
    async def test_outside_program_windows_is_night_stage(self, now):
        values = {
            "0A1D10": _window(10, 12),
            "0A1D11": _window(18, 22),
            "0A056C": _word(2),
            "0A056D": _word(1),
        }
        fan = _fan(FakeDevice(values), airflow=None)
        await fan.async_update()
        assert fan._stage == 1

    @pytest.mark.asyncio
    async def test_no_program_for_today_leaves_state(self, now):
        now["now"] = MONDAY_8 + timedelta(days=1)
        fan = _fan(FakeDevice({"0A056C": _word(2)}), airflow=None)
        await fan.async_update()
        assert fan._stage is None

    @pytest.mark.asyncio
    async def test_unreadable_program_leaves_state(self, now):
        fan = _fan(FakeDevice({}), airflow=None)
        await fan.async_update()
        assert fan._stage is None

    @pytest.mark.asyncio
    async def test_device_error_marks_unavailable(self, now):
        fan = _fan(FakeDevice(fail=True), airflow=None)
        await fan.async_update()
        assert fan._stage is None
        assert fan._attr_available is False

    @pytest.mark.asyncio
    async def test_decode_error_leaves_state(self, now, monkeypatch):
        monkeypatch.setattr(
            fan_module.THZValueCodec,
            "decode_number",
            MagicMock(side_effect=ValueError("bad")),
        )
        values = {"0A1D10": _window(6, 9), "0A056C": _word(2)}
        fan = _fan(FakeDevice(values), airflow=None)
        await fan.async_update()
        assert fan._stage is None


class TestWrites:
    @pytest.mark.parametrize(
        ("percentage", "stage"),
        [(0, 0), (1, 1), (33, 1), (34, 2), (66, 2), (67, 3), (100, 3)],
    )
    @pytest.mark.asyncio
    async def test_set_percentage_starts_unscheduled_ventilation(
        self, now, percentage, stage
    ):
        device = FakeDevice()
        fan = _fan(device)
        await fan.async_set_percentage(percentage)
        assert device.writes == [("0A05DD", _word(stage))]
        assert fan._stage == stage
        fan.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_program_settings_are_not_written(self, now):
        device = FakeDevice()
        fan = _fan(device)
        await fan.async_set_percentage(100)
        await fan.async_turn_off()
        await fan.async_turn_on()
        assert {command for command, _ in device.writes} == {"0A05DD"}

    @pytest.mark.asyncio
    async def test_turn_off_starts_stage_zero(self, now):
        device = FakeDevice()
        fan = _fan(device)
        await fan.async_turn_off()
        assert device.writes == [("0A05DD", _word(0))]
        assert fan.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_restores_last_stage(self, now):
        device = FakeDevice()
        fan = _fan(device)
        await fan.async_set_percentage(66)
        await fan.async_turn_off()
        await fan.async_turn_on()
        assert device.writes[-1] == ("0A05DD", _word(2))

    @pytest.mark.asyncio
    async def test_turn_on_default_stage_is_one(self, now):
        device = FakeDevice()
        await _fan(device).async_turn_on()
        assert device.writes == [("0A05DD", _word(1))]

    @pytest.mark.asyncio
    async def test_turn_on_with_percentage(self, now):
        device = FakeDevice()
        await _fan(device).async_turn_on(percentage=100)
        assert device.writes == [("0A05DD", _word(3))]

    @pytest.mark.asyncio
    async def test_write_error_keeps_state(self, now):
        fan = _fan(FakeDevice(fail=True))
        await fan.async_set_percentage(100)
        assert fan._stage is None
        fan.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_unscheduled_stage_shown_until_its_duration_ends(self, now):
        values = {
            "0A0574": _word(30),
            "0A1D10": _window(6, 9),
            "0A056C": _word(1),
        }
        fan = _fan(FakeDevice(values), airflow=None)
        await fan.async_set_percentage(100)

        now["now"] = MONDAY_8 + timedelta(minutes=29)
        await fan.async_update()
        assert fan._stage == 3

        now["now"] = MONDAY_8 + timedelta(minutes=31)
        await fan.async_update()
        assert fan._stage == 1
        assert fan._unscheduled is None

    @pytest.mark.asyncio
    async def test_airflow_wins_over_unscheduled_stage(self, now):
        values = {**_AIRFLOWS, "0A0574": _word(30)}
        fan = _fan(FakeDevice(values), e8=_e8(90))
        await fan.async_set_percentage(100)
        await fan.async_update()
        assert fan._stage == 1

    @pytest.mark.asyncio
    async def test_unknown_duration_is_not_tracked(self, now):
        fan = _fan(FakeDevice())
        await fan.async_set_percentage(100)
        assert fan._unscheduled is None

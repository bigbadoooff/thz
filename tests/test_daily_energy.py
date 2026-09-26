"""Tests for the correction of the daily energy counters at midnight."""

from datetime import datetime, timedelta

import pytest

from custom_components.thz.daily_energy import SAVE_DELAY, DailyEnergyCorrector
from custom_components.thz.register_maps.register_map_manager import RegisterMapManager

BLOCK = "pxx0A091A"
EVENING = datetime(2026, 9, 25, 23, 50)
NIGHT = datetime(2026, 9, 26, 0, 5)
MORNING = datetime(2026, 9, 26, 8, 0)


class FakeStore:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
        self.saves = []

    async def async_load(self):
        if self.error:
            raise self.error
        return self.data

    def async_delay_save(self, data_func, delay=0):
        self.saves.append(delay)
        self.data = data_func()


def _corrector(data=None):
    return DailyEnergyCorrector(FakeStore(data), frozenset({BLOCK}))


def _read(corrector, readings):
    """Feed (low, high, time) readings; return the corrected values."""
    return [corrector.correct(BLOCK, low, high, now) for low, high, now in readings]


class TestKeptWhRegister:
    """The device resets only the kWh register (issue #258)."""

    def test_offset_removes_the_kept_wh_part(self):
        values = _read(
            _corrector(),
            [
                (359, 1, EVENING),
                (359, 0, NIGHT),  # 1359 -> 359 at the reset
                (900, 0, MORNING),
                (100, 1, MORNING),  # Wh register wrapped: 1100 raw
            ],
        )
        assert values == [1359, 0, 541, 741]

    def test_energy_counted_between_reset_and_read_is_kept(self):
        values = _read(_corrector(), [(359, 1, EVENING), (400, 0, NIGHT)])
        assert values == [1359, 41]

    def test_wh_register_wrapped_before_the_first_read(self):
        values = _read(_corrector(), [(900, 2, EVENING), (100, 1, NIGHT)])
        assert values == [2900, 200]

    def test_day_below_one_kwh_uses_home_assistant_midnight(self):
        """With the kWh register already zero the reset is invisible."""
        values = _read(
            _corrector(),
            [(800, 0, EVENING), (820, 0, NIGHT), (900, 0, MORNING)],
        )
        assert values == [800, 20, 100]

    def test_device_clock_ahead_is_not_reset_twice(self):
        values = _read(
            _corrector(),
            [
                (300, 1, EVENING - timedelta(minutes=10)),
                (310, 0, EVENING),  # device midnight at 23:45
                (320, 0, NIGHT),
            ],
        )
        assert values == [1300, 10, 20]

    def test_device_clock_behind_waits_for_the_reset(self):
        values = _read(
            _corrector(),
            [
                (300, 1, EVENING),
                (310, 1, NIGHT),  # device still before its midnight
                (320, 0, NIGHT + timedelta(minutes=10)),
            ],
        )
        assert values == [1300, 1310, 10]


class TestResettingWhRegister:
    """A device that resets both registers keeps its values."""

    def test_no_offset_when_the_wh_register_resets(self):
        values = _read(
            _corrector(),
            [(359, 1, EVENING), (5, 0, NIGHT), (600, 0, MORNING)],
        )
        assert values == [1359, 5, 600]

    def test_late_device_reset_clears_the_offset(self):
        """HA's midnight guessed a kept Wh part; the device's reset undoes it."""
        values = _read(
            _corrector(),
            [
                (800, 0, EVENING),
                (810, 0, NIGHT),
                (3, 0, NIGHT + timedelta(minutes=10)),
            ],
        )
        assert values == [800, 10, 3]


class TestPersistence:
    def test_state_is_saved_with_a_delay(self):
        store = FakeStore()
        corrector = DailyEnergyCorrector(store, frozenset({BLOCK}))
        corrector.correct(BLOCK, 359, 1, EVENING)
        corrector.correct(BLOCK, 359, 0, NIGHT)
        assert store.saves == [SAVE_DELAY, SAVE_DELAY]
        assert store.data == {
            BLOCK: {"low": 359, "high": 0, "offset": 359, "day": "2026-09-26"}
        }

    @pytest.mark.asyncio
    async def test_offset_survives_a_restart(self):
        store = FakeStore()
        before = DailyEnergyCorrector(store, frozenset({BLOCK}))
        _read(before, [(359, 1, EVENING), (359, 0, NIGHT)])

        after = DailyEnergyCorrector(FakeStore(store.data), frozenset({BLOCK}))
        await after.async_load()
        assert _read(after, [(500, 0, MORNING)]) == [141]

    @pytest.mark.asyncio
    async def test_reset_while_home_assistant_was_stopped(self):
        store = FakeStore(
            {BLOCK: {"low": 359, "high": 1, "offset": 0, "day": "2026-09-25"}}
        )
        corrector = DailyEnergyCorrector(store, frozenset({BLOCK}))
        await corrector.async_load()
        assert _read(corrector, [(400, 0, MORNING)]) == [41]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data",
        [
            None,
            [],
            {BLOCK: "garbage"},
            {BLOCK: {"low": 1}},
            {BLOCK: {"low": 1, "high": 0, "offset": 0, "day": "yesterday"}},
            {"pxxFB": {"low": 1, "high": 0, "offset": 1, "day": "2026-09-26"}},
        ],
    )
    async def test_unusable_stored_state_is_ignored(self, data):
        corrector = _corrector(data)
        await corrector.async_load()
        assert _read(corrector, [(500, 0, MORNING)]) == [500]

    @pytest.mark.asyncio
    async def test_load_error_is_logged(self, caplog):
        corrector = DailyEnergyCorrector(
            FakeStore(error=OSError("disk")), frozenset({BLOCK})
        )
        await corrector.async_load()
        assert "daily energy counter state" in caplog.text
        assert _read(corrector, [(500, 0, MORNING)]) == [500]


class TestDailyBlocks:
    def test_daily_blocks_of_firmware_439(self):
        assert RegisterMapManager("439").get_daily_blocks() == {
            "pxx0A03AE",
            "pxx0A092A",
            "pxx0A092E",
            "pxx0A091A",
            "pxx0A091E",
        }

    def test_no_daily_blocks_on_firmware_206(self):
        assert RegisterMapManager("206").get_daily_blocks() == frozenset()

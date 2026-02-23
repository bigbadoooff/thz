"""Tests for time conversion functions."""
from datetime import time

import pytest

from custom_components.thz.const import TIME_VALUE_UNSET
from custom_components.thz.time import quarters_to_time, time_to_quarters


class TestTimeToQuarters:
    """Tests for time_to_quarters function."""

    def test_midnight(self):
        """Test conversion of midnight (00:00)."""
        assert time_to_quarters(time(0, 0)) == 0

    def test_quarter_past_midnight(self):
        """Test conversion of 00:15."""
        assert time_to_quarters(time(0, 15)) == 1

    def test_half_past_midnight(self):
        """Test conversion of 00:30."""
        assert time_to_quarters(time(0, 30)) == 2

    def test_quarter_to_one(self):
        """Test conversion of 00:45."""
        assert time_to_quarters(time(0, 45)) == 3

    def test_one_oclock(self):
        """Test conversion of 01:00."""
        assert time_to_quarters(time(1, 0)) == 4

    def test_noon(self):
        """Test conversion of 12:00."""
        assert time_to_quarters(time(12, 0)) == 48

    def test_end_of_day(self):
        """Test conversion of 23:45 (last valid time)."""
        assert time_to_quarters(time(23, 45)) == 95

    def test_none_returns_unset(self):
        """Test that None returns the sentinel value."""
        assert time_to_quarters(None) == TIME_VALUE_UNSET

    def test_minutes_rounded_down(self):
        """Test that minutes are rounded down to nearest 15."""
        assert time_to_quarters(time(1, 14)) == 4  # Rounds to 01:00
        assert time_to_quarters(time(1, 29)) == 5  # Rounds to 01:15
        assert time_to_quarters(time(1, 44)) == 6  # Rounds to 01:30
        assert time_to_quarters(time(1, 59)) == 7  # Rounds to 01:45


class TestQuartersToTime:
    """Tests for quarters_to_time function."""

    def test_midnight(self):
        """Test conversion of 0 to midnight."""
        assert quarters_to_time(0) == time(0, 0)

    def test_quarter_past_midnight(self):
        """Test conversion of 1 to 00:15."""
        assert quarters_to_time(1) == time(0, 15)

    def test_half_past_midnight(self):
        """Test conversion of 2 to 00:30."""
        assert quarters_to_time(2) == time(0, 30)

    def test_quarter_to_one(self):
        """Test conversion of 3 to 00:45."""
        assert quarters_to_time(3) == time(0, 45)

    def test_one_oclock(self):
        """Test conversion of 4 to 01:00."""
        assert quarters_to_time(4) == time(1, 0)

    def test_noon(self):
        """Test conversion of 48 to 12:00."""
        assert quarters_to_time(48) == time(12, 0)

    def test_end_of_day(self):
        """Test conversion of 95 to 23:45."""
        assert quarters_to_time(95) == time(23, 45)

    def test_unset_returns_none(self):
        """Test that sentinel value returns None."""
        assert quarters_to_time(TIME_VALUE_UNSET) is None

    def test_invalid_value_clamped(self):
        """Test that invalid values are clamped to valid range."""
        # Values above 96 should be clamped to 95
        assert quarters_to_time(100) == time(23, 45)
        # Negative values should be clamped to 0
        assert quarters_to_time(-1) == time(0, 0)

    def test_end_of_day_value(self):
        """Test that value 96 (24:00) is treated as end-of-day (00:00)."""
        assert quarters_to_time(96) == time(0, 0)


class TestEndOfDay:
    """Tests for end-of-day (value 96) handling."""

    def test_time_to_quarters_end_time_midnight(self):
        """For end-time entities, time(0, 0) encodes as 96 (end-of-day)."""
        assert time_to_quarters(time(0, 0), is_end_time=True) == 96

    def test_time_to_quarters_start_time_midnight(self):
        """For start-time entities, time(0, 0) encodes as 0 (start-of-day)."""
        assert time_to_quarters(time(0, 0), is_end_time=False) == 0
        assert time_to_quarters(time(0, 0)) == 0  # default

    def test_time_to_quarters_end_time_non_midnight(self):
        """For end-time entities, non-midnight values encode normally."""
        assert time_to_quarters(time(23, 45), is_end_time=True) == 95
        assert time_to_quarters(time(12, 0), is_end_time=True) == 48

    def test_round_trip_end_of_day(self):
        """96 -> time(0, 0) -> 96 (end-time round trip)."""
        t = quarters_to_time(96)
        assert t == time(0, 0)
        assert time_to_quarters(t, is_end_time=True) == 96


class TestRoundTrip:
    """Tests for round-trip conversions."""

    def test_round_trip_exact_quarters(self):
        """Test that conversion works both ways for exact quarters."""
        for hour in range(24):
            for minute in [0, 15, 30, 45]:
                t = time(hour, minute)
                quarters = time_to_quarters(t)
                result = quarters_to_time(quarters)
                assert result == t, f"Failed for {t}"

    def test_round_trip_with_rounding(self):
        """Test that non-quarter minutes round correctly."""
        # 01:14 should round to 01:00
        t = time(1, 14)
        quarters = time_to_quarters(t)
        result = quarters_to_time(quarters)
        assert result == time(1, 0)

        # 01:47 should round to 01:45
        t = time(1, 47)
        quarters = time_to_quarters(t)
        result = quarters_to_time(quarters)
        assert result == time(1, 45)

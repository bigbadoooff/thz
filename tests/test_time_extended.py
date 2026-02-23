"""Additional tests for time module to increase coverage."""

import pytest
from datetime import time

from custom_components.thz.const import TIME_VALUE_UNSET
from custom_components.thz.time import quarters_to_time, time_to_quarters


class TestTimeConversionEdgeCases:
    """Additional edge case tests for time conversion."""

    def test_quarters_to_time_boundary_values(self):
        """Test boundary values for quarters_to_time."""
        # Test 0 (midnight)
        assert quarters_to_time(0) == time(0, 0)
        
        # Test maximum valid value (95 = 23:45)
        assert quarters_to_time(95) == time(23, 45)
        
        # Test mid-range values
        assert quarters_to_time(50) == time(12, 30)
        assert quarters_to_time(40) == time(10, 0)

    def test_time_to_quarters_all_valid_times(self):
        """Test time_to_quarters for various valid times."""
        # Morning times
        assert time_to_quarters(time(0, 0)) == 0
        assert time_to_quarters(time(6, 30)) == 26
        assert time_to_quarters(time(9, 45)) == 39
        
        # Afternoon times
        assert time_to_quarters(time(12, 0)) == 48
        assert time_to_quarters(time(15, 15)) == 61
        assert time_to_quarters(time(18, 30)) == 74
        
        # Evening times
        assert time_to_quarters(time(21, 45)) == 87
        assert time_to_quarters(time(23, 45)) == 95

    def test_time_to_quarters_rounding_comprehensive(self):
        """Test comprehensive rounding behavior."""
        # Test values that should round down
        assert time_to_quarters(time(10, 1)) == 40   # Rounds to 10:00
        assert time_to_quarters(time(10, 7)) == 40   # Rounds to 10:00
        assert time_to_quarters(time(10, 14)) == 40  # Rounds to 10:00
        
        # Test values at quarter boundaries
        assert time_to_quarters(time(10, 15)) == 41  # Exact quarter
        assert time_to_quarters(time(10, 30)) == 42  # Exact quarter
        assert time_to_quarters(time(10, 45)) == 43  # Exact quarter
        
        # Test values that round to next quarter
        assert time_to_quarters(time(10, 16)) == 41  # Rounds to 10:15
        assert time_to_quarters(time(10, 31)) == 42  # Rounds to 10:30
        assert time_to_quarters(time(10, 46)) == 43  # Rounds to 10:45

    def test_quarters_clamping(self):
        """Test that out-of-range quarter values are clamped, but 96 is end-of-day."""
        # 96 means 24:00 (end-of-day) -> returned as 00:00
        assert quarters_to_time(96) == time(0, 0)

        # Values above 96 should clamp to 95 (23:45)
        assert quarters_to_time(100) == time(23, 45)
        assert quarters_to_time(200) == time(23, 45)

        # Negative values should clamp to 0 (00:00)
        assert quarters_to_time(-1) == time(0, 0)
        assert quarters_to_time(-10) == time(0, 0)

    def test_unset_value_handling(self):
        """Test handling of TIME_VALUE_UNSET sentinel."""
        # Converting None to quarters should return unset
        assert time_to_quarters(None) == TIME_VALUE_UNSET
        
        # Converting unset value to time should return None
        assert quarters_to_time(TIME_VALUE_UNSET) is None
        assert quarters_to_time(128) is None  # 0x80 = 128

    def test_round_trip_all_quarters(self):
        """Test round-trip conversion for all valid quarter values."""
        for quarter in range(96):  # 0 to 95
            if quarter != TIME_VALUE_UNSET:  # Skip sentinel value
                t = quarters_to_time(quarter)
                result = time_to_quarters(t)
                assert result == quarter, f"Round-trip failed for quarter {quarter}"

    def test_special_times(self):
        """Test special time values."""
        # Test midnight
        assert time_to_quarters(time(0, 0)) == 0
        assert quarters_to_time(0) == time(0, 0)
        
        # Test noon
        assert time_to_quarters(time(12, 0)) == 48
        assert quarters_to_time(48) == time(12, 0)
        
        # Test end of day
        assert time_to_quarters(time(23, 59)) == 95  # Rounds down to 23:45
        assert quarters_to_time(95) == time(23, 45)


class TestTimeModuleConstants:
    """Test time module constants."""

    def test_time_value_unset_constant(self):
        """Test TIME_VALUE_UNSET constant value."""
        from custom_components.thz.time import TIME_VALUE_UNSET as TIME_UNSET_LOCAL
        assert TIME_UNSET_LOCAL == 0x80
        assert TIME_UNSET_LOCAL == 128

    def test_quarters_per_hour(self):
        """Test that there are 4 quarters per hour."""
        # 1 hour = 4 quarters
        assert time_to_quarters(time(1, 0)) == 4
        assert time_to_quarters(time(2, 0)) == 8
        assert time_to_quarters(time(3, 0)) == 12
        
        # Verify pattern continues
        for hour in range(24):
            expected_quarters = hour * 4
            assert time_to_quarters(time(hour, 0)) == expected_quarters

    def test_minutes_per_quarter(self):
        """Test that each quarter represents 15 minutes."""
        # Each quarter = 15 minutes
        assert quarters_to_time(1) == time(0, 15)
        assert quarters_to_time(2) == time(0, 30)
        assert quarters_to_time(3) == time(0, 45)
        assert quarters_to_time(4) == time(1, 0)


class TestTimeConversionConsistency:
    """Test consistency between time conversion functions."""

    def test_none_handling_consistency(self):
        """Test that None is consistently handled."""
        # None -> quarters -> time should return None
        quarters = time_to_quarters(None)
        assert quarters == TIME_VALUE_UNSET
        result = quarters_to_time(quarters)
        assert result is None

    def test_symmetry_for_exact_quarters(self):
        """Test symmetry for exact quarter-hour times."""
        for hour in range(24):
            for minute in [0, 15, 30, 45]:
                original = time(hour, minute)
                quarters = time_to_quarters(original)
                result = quarters_to_time(quarters)
                assert result == original, f"Symmetry broken for {hour}:{minute}"

    def test_idempotent_conversions(self):
        """Test that multiple conversions produce same result."""
        original_time = time(14, 30)
        
        # time -> quarters -> time -> quarters should be same as time -> quarters
        quarters1 = time_to_quarters(original_time)
        time1 = quarters_to_time(quarters1)
        quarters2 = time_to_quarters(time1)
        
        assert quarters1 == quarters2


class TestTimeValidation:
    """Test time validation and error handling."""

    def test_valid_time_objects(self):
        """Test that valid time objects are accepted."""
        valid_times = [
            time(0, 0),
            time(12, 30),
            time(23, 59),
            time(6, 45),
            time(18, 15),
        ]
        
        for t in valid_times:
            result = time_to_quarters(t)
            assert isinstance(result, int)
            assert 0 <= result <= 95

    def test_quarter_range(self):
        """Test that quarter values stay in valid range."""
        for hour in range(24):
            for minute in range(0, 60, 15):
                t = time(hour, minute)
                quarters = time_to_quarters(t)
                assert 0 <= quarters <= 95, f"Invalid quarters {quarters} for {hour}:{minute}"

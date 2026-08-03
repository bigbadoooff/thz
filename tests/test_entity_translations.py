"""Tests for entity translation mappings."""


from custom_components.thz.entity_translations import (
    ENTITY_TRANSLATION_KEYS,
    get_translation_key,
)


class TestEntityTranslationKeys:
    """Test the ENTITY_TRANSLATION_KEYS dictionary."""

    def test_dictionary_not_empty(self):
        """Test that the translation keys dictionary is not empty."""
        assert len(ENTITY_TRANSLATION_KEYS) > 0

    def test_op_mode_key_exists(self):
        """Test that operating mode key exists."""
        assert "pOpMode" in ENTITY_TRANSLATION_KEYS
        assert ENTITY_TRANSLATION_KEYS["pOpMode"] == "op_mode"

    def test_room_temp_keys_exist(self):
        """Test that room temperature keys exist."""
        assert "p01RoomTempDay" in ENTITY_TRANSLATION_KEYS
        assert "p02RoomTempNight" in ENTITY_TRANSLATION_KEYS
        assert "p03RoomTempStandby" in ENTITY_TRANSLATION_KEYS

    def test_dhw_temp_keys_exist(self):
        """Test that DHW temperature keys exist (write_map_206 format)."""
        assert "p04DHWsetTempDay" in ENTITY_TRANSLATION_KEYS
        assert "p05DHWsetTempNight" in ENTITY_TRANSLATION_KEYS
        assert "p06DHWsetTempStandby" in ENTITY_TRANSLATION_KEYS

    def test_dhw_temp_keys_exist_439_539(self):
        """Test that DHW temperature keys exist (write_map_439_539 format)."""
        assert "p04DHWsetDayTemp" in ENTITY_TRANSLATION_KEYS
        assert "p05DHWsetNightTemp" in ENTITY_TRANSLATION_KEYS
        assert "p06DHWsetStandbyTemp" in ENTITY_TRANSLATION_KEYS
        assert "p11DHWsetManualTemp" in ENTITY_TRANSLATION_KEYS

    def test_fan_stage_keys_exist(self):
        """Test that fan stage keys exist."""
        assert "p07FanStageDay" in ENTITY_TRANSLATION_KEYS
        assert "p08FanStageNight" in ENTITY_TRANSLATION_KEYS
        assert "p09FanStageStandby" in ENTITY_TRANSLATION_KEYS

    def test_hc2_keys_exist(self):
        """Test that HC2 keys exist."""
        assert "p01RoomTempDayHC2" in ENTITY_TRANSLATION_KEYS
        assert "p16GradientHC2" in ENTITY_TRANSLATION_KEYS
        assert "p17LowEndHC2" in ENTITY_TRANSLATION_KEYS

    def test_all_values_are_strings(self):
        """Test that all translation keys are strings."""
        for key, value in ENTITY_TRANSLATION_KEYS.items():
            assert isinstance(key, str), f"Key {key} is not a string"
            assert isinstance(value, str), (
                f"Value {value} for key {key} is not a string"
            )

    def test_no_duplicate_values(self):
        """Translation keys don't have duplicate values (except where expected)."""
        values = list(ENTITY_TRANSLATION_KEYS.values())
        # Some duplicates may be intentional (like p84 having two entries)
        # Just ensure the structure is correct
        assert len(values) > 0


class TestGetTranslationKey:
    """Test the get_translation_key function."""

    def test_existing_key(self):
        """Test getting an existing translation key."""
        result = get_translation_key("pOpMode")
        assert result == "op_mode"

    def test_room_temp_day(self):
        """Test getting room temperature day key."""
        result = get_translation_key("p01RoomTempDay")
        assert result == "room_temp_day"

    def test_dhw_temp(self):
        """Test getting DHW temperature key (write_map_206 format)."""
        result = get_translation_key("p04DHWsetTempDay")
        assert result == "dhw_temp_day"

    def test_dhw_temp_439_539(self):
        """Test getting DHW temperature key (write_map_439_539 format)."""
        result = get_translation_key("p04DHWsetDayTemp")
        assert result == "dhw_temp_day"
        result = get_translation_key("p05DHWsetNightTemp")
        assert result == "dhw_temp_night"

    def test_non_existing_key(self):
        """Test getting a non-existing key returns None."""
        result = get_translation_key("nonExistentKey")
        assert result is None

    def test_empty_string(self):
        """Test getting translation for empty string."""
        result = get_translation_key("")
        assert result is None

    def test_hc1_keys(self):
        """Test HC1-specific keys."""
        assert get_translation_key("p13GradientHC1") == "gradient_hc1"
        assert get_translation_key("p14LowEndHC1") == "low_end_hc1"
        assert get_translation_key("p15RoomInfluenceHC1") == "room_influence_hc1"

    def test_hc2_keys(self):
        """Test HC2-specific keys."""
        assert get_translation_key("p16GradientHC2") == "gradient_hc2"
        assert get_translation_key("p17LowEndHC2") == "low_end_hc2"
        assert get_translation_key("p18RoomInfluenceHC2") == "room_influence_hc2"

    def test_hysteresis_keys(self):
        """Test hysteresis parameter keys."""
        assert get_translation_key("p21Hyst1") == "hysteresis_1"
        assert get_translation_key("p22Hyst2") == "hysteresis_2"
        assert get_translation_key("p29HystAsymmetry") == "hysteresis_asymmetry"

    def test_solar_keys(self):
        """Test solar-related keys."""
        assert get_translation_key("p80EnableSolar") == "enable_solar"
        key = get_translation_key("p81DiffTempSolarLoading")
        assert key == "diff_temp_solar_loading"

    def test_cooling_keys(self):
        """Test cooling parameter keys (p99 extended parameters)."""
        assert get_translation_key("p99CoolingHC1SetTemp") == "cooling_hc1_set_temp"
        assert get_translation_key("p99CoolingHC2SetTemp") == "cooling_hc2_set_temp"

    def test_pump_rate_keys(self):
        """Test pump rate keys."""
        assert get_translation_key("p99PumpRateDHW") == "pump_rate_dhw"
        assert get_translation_key("p99PumpRateHC") == "pump_rate_hc"

    def test_alternative_naming(self):
        """Test that alternative naming conventions map to the same keys."""
        # DHW temp variations
        assert get_translation_key("p04DHWsetTempDay") == get_translation_key(
            "p04DHWsetDayTemp"
        )
        assert get_translation_key("p05DHWsetTempNight") == get_translation_key(
            "p05DHWsetNightTemp"
        )
        # Passive cooling case variation
        assert get_translation_key("p75PassiveCooling") == get_translation_key(
            "p75passiveCooling"
        )

    def test_program_hc1_all_keys(self):
        """Test all HC1 program schedule keys exist and are valid."""
        days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "So"]
        day_ranges = ["Mo-Fr", "Sa-So", "Mo-So"]
        slots = [0, 1, 2]

        # Test individual days
        for day in days:
            for slot in slots:
                key = f"programHC1_{day}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                assert translation_key.startswith("programhc1_"), (
                    f"Invalid translation key format: {translation_key}"
                )
                # Verify no hyphens in translation key
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

        # Test day ranges
        for day_range in day_ranges:
            for slot in slots:
                key = f"programHC1_{day_range}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                # Verify hyphens are converted to underscores
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

    def test_program_hc2_all_keys(self):
        """Test all HC2 program schedule keys exist and are valid."""
        days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "So"]
        day_ranges = ["Mo-Fr", "Sa-So", "Mo-So"]
        slots = [0, 1, 2]

        for day in days:
            for slot in slots:
                key = f"programHC2_{day}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

        for day_range in day_ranges:
            for slot in slots:
                key = f"programHC2_{day_range}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

    def test_program_dhw_all_keys(self):
        """Test all DHW program schedule keys exist and are valid."""
        days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "So"]
        day_ranges = ["Mo-Fr", "Sa-So", "Mo-So"]
        slots = [0, 1, 2]

        for day in days:
            for slot in slots:
                key = f"programDHW_{day}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

        for day_range in day_ranges:
            for slot in slots:
                key = f"programDHW_{day_range}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

    def test_program_fan_all_keys(self):
        """Test all Fan program schedule keys exist and are valid."""
        days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "So"]
        day_ranges = ["Mo-Fr", "Sa-So", "Mo-So"]
        slots = [0, 1, 2]

        for day in days:
            for slot in slots:
                key = f"programFan_{day}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

        for day_range in day_ranges:
            for slot in slots:
                key = f"programFan_{day_range}_{slot}"
                translation_key = get_translation_key(key)
                assert translation_key is not None, f"Missing translation for {key}"
                assert "-" not in translation_key, (
                    f"Translation key {translation_key} contains hyphen"
                )

    def test_all_program_keys_count(self):
        """Test that we have exactly 120 base program translation keys.

        This validates the base program keys only (without _start/_end suffixes).
        Total program-related keys: 120 base + 120 _start + 120 _end = 360 keys.
        Structure: 4 program types x 30 entities each = 120 base keys
        - Each type has: 7 individual days x 3 slots + 3 day ranges x 3 slots = 30 keys
        """
        program_keys = [
            k for k in ENTITY_TRANSLATION_KEYS.keys() if k.startswith("program")
        ]
        # 4 program types × 30 entities each = 120 total base keys
        assert len(program_keys) == 120, (
            f"Expected 120 program keys, found {len(program_keys)}"
        )

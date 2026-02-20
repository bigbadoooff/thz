"""Tests for sensor name processing and metadata lookup.

This test file verifies that sensor names from register maps are correctly
cleaned and that metadata is correctly stored in register map tuples.
"""

import pytest


class TestSensorNameCleaning:
    """Test sensor name cleaning logic."""

    def test_strip_trailing_colon(self):
        """Test that trailing colons are stripped from sensor names."""
        name = "outsideTemp:"
        cleaned = name.strip().rstrip(':')
        assert cleaned == "outsideTemp"

    def test_strip_whitespace_and_colon(self):
        """Test that both whitespace and colons are stripped."""
        name = "  flowTemp:  "
        cleaned = name.strip().rstrip(':')
        assert cleaned == "flowTemp"

    def test_no_colon(self):
        """Test that names without colons are unchanged."""
        name = "returnTemp"
        cleaned = name.strip().rstrip(':')
        assert cleaned == "returnTemp"

    def test_multiple_trailing_colons(self):
        """Test that multiple trailing colons are all stripped."""
        name = "dhwTemp:::"
        cleaned = name.strip().rstrip(':')
        assert cleaned == "dhwTemp"


class TestSensorMetadataLookup:
    """Test that sensor metadata is present in register map tuples."""

    def test_register_map_tuple_has_metadata(self):
        """Test that pxxFB entries have translation_key in 6th element."""
        from custom_components.thz.register_maps.register_map_all import REGISTER_MAP

        # Build lookup: cleaned name -> meta
        fb_meta = {e[0].strip().rstrip(":"): e[5] for e in REGISTER_MAP["pxxFB"] if len(e) > 5}

        assert "outsideTemp" in fb_meta
        assert fb_meta["outsideTemp"].get("translation_key") == "outside_temp"

    def test_common_sensors_have_metadata(self):
        """Test that common sensor names have metadata entries in register map."""
        from custom_components.thz.register_maps.register_map_all import REGISTER_MAP

        fb_meta = {e[0].strip().rstrip(":"): e[5] for e in REGISTER_MAP["pxxFB"] if len(e) > 5}

        common_sensors = [
            "outsideTemp",
            "flowTemp",
            "returnTemp",
            "hotGasTemp",
            "dhwTemp",
            "evaporatorTemp",
            "condenserTemp",
        ]

        for sensor in common_sensors:
            meta = fb_meta.get(sensor, {})
            assert meta, f"Sensor {sensor} should have metadata in register map"
            assert meta.get("translation_key"), f"Sensor {sensor} should have translation_key"


class TestEntityHiding:
    """Test entity hiding logic with sensor names."""

    def test_hc2_sensors_hidden(self):
        """Test that HC2 sensors are hidden by default."""
        from custom_components.thz.const import should_hide_entity_by_default
        
        hc2_sensors = ["flowTempHC2", "roomTempHC2", "setTempHC2"]
        for sensor in hc2_sensors:
            assert should_hide_entity_by_default(sensor), f"{sensor} should be hidden"

    def test_program_entities_hidden(self):
        """Test that program entities are hidden by default."""
        from custom_components.thz.const import should_hide_entity_by_default
        
        program_entities = ["programDHW_Mo", "programHC1_Tu", "programHC2_We"]
        for entity in program_entities:
            assert should_hide_entity_by_default(entity), f"{entity} should be hidden"

    def test_advanced_parameters_hidden(self):
        """Test that advanced parameters (p13+) are hidden by default."""
        from custom_components.thz.const import should_hide_entity_by_default
        
        advanced_params = ["p13GradientHC1", "p21Hyst1", "p30integralComponent"]
        for param in advanced_params:
            assert should_hide_entity_by_default(param), f"{param} should be hidden"

    def test_basic_entities_visible(self):
        """Test that basic entities are visible by default."""
        from custom_components.thz.const import should_hide_entity_by_default
        
        basic_entities = [
            "outsideTemp",
            "flowTemp",
            "dhwTemp",
            "p01RoomTempDay",
            "p04DHWsetTempDay",
            "pOpMode"
        ]
        for entity in basic_entities:
            assert not should_hide_entity_by_default(entity), f"{entity} should be visible"

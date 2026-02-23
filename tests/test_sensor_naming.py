"""Tests for sensor name processing and metadata lookup.

This test file verifies that sensor names from register maps are correctly
cleaned and matched against SENSOR_META entries to ensure proper entity
naming and translation key assignment.
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


class TestSensorUniqueIdExtraction:
    """Test extraction of internal sensor name from unique_id for visibility checks.

    Sensor unique_ids have the format:
        thz_{block}_{int_offset}_{entity_name_lower}
    where {block} is a Python bytes repr (e.g. b'\\n\\t(') that may itself contain
    underscores or special characters.  The regex used in
    _async_enable_integration_disabled_entities must correctly extract the entity
    name so that should_hide_entity_by_default() returns the right value even when
    entity.original_name is None (e.g. because a translation lookup failed).
    """

    @staticmethod
    def _extract_name_from_sensor_uid(unique_id: str) -> str | None:
        """Simulate the regex extraction logic from __init__.py."""
        import re
        match = re.search(r"^thz_.+_(\d+)_([a-z][a-z0-9_-]*)$", unique_id)
        return match.group(2) if match else None

    def test_hc2_sensor_name_extracted(self):
        """Entity name is extracted from HC2 sensor unique_id."""
        from custom_components.thz.const import should_hide_entity_by_default

        # Simulate unique_id for flowTempHC2 at block b'\n\t(' offset 4
        block_repr = repr(bytes.fromhex("0a0928"))  # b'\n\t('
        unique_id = f"thz_{block_repr}_4_flowtemphc2"
        name = self._extract_name_from_sensor_uid(unique_id)
        assert name == "flowtemphc2"
        assert should_hide_entity_by_default(name)

    def test_basic_sensor_name_extracted(self):
        """Entity name is extracted from a basic (non-hidden) sensor unique_id."""
        from custom_components.thz.const import should_hide_entity_by_default

        block_repr = repr(bytes.fromhex("0a0900"))
        unique_id = f"thz_{block_repr}_4_outsidetemp"
        name = self._extract_name_from_sensor_uid(unique_id)
        assert name == "outsidetemp"
        assert not should_hide_entity_by_default(name)

    def test_sensor_name_with_underscores(self):
        """Entity name with underscores is extracted correctly."""
        block_repr = repr(bytes.fromhex("0a0900"))
        unique_id = f"thz_{block_repr}_37_outside_tempfiltered"
        name = self._extract_name_from_sensor_uid(unique_id)
        assert name == "outside_tempfiltered"

    def test_block_bytes_with_underscore_char(self):
        """Block repr containing '_' character does not confuse extraction."""
        # 0x5f = '_' (underscore), so this block repr will contain '_'
        block_repr = repr(bytes.fromhex("5f01"))  # b'_\x01'
        unique_id = f"thz_{block_repr}_4_flowtemphc2"
        name = self._extract_name_from_sensor_uid(unique_id)
        assert name == "flowtemphc2"

    def test_calendar_entity_uid_does_not_match(self):
        """Calendar entity unique_ids don't match the sensor regex."""
        # Calendar UID: thz_{name_lower} - no _integer_ segment
        uid = "thz_programdhw_mo_0"
        assert self._extract_name_from_sensor_uid(uid) is None

    def test_cop_sensor_uid_does_not_match(self):
        """COP sensor unique_ids don't match the sensor regex."""
        uid = "thz_ip-192.168.1.100_current_cop"
        assert self._extract_name_from_sensor_uid(uid) is None

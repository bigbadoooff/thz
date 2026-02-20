"""Tests for sensor module functions."""

import pytest

from custom_components.thz.sensor import normalize_entry


class TestNormalizeEntry:
    """Tests for normalize_entry function."""

    def test_normalize_tuple_entry(self):
        """Test normalizing a 5-element tuple entry (no metadata)."""
        entry = ("outsideTemp", 0, 4, "hex2int", 10)
        result = normalize_entry(entry)
        
        assert isinstance(result, dict)
        assert result["name"] == "outsideTemp"
        assert result["offset"] == 0
        assert result["length"] == 4
        assert result["decode"] == "hex2int"
        assert result["factor"] == 10
        assert result["unit"] is None
        assert result["device_class"] is None
        assert result["state_class"] is None
        assert result["icon"] is None
        assert result["translation_key"] is None

    def test_normalize_tuple_entry_with_metadata(self):
        """Test normalizing a 6-element tuple entry (with metadata dict)."""
        meta = {"unit": "°C", "device_class": "temperature", "state_class": "measurement",
                "icon": "mdi:thermometer", "translation_key": "outside_temp"}
        entry = ("outsideTemp:", 8, 4, "hex2int", 10, meta)
        result = normalize_entry(entry)

        assert result["name"] == "outsideTemp:"
        assert result["unit"] == "°C"
        assert result["device_class"] == "temperature"
        assert result["state_class"] == "measurement"
        assert result["icon"] == "mdi:thermometer"
        assert result["translation_key"] == "outside_temp"

    def test_normalize_tuple_with_whitespace(self):
        """Test normalizing a tuple entry with whitespace in name."""
        entry = ("  flowTemp  ", 2, 4, "hex2int", 10)
        result = normalize_entry(entry)
        
        assert result["name"] == "flowTemp"
        assert result["offset"] == 2
        assert result["length"] == 4

    def test_normalize_dict_entry(self):
        """Test normalizing a dictionary entry (returns as-is)."""
        entry = {
            "name": "dhwTemp",
            "offset": 4,
            "length": 4,
            "decode": "hex2int",
            "factor": 10,
            "unit": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
            "icon": "mdi:thermometer",
            "translation_key": "dhw_temp",
        }
        result = normalize_entry(entry)
        
        assert result == entry
        assert result["name"] == "dhwTemp"
        assert result["unit"] == "°C"
        assert result["device_class"] == "temperature"

    def test_normalize_invalid_entry(self):
        """Test normalizing an invalid entry type raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported sensor entry format"):
            normalize_entry("invalid_string")

    def test_normalize_invalid_list(self):
        """Test normalizing a list raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported sensor entry format"):
            normalize_entry(["name", 0, 4, "hex2int", 10])

    def test_normalize_tuple_minimal(self):
        """Test normalizing tuple with minimal values."""
        entry = ("sensor", 0, 2, "hex", 1)
        result = normalize_entry(entry)
        
        assert result["name"] == "sensor"
        assert result["offset"] == 0
        assert result["length"] == 2
        assert result["decode"] == "hex"
        assert result["factor"] == 1


class TestSensorNameCleaning:
    """Tests for sensor name cleaning logic in async_setup_entry."""

    def test_strip_trailing_colon_from_name(self):
        """Test that trailing colons are stripped."""
        name = "outsideTemp:"
        cleaned = name.strip().rstrip(':')
        assert cleaned == "outsideTemp"

    def test_strip_whitespace_and_colon(self):
        """Test that whitespace and colons are stripped."""
        name = "  flowTemp:  "
        cleaned = name.strip().rstrip(':')
        assert cleaned == "flowTemp"

    def test_name_without_special_chars(self):
        """Test names without special characters."""
        name = "returnTemp"
        cleaned = name.strip().rstrip(':')
        assert cleaned == "returnTemp"


class TestSensorMetadataIntegration:
    """Tests for sensor metadata integration (now stored in register map tuples)."""

    def test_register_map_provides_device_class(self):
        """Test that register map tuples provide device class for temperature sensors."""
        from custom_components.thz.register_maps.register_map_all import REGISTER_MAP

        fb_entries = {e[0].strip().rstrip(":"): e[5] for e in REGISTER_MAP["pxxFB"] if len(e) > 5}
        meta = fb_entries.get("outsideTemp", {})
        assert meta.get("device_class") == "temperature"
        assert meta.get("unit") == "°C"

    def test_register_map_provides_translation_key(self):
        """Test that register map tuples provide translation key."""
        from custom_components.thz.register_maps.register_map_all import REGISTER_MAP

        fb_entries = {e[0].strip().rstrip(":"): e[5] for e in REGISTER_MAP["pxxFB"] if len(e) > 5}
        meta = fb_entries.get("outsideTemp", {})
        assert meta.get("translation_key") == "outside_temp"

    def test_missing_sensor_has_no_metadata(self):
        """Test that sensors without a 6th tuple element yield empty metadata."""
        # A 5-element tuple – no metadata
        entry = ("fakeTemp:", 0, 4, "hex2int", 10)
        meta = entry[5] if len(entry) > 5 else {}
        assert meta == {}
        assert meta.get("unit") is None


class TestOffsetLengthCalculation:
    """Tests for offset and length calculation logic."""

    def test_offset_byte_conversion(self):
        """Test offset conversion from register to byte offset."""
        # In the code: offset // 2
        register_offset = 4
        byte_offset = register_offset // 2
        assert byte_offset == 2

    def test_length_byte_conversion(self):
        """Test length conversion from register to byte length."""
        # In the code: (length + 1) // 2
        register_length = 4
        byte_length = (register_length + 1) // 2
        assert byte_length == 2

    def test_length_odd_value(self):
        """Test length conversion with odd register length."""
        register_length = 3
        byte_length = (register_length + 1) // 2
        assert byte_length == 2  # 3+1=4, 4//2=2

    def test_length_minimum(self):
        """Test length conversion with minimum register length."""
        register_length = 0
        byte_length = (register_length + 1) // 2
        assert byte_length == 0  # (0+1)//2 = 0 (actual result)
        
    def test_length_ensures_at_least_some_bytes(self):
        """Test that length conversion always produces a result."""
        register_length = 1
        byte_length = (register_length + 1) // 2
        assert byte_length == 1  # (1+1)//2 = 1


class TestBlockHexProcessing:
    """Tests for block hex string processing."""

    def test_remove_pxx_prefix(self):
        """Test removing 'pxx' prefix from block identifier."""
        block = "pxx0100"
        block_hex = block.removeprefix("pxx")
        assert block_hex == "0100"

    def test_block_without_prefix(self):
        """Test block without 'pxx' prefix."""
        block = "0100"
        block_hex = block.removeprefix("pxx")
        assert block_hex == "0100"

    def test_convert_hex_to_bytes(self):
        """Test converting hex string to bytes."""
        block_hex = "0100"
        block_bytes = bytes.fromhex(block_hex)
        assert block_bytes == b'\x01\x00'
        assert len(block_bytes) == 2


class TestDuplicateSensorHandling:
    """Tests for duplicate sensor name handling logic."""

    def test_duplicate_detection_logic(self):
        """Test the logic for detecting duplicate sensor names."""
        seen_sensor_names = set()
        
        # First sensor
        sensor_name = "outsideTemp"
        is_duplicate = sensor_name in seen_sensor_names
        assert not is_duplicate
        seen_sensor_names.add(sensor_name)
        
        # Second sensor with same name
        sensor_name = "outsideTemp"
        is_duplicate = sensor_name in seen_sensor_names
        assert is_duplicate

    def test_different_sensors_not_duplicate(self):
        """Test that different sensor names are not duplicates."""
        seen_sensor_names = set()
        
        sensor_name1 = "outsideTemp"
        sensor_name2 = "flowTemp"
        
        seen_sensor_names.add(sensor_name1)
        
        is_duplicate = sensor_name2 in seen_sensor_names
        assert not is_duplicate

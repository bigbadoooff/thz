"""Tests for register map manager."""

import pytest

from custom_components.thz.register_maps.register_map_manager import (
    FIRMWARE_MAPS,
    BaseRegisterMapManager,
    RegisterMapManager,
    RegisterMapManagerWrite,
)


class TestFirmwareMaps:
    """Test FIRMWARE_MAPS configuration."""

    def test_firmware_maps_not_empty(self):
        """Test that FIRMWARE_MAPS is not empty."""
        assert len(FIRMWARE_MAPS) > 0

    def test_206_firmware_config(self):
        """Test 206 firmware configuration."""
        assert "206" in FIRMWARE_MAPS
        config = FIRMWARE_MAPS["206"]
        assert "write" in config
        assert "read" in config
        assert "write_map_206" in config["write"]
        assert "readings_map_206" in config["read"]

    def test_214_firmware_config(self):
        """Test 214 firmware configuration."""
        assert "214" in FIRMWARE_MAPS
        config = FIRMWARE_MAPS["214"]
        assert "write" in config
        assert "read" in config
        assert "write_map_214" in config["write"]
        assert "readings_map_214" in config["read"]

    def test_439_firmware_config(self):
        """Test 439 firmware configuration."""
        assert "439" in FIRMWARE_MAPS
        config = FIRMWARE_MAPS["439"]
        assert "write" in config
        assert "read" in config
        assert "write_map_439" in config["write"]
        assert "readings_map_439" in config["read"]

    def test_539_firmware_config(self):
        """Test explicit 539 firmware configuration (539-like)."""
        assert "539" in FIRMWARE_MAPS
        config = FIRMWARE_MAPS["539"]
        assert "write" in config
        assert "read" in config
        assert "write_map_539" in config["write"]
        assert "readings_map_539" in config["read"]

    def test_default_firmware_config_is_439_like(self):
        """Unrecognized firmware strings must fall back to 4.39-like maps.

        Mirrors the reference FHEM 00_THZ.pm module, which treats any
        unrecognized ``firmware`` attribute as 4.39 (see docs/legacy/00_THZ.pm,
        "in all other cases I assume $attrVal eq '4.39'"). Falling back to
        5.39-like maps instead pulls in register offsets/fields that don't
        exist on 4.3x devices (e.g. firmware "438" on an LWZ 403).
        """
        assert "default" in FIRMWARE_MAPS
        config = FIRMWARE_MAPS["default"]
        assert "write" in config
        assert "read" in config
        assert "write_map_439" in config["write"]
        assert "readings_map_439" in config["read"]
        assert "write_map_539" not in config["write"]
        assert "readings_map_539" not in config["read"]

    def test_technician_mode_configs(self):
        """Test technician mode firmware configurations."""
        assert "439technician" in FIRMWARE_MAPS
        assert "539technician" in FIRMWARE_MAPS
        
        config_439t = FIRMWARE_MAPS["439technician"]
        assert "write_map_X39tech" in config_439t["write"]
        
        config_539t = FIRMWARE_MAPS["539technician"]
        assert "write_map_X39tech" in config_539t["write"]


class TestRegisterMapManager:
    """Test RegisterMapManager class."""

    def test_initialization_with_known_firmware(self):
        """Test initializing manager with known firmware version."""
        manager = RegisterMapManager("206")
        assert manager.get_firmware_version() == "206"

    def test_initialization_with_unknown_firmware(self):
        """Test initializing manager with unknown firmware version (uses default)."""
        manager = RegisterMapManager("unknown_version")
        assert manager.get_firmware_version() == "unknown_version"

    def test_get_all_registers(self):
        """Test getting all registers."""
        manager = RegisterMapManager("206")
        registers = manager.get_all_registers()
        assert isinstance(registers, dict)

    def test_get_registers_for_block(self):
        """Test getting registers for a specific block."""
        manager = RegisterMapManager("206")
        # Block 0x01 0x00 should exist in most firmware versions
        registers = manager.get_registers_for_block("\x01\x00")
        # Should return a list (even if empty)
        assert isinstance(registers, list)

    def test_get_registers_for_nonexistent_block(self):
        """Test getting registers for a non-existent block."""
        manager = RegisterMapManager("206")
        registers = manager.get_registers_for_block("\xff\xff")
        # Should return empty list
        assert registers == []

    def test_firmware_version_property(self):
        """Test firmware_version property."""
        manager = RegisterMapManager("214")
        assert manager.get_firmware_version() == "214"

    def test_readings_map_names_property(self):
        """Test readings_map_names property."""
        manager = RegisterMapManager("206")
        map_names = manager.readings_map_names
        assert isinstance(map_names, list)
        assert len(map_names) > 0

    def test_write_map_names_property(self):
        """Test write_map_names property."""
        manager = RegisterMapManager("206")
        map_names = manager.write_map_names
        assert isinstance(map_names, list)
        assert len(map_names) > 0

    def test_different_firmware_versions(self):
        """Test that different firmware versions load different maps."""
        manager_206 = RegisterMapManager("206")
        manager_214 = RegisterMapManager("214")
        
        # Both should be valid but potentially different
        assert manager_206.get_firmware_version() == "206"
        assert manager_214.get_firmware_version() == "214"


class TestRegisterMapManagerWrite:
    """Test RegisterMapManagerWrite class."""

    def test_initialization_with_known_firmware(self):
        """Test initializing write manager with known firmware version."""
        manager = RegisterMapManagerWrite("206")
        assert manager.get_firmware_version() == "206"

    def test_initialization_with_unknown_firmware(self):
        """Test initializing write manager with unknown firmware version."""
        manager = RegisterMapManagerWrite("unknown_version")
        assert manager.get_firmware_version() == "unknown_version"

    def test_get_all_registers(self):
        """Test getting all write registers."""
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()
        assert isinstance(registers, dict)

    def test_get_registers_for_block(self):
        """Test getting write registers for a specific block."""
        manager = RegisterMapManagerWrite("206")
        # Try a common write register key
        registers = manager.get_registers_for_block("pOpMode")
        # Could be dict or empty based on map structure

    def test_firmware_version_property(self):
        """Test firmware_version property for write manager."""
        manager = RegisterMapManagerWrite("214")
        assert manager.get_firmware_version() == "214"

    def test_readings_map_names_property(self):
        """Test readings_map_names property for write manager."""
        manager = RegisterMapManagerWrite("206")
        map_names = manager.readings_map_names
        assert isinstance(map_names, list)

    def test_write_map_names_property(self):
        """Test write_map_names property for write manager."""
        manager = RegisterMapManagerWrite("206")
        map_names = manager.write_map_names
        assert isinstance(map_names, list)
        assert len(map_names) > 0


class TestBaseRegisterMapManager:
    """Test BaseRegisterMapManager internals."""

    def test_normalize_name_with_string(self):
        """Test name normalization with string."""
        manager = RegisterMapManager("206")
        assert manager._normalize_name("  test  ") == "test"
        assert manager._normalize_name("test") == "test"

    def test_normalize_name_with_non_string(self):
        """Test name normalization with non-string."""
        manager = RegisterMapManager("206")
        # Should return input unchanged if not a string
        assert manager._normalize_name(123) == 123
        assert manager._normalize_name(None) is None

    def test_select_maps_for_known_firmware(self):
        """Test map selection for known firmware."""
        manager = RegisterMapManager("206")
        write_maps, read_maps = manager._select_maps_for_firmware("206")
        
        assert isinstance(write_maps, list)
        assert isinstance(read_maps, list)
        assert len(write_maps) > 0
        assert len(read_maps) > 0

    def test_select_maps_for_unknown_firmware(self):
        """Test map selection for unknown firmware uses default."""
        manager = RegisterMapManager("999")
        write_maps, read_maps = manager._select_maps_for_firmware("999")
        
        # Should return default maps
        assert isinstance(write_maps, list)
        assert isinstance(read_maps, list)

    def test_unrecognized_43x_firmware_uses_439_maps(self):
        """Regression test: firmware "438" (LWZ 403, off-by-a-point-release
        from the "439" entry) must load 439-style maps, not 539-style ones.
        """
        manager = RegisterMapManager("438")
        assert "readings_map_439" in manager.readings_map_names
        assert "readings_map_539" not in manager.readings_map_names

        write_manager = RegisterMapManagerWrite("438")
        assert "write_map_439" in write_manager.write_map_names
        assert "write_map_539" not in write_manager.write_map_names

    def test_non_cooling_539_keeps_non_cooling_read_blocks(self):
        """Test non-cooling 5.39 keeps shared blocks and removes cooling-only ones."""
        manager = RegisterMapManager("539", has_cooling=False)

        assert "readings_map_539" in manager.readings_map_names
        assert "pxx0A033B" in manager.get_all_registers()
        assert "pxx0A0648" not in manager.get_all_registers()
        assert "pxx0B0264" not in manager.get_all_registers()
        assert "pxx0C0264" not in manager.get_all_registers()
        assert "pxx0A0648" not in manager.get_paired_blocks()

    def test_non_cooling_539_keeps_non_cooling_write_entries(self):
        """Test non-cooling 5.39 keeps shared write entries and removes cooling-only ones."""
        manager = RegisterMapManagerWrite("539", has_cooling=False)

        assert "write_map_539" in manager.write_map_names
        assert "p99PumpRateHC" in manager.get_all_registers()
        assert "p99PumpRateDHW" in manager.get_all_registers()
        assert "p75passiveCooling" not in manager.get_all_registers()
        assert "p99CoolingHC1Switch" not in manager.get_all_registers()
        assert "p99CoolingHC2Switch" not in manager.get_all_registers()

    def test_merge_maps_with_lists(self):
        """Test merging maps with list entries."""
        manager = RegisterMapManager("206")
        
        base = {
            "block1": [("sensor1", 0, 2, "hex"), ("sensor2", 2, 2, "hex")]
        }
        override = {
            "block1": [("sensor2", 2, 2, "hex2int", 10)]  # Override sensor2
        }
        
        result = manager._merge_maps(base, override)
        
        # Should have merged properly
        assert "block1" in result
        assert isinstance(result["block1"], list)

    def test_merge_maps_with_empty_override(self):
        """Test merging with empty override."""
        manager = RegisterMapManager("206")
        
        base = {"block1": [("sensor1", 0, 2, "hex")]}
        override = {}
        
        result = manager._merge_maps(base, override)
        
        # Should return base unchanged
        assert result == base

    def test_merge_maps_with_empty_base(self):
        """Test merging with empty base."""
        manager = RegisterMapManager("206")
        
        base = {}
        override = {"block1": [("sensor1", 0, 2, "hex")]}
        
        result = manager._merge_maps(base, override)
        
        # Should return override
        assert "block1" in result

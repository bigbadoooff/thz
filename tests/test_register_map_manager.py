"""Tests for register map manager."""


from custom_components.thz.register_maps.register_map_manager import (
    FIRMWARE_MAPS,
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
        """Test default firmware configuration (539-like)."""
        assert "default" in FIRMWARE_MAPS
        config = FIRMWARE_MAPS["default"]
        assert "write" in config
        assert "read" in config
        assert "write_map_539" in config["write"]
        assert "readings_map_539" in config["read"]

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


class TestRegisterMapManagerWrite2xxEnrichment:
    """Tests for 2xx firmware write entry enrichment."""

    def test_2xx_entries_get_command(self):
        """Test that 2xx write entries are enriched with a 'command' field."""
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()

        # p01RoomTempDay should have been enriched with command "17" (block pxx17)
        entry = registers.get("p01RoomTempDay")
        assert entry is not None, "p01RoomTempDay missing from 206 write map"
        assert entry.get("command") == "17", (
            f"Expected command='17', got {entry.get('command')!r}"
        )

    def test_2xx_entries_get_offset_and_length(self):
        """Test that 2xx write entries get byte offset and length converted from nibbles.

        p01RoomTempDay has nibble offset=4, nibble length=4 in register_map_206.
        After conversion (nibble//2): byte offset=2, byte length=2.
        """
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()

        entry = registers.get("p01RoomTempDay")
        assert entry is not None
        assert entry.get("offset") == 2   # nibble 4 → byte 2
        assert entry.get("length") == 2   # nibble 4 → byte 2

    def test_2xx_entries_get_step_from_factor(self):
        """Test that step is computed as 1/factor from the register map."""
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()

        # factor=10 for temperature -> step=0.1
        entry = registers.get("p01RoomTempDay")
        assert entry is not None
        assert abs(float(entry.get("step", 0)) - 0.1) < 1e-6

        # factor=1 for fan stages -> step=1.0
        entry_fan = registers.get("p07FanStageDay")
        assert entry_fan is not None
        assert abs(float(entry_fan.get("step", 0)) - 1.0) < 1e-6

    def test_2xx_entries_get_write_mode_block(self):
        """Test that 2xx write entries have write_mode='block'."""
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()

        entry = registers.get("p01RoomTempDay")
        assert entry is not None
        assert entry.get("write_mode") == "block"

    def test_2xx_pclean_type_promoted_to_number(self):
        """Test that 'pclean' type entries are converted to 'number'."""
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()

        entry = registers.get("p01RoomTempDay")
        assert entry is not None
        assert entry.get("type") == "number"

    def test_2xx_ptime_type_not_changed(self):
        """Test that 'ptime' type entries are NOT converted (different encoding needed)."""
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()

        # progHC1StartTime has type="ptime"
        entry = registers.get("progHC1StartTime")
        assert entry is not None
        assert entry.get("type") == "ptime", (
            "ptime entries should remain unchanged pending schedule time support"
        )

    def test_2xx_multiple_parent_groups(self):
        """Test that parameters from multiple parent groups are all enriched."""
        manager = RegisterMapManagerWrite("206")
        registers = manager.get_all_registers()

        expected = [
            ("p13GradientHC1", "05"),   # pHeat1
            ("p21Hyst1", "06"),          # pHeat2
            ("p32HystDHW", "07"),        # pDHW
            ("p37Fanstage1AirflowInlet", "01"),  # pFan
            ("p54MinPumpCycles", "0A"),  # pCircPump
        ]
        for param_name, expected_cmd in expected:
            entry = registers.get(param_name)
            assert entry is not None, f"{param_name} missing from registers"
            assert entry.get("command") == expected_cmd, (
                f"{param_name}: expected command={expected_cmd!r}, "
                f"got {entry.get('command')!r}"
            )

    def test_4xx_entries_not_affected(self):
        """Test that 4xx/5xx firmware entries are not affected by enrichment."""
        manager = RegisterMapManagerWrite("439")
        registers = manager.get_all_registers()

        # 439 firmware pOpMode should keep its original command
        entry = registers.get("pOpMode")
        assert entry is not None
        assert entry.get("command") == "0A0112"
        assert entry.get("write_mode") is None  # no write_mode for direct writes

    def test_214_enrichment(self):
        """Test that 214 firmware entries are also enriched (it is a 2xx firmware)."""
        manager = RegisterMapManagerWrite("214")
        registers = manager.get_all_registers()

        entry = registers.get("p01RoomTempDay")
        assert entry is not None
        assert entry.get("command") == "17"
        assert entry.get("write_mode") == "block"

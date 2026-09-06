"""Tests for paired register blocks (dual-read energy sensors).

Energy sensors in the THZ device use two registers (cmd2 + cmd3) to represent
values that can exceed 16-bit range.  The combined value is computed as:
    combined = cmd3_value * 1000 + cmd2_value

This matches the FHEM THZ module's behaviour for "1clean" type sensors.
"""


from custom_components.thz.register_maps.register_map_manager import RegisterMapManager
from custom_components.thz.register_maps import readings_map_439, readings_map_539


class TestPairedBlocksDefinitions:
    """Test PAIRED_BLOCKS module-level definitions."""

    def test_readings_map_439_has_paired_blocks(self):
        """Test that readings_map_439 defines PAIRED_BLOCKS."""
        assert hasattr(readings_map_439, "PAIRED_BLOCKS")
        assert isinstance(readings_map_439.PAIRED_BLOCKS, dict)
        assert len(readings_map_439.PAIRED_BLOCKS) > 0

    def test_readings_map_539_has_paired_blocks(self):
        """Test that readings_map_539 defines PAIRED_BLOCKS."""
        assert hasattr(readings_map_539, "PAIRED_BLOCKS")
        assert isinstance(readings_map_539.PAIRED_BLOCKS, dict)
        assert len(readings_map_539.PAIRED_BLOCKS) > 0

    def test_cmd3_is_cmd2_plus_one(self):
        """Test that cmd3 register address is always cmd2 + 1."""
        for cmd2_block, cmd3_block in readings_map_439.PAIRED_BLOCKS.items():
            cmd2_hex = cmd2_block.removeprefix("pxx")
            cmd3_hex = cmd3_block.removeprefix("pxx")
            cmd2_int = int(cmd2_hex, 16)
            cmd3_int = int(cmd3_hex, 16)
            assert cmd3_int == cmd2_int + 1, (
                f"cmd3 ({cmd3_block}) should be cmd2 ({cmd2_block}) + 1"
            )

    def test_all_439_energy_sensors_have_paired_blocks(self):
        """Test that all energy sensors in readings_map_439 have paired blocks."""
        energy_blocks = [
            "pxx0A0924",  # sBoostDHWTotal
            "pxx0A0928",  # sBoostHCTotal
            "pxx0A03AE",  # sHeatRecoveredDay
            "pxx0A03B0",  # sHeatRecoveredTotal
            "pxx0A092A",  # sHeatDHWDay
            "pxx0A092C",  # sHeatDHWTotal
            "pxx0A092E",  # sHeatHCDay
            "pxx0A0930",  # sHeatHCTotal
            "pxx0A091A",  # sElectrDHWDay
            "pxx0A091C",  # sElectrDHWTotal
            "pxx0A091E",  # sElectrHCDay
            "pxx0A0920",  # sElectrHCTotal
        ]
        for block in energy_blocks:
            assert block in readings_map_439.PAIRED_BLOCKS, (
                f"Energy block {block} should have a paired cmd3 register"
            )

    def test_party_time_is_not_paired(self):
        """Test that party-time is NOT in paired blocks."""
        assert "pxx0A05D1" not in readings_map_439.PAIRED_BLOCKS

    def test_paired_blocks_reference_valid_format(self):
        """Test that paired blocks have valid pxx hex format."""
        for cmd2, cmd3 in readings_map_439.PAIRED_BLOCKS.items():
            assert cmd2.startswith("pxx"), f"cmd2 {cmd2} must start with pxx"
            assert cmd3.startswith("pxx"), f"cmd3 {cmd3} must start with pxx"
            # Verify hex part is valid
            bytes.fromhex(cmd2.removeprefix("pxx"))
            bytes.fromhex(cmd3.removeprefix("pxx"))


class TestPairedBlocksRegisterLength:
    """Test that paired-block sensors use length 8 (4 bytes) for combined values."""

    def test_energy_sensors_use_length_8(self):
        """Test that energy sensor entries in readings_map_439 have length 8."""
        register_map = readings_map_439.REGISTER_MAP
        for block in readings_map_439.PAIRED_BLOCKS:
            entries = register_map.get(block, [])
            for entry in entries:
                name, length = entry[0], entry[2]
                assert length == 8, (
                    f"Paired sensor {name} in block {block} should have "
                    f"length 8 (4 bytes) for combined value, got {length}"
                )

    def test_non_paired_sensors_keep_original_length(self):
        """Test that non-paired sensors like party-time keep their original length."""
        register_map = readings_map_439.REGISTER_MAP
        party_entries = register_map.get("pxx0A05D1", [])
        assert len(party_entries) == 1
        length = party_entries[0][2]
        assert length == 4, "party-time should keep length 4"

    def test_cool_hc_total_uses_length_8(self):
        """Test that sCoolHCTotal in 539 map uses length 8."""
        register_map = readings_map_539.REGISTER_MAP
        entries = register_map.get("pxx0A0648", [])
        assert len(entries) == 1
        length = entries[0][2]
        assert length == 8, "sCoolHCTotal should have length 8 for combined value"


class TestGetPairedBlocks:
    """Test RegisterMapManager.get_paired_blocks() method."""

    def test_get_paired_blocks_for_439(self):
        """Test that get_paired_blocks returns paired blocks for firmware 439."""
        manager = RegisterMapManager("439")
        paired = manager.get_paired_blocks()
        assert isinstance(paired, dict)
        assert len(paired) > 0
        # Should contain at least the 439 entries
        assert "pxx0A092A" in paired  # sHeatDHWDay
        assert paired["pxx0A092A"] == "pxx0A092B"

    def test_get_paired_blocks_for_539(self):
        """get_paired_blocks includes 539-specific entries for explicit 539 firmware."""
        # Explicit 539 firmware loads both 439 and 539 readings maps
        manager = RegisterMapManager("539")
        paired = manager.get_paired_blocks()
        # Should contain 439 entries
        assert "pxx0A092A" in paired
        # Should also contain 539 entry
        assert "pxx0A0648" in paired  # sCoolHCTotal
        assert paired["pxx0A0648"] == "pxx0A0649"

    def test_get_paired_blocks_empty_for_206(self):
        """Test that get_paired_blocks returns empty for firmware 206."""
        manager = RegisterMapManager("206")
        paired = manager.get_paired_blocks()
        assert isinstance(paired, dict)
        assert len(paired) == 0

    def test_paired_blocks_count_for_439(self):
        """Test expected number of paired blocks for firmware 439."""
        manager = RegisterMapManager("439")
        paired = manager.get_paired_blocks()
        # 12 energy sensors: 4 Day + 4 Total + 2 Boost + 2 Recovered
        assert len(paired) == 12


class TestCombineValues:
    """Test the value combination logic (cmd3 * 1000 + cmd2)."""

    @staticmethod
    def combine(low: int, high: int) -> int:
        """Replicate the FHEM combination formula."""
        return high * 1000 + low

    def test_combine_zero_values(self):
        """Test combining zero values."""
        assert self.combine(0, 0) == 0

    def test_combine_low_only(self):
        """Test when only low value (cmd2) is non-zero."""
        assert self.combine(483, 0) == 483

    def test_combine_high_only(self):
        """Test when only high value (cmd3) is non-zero."""
        assert self.combine(0, 3) == 3000

    def test_combine_typical_day_value(self):
        """Test typical day energy value (e.g. 3483 Wh ≈ 3.5 kWh)."""
        assert self.combine(483, 3) == 3483

    def test_combine_large_total_value(self):
        """Test large total energy value (e.g. 12500 kWh)."""
        assert self.combine(500, 12) == 12500

    def test_combine_max_low_value(self):
        """Test combining with maximum low value (999)."""
        assert self.combine(999, 5) == 5999

    def test_combine_roll_over_boundary(self):
        """Test the exact boundary where low rolls from 999 to 0."""
        # At 5999 Wh: low=999, high=5
        assert self.combine(999, 5) == 5999
        # At 6000 Wh: low=0, high=6
        assert self.combine(0, 6) == 6000

    def test_combined_value_fits_in_4_bytes(self):
        """Test that even large combined values fit in signed 4-byte int."""
        # Max reasonable value: high=32767, low=999
        combined = self.combine(999, 32767)
        # Must fit in signed int32 (-2147483648 to 2147483647)
        packed = combined.to_bytes(4, byteorder="big", signed=True)
        unpacked = int.from_bytes(packed, byteorder="big", signed=True)
        assert unpacked == combined


class TestPayloadConstruction:
    """Test the payload construction for combined values."""

    def test_build_combined_payload(self):
        """Test constructing a payload with a 4-byte combined value."""
        # Simulate a device response: 6 bytes with 2-byte value at offset 4
        original = bytes([0xAA, 0x0A, 0x09, 0x2A, 0x01, 0xE3])
        # low_val at offset 4 = 0x01E3 = 483

        # Simulate cmd3 response with high value = 3
        cmd3_response = bytes([0xBB, 0x0A, 0x09, 0x2B, 0x00, 0x03])
        # high_val at offset 4 = 0x0003 = 3

        low_val = int.from_bytes(original[4:6], byteorder="big", signed=True)
        high_val = int.from_bytes(cmd3_response[4:6], byteorder="big", signed=True)
        combined = high_val * 1000 + low_val  # 3000 + 483 = 3483

        # Build payload with 4-byte combined value at offset 4
        buf = bytearray(max(len(original) + 2, 8))
        buf[: len(original)] = original
        buf[4:8] = combined.to_bytes(4, byteorder="big", signed=True)
        result = bytes(buf)

        assert len(result) >= 8
        # First 4 bytes unchanged (header / command echo)
        assert result[0] == 0xAA
        assert result[1] == 0x0A
        assert result[2] == 0x09
        assert result[3] == 0x2A
        # Bytes 4-7 = combined value (3483 = 0x00000D9B)
        stored = int.from_bytes(result[4:8], byteorder="big", signed=True)
        assert stored == 3483

    def test_sensor_decode_of_combined_payload(self):
        """Test that decode_value correctly decodes a 4-byte combined value."""
        from custom_components.thz.sensor import decode_value

        # 4-byte combined value: 3483 = 0x00000D9B
        raw = (3483).to_bytes(4, byteorder="big", signed=True)
        result = decode_value(raw, "hex2int", factor=1.0)
        assert result == 3483

    def test_sensor_decode_large_combined_value(self):
        """Test decoding a large combined value (12500 kWh)."""
        from custom_components.thz.sensor import decode_value

        raw = (12500).to_bytes(4, byteorder="big", signed=True)
        result = decode_value(raw, "hex2int", factor=1.0)
        assert result == 12500

    def test_byte_length_calculation_for_length_8(self):
        """Test that length 8 in register map yields 4 bytes for sensor."""
        # Replicate the calculation from sensor.py async_setup_entry
        length_hex_chars = 8
        byte_length = (length_hex_chars + 1) // 2
        assert byte_length == 4, "Length 8 should produce 4-byte reads"

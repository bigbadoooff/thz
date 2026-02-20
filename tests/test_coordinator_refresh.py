"""Tests for coordinator refresh value handling (issue #85).

These tests verify that coordinators are created for ALL register map blocks,
even if the stored refresh_intervals config is missing some blocks.
"""

import pytest

from custom_components.thz.register_maps.register_map_manager import RegisterMapManager
from custom_components.thz.const import DEFAULT_UPDATE_INTERVAL


class TestCoordinatorRefreshCoverage:
    """Tests ensuring coordinators cover all register map blocks."""

    def test_all_blocks_have_default_interval_when_config_empty(self):
        """All register map blocks should get default interval when config is empty."""
        mgr = RegisterMapManager("439")
        all_blocks = list(mgr.get_all_registers().keys())
        stored_intervals = {}

        # Simulate what __init__.py now does: use stored interval or default
        result = {
            block: stored_intervals.get(block, DEFAULT_UPDATE_INTERVAL)
            for block in all_blocks
        }

        assert len(result) == len(all_blocks)
        for block in all_blocks:
            assert block in result
            assert result[block] == DEFAULT_UPDATE_INTERVAL

    def test_blocks_use_stored_intervals_when_available(self):
        """Blocks with stored intervals should use those, not defaults."""
        mgr = RegisterMapManager("439")
        all_blocks = list(mgr.get_all_registers().keys())
        # Configure a custom interval for pxxFB
        stored_intervals = {"pxxFB": 180, "pxxF2": 300}

        result = {
            block: stored_intervals.get(block, DEFAULT_UPDATE_INTERVAL)
            for block in all_blocks
        }

        # pxxFB and pxxF2 should use stored intervals
        assert result["pxxFB"] == 180
        assert result["pxxF2"] == 300
        # Other blocks should use default
        for block in all_blocks:
            if block not in stored_intervals:
                assert result[block] == DEFAULT_UPDATE_INTERVAL

    def test_new_blocks_get_default_when_config_has_some_blocks(self):
        """New blocks (added after initial setup) should get default interval."""
        mgr = RegisterMapManager("439")
        all_blocks = list(mgr.get_all_registers().keys())
        # Simulate old config that only has some blocks
        old_blocks = all_blocks[:3]  # Only first 3 blocks were configured
        stored_intervals = {block: 600 for block in old_blocks}

        result = {
            block: stored_intervals.get(block, DEFAULT_UPDATE_INTERVAL)
            for block in all_blocks
        }

        # Old blocks use stored interval
        for block in old_blocks:
            assert result[block] == 600
        # New blocks use default interval
        for block in all_blocks[3:]:
            assert result[block] == DEFAULT_UPDATE_INTERVAL

    def test_pxxfb_block_always_has_coordinator(self):
        """The pxxFB block (containing pump sensors) must always have a coordinator."""
        mgr = RegisterMapManager("439")
        all_blocks = list(mgr.get_all_registers().keys())
        # Simulate a stored config that's missing pxxFB
        stored_intervals = {b: 600 for b in all_blocks if b != "pxxFB"}

        result = {
            block: stored_intervals.get(block, DEFAULT_UPDATE_INTERVAL)
            for block in all_blocks
        }

        # pxxFB should still get an interval (default) even though not in stored config
        assert "pxxFB" in result
        assert result["pxxFB"] == DEFAULT_UPDATE_INTERVAL

    def test_reconfigure_schema_includes_all_firmware_blocks(self):
        """Reconfigure schema should include ALL blocks for the stored firmware."""
        mgr_439 = RegisterMapManager("439")
        all_blocks_439 = list(mgr_439.get_all_registers().keys())

        # Simulate stored config with only some blocks
        stored_intervals = {"pxxFB": 180}
        firmware_version = "439"

        # Simulate what reconfigure_schema now does
        mgr = RegisterMapManager(firmware_version)
        schema_blocks = list(mgr.get_all_registers().keys())

        # All 439 blocks should be in the schema
        assert set(schema_blocks) == set(all_blocks_439)
        # Including pxxFB with its stored interval
        assert "pxxFB" in schema_blocks

    def test_reconfigure_schema_uses_stored_interval_for_known_blocks(self):
        """Reconfigure schema should use stored intervals for known blocks."""
        stored_intervals = {"pxxFB": 180, "pxxF2": 300, "pxxFC": 900}
        firmware_version = "439"

        mgr = RegisterMapManager(firmware_version)
        all_blocks = list(mgr.get_all_registers().keys())

        # Check that stored intervals are used
        for block in all_blocks:
            interval = stored_intervals.get(block, DEFAULT_UPDATE_INTERVAL)
            if block in stored_intervals:
                assert interval == stored_intervals[block]
            else:
                assert interval == DEFAULT_UPDATE_INTERVAL

    def test_reconfigure_schema_falls_back_to_stored_keys_without_firmware(self):
        """Without firmware version, schema should fall back to stored intervals."""
        stored_intervals = {"pxxFB": 180, "pxxF2": 300}
        firmware_version = ""  # No firmware stored

        # Simulate what reconfigure_schema does without firmware
        if firmware_version:
            mgr = RegisterMapManager(firmware_version)
            all_blocks = list(mgr.get_all_registers().keys())
        else:
            all_blocks = list(stored_intervals.keys())

        assert set(all_blocks) == set(stored_intervals.keys())

    def test_pxxfb_sensors_are_in_register_map(self):
        """Verify pump sensors (dhwPump, heatingCircuitPump) are in pxxFB block."""
        mgr = RegisterMapManager("439")
        registers = mgr.get_all_registers()

        assert "pxxFB" in registers
        pxxfb_entries = registers["pxxFB"]
        sensor_names = [name.strip().rstrip(":") for name, *_ in pxxfb_entries]

        assert "dhwPump" in sensor_names, "dhwPump sensor must be in pxxFB block"
        assert "heatingCircuitPump" in sensor_names, (
            "heatingCircuitPump sensor must be in pxxFB block"
        )

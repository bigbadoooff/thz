"""Tests for automatic cooling support detection."""

from unittest.mock import patch

from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManager,
    RegisterMapManagerWrite,
)
from custom_components.thz.thz_device import THZDevice


class TestProbeCoolingSupport:
    """Tests for THZDevice._probe_cooling_support()."""

    def test_no_cooling_all_zero_payload(self):
        """Device without cooling returns zero payload for 0A0648."""
        device = THZDevice(connection="usb", port="/dev/null")
        # Simulate decode_response output: checksum + addr + 0x00 0x00
        mock_response = bytes.fromhex("590a06480000")

        with patch.object(device, "read_block", return_value=mock_response):
            assert device._probe_cooling_support() is False

    def test_cooling_present_nonzero_payload(self):
        """Device with cooling returns non-zero payload for 0A0648."""
        device = THZDevice(connection="usb", port="/dev/null")
        # Simulate a non-zero energy value at bytes 4-5
        mock_response = bytes.fromhex("590a064801f4")  # value 0x01f4 = 500

        with patch.object(device, "read_block", return_value=mock_response):
            assert device._probe_cooling_support() is True

    def test_second_byte_nonzero_is_cooling(self):
        """Non-zero in byte 5 alone also signals cooling present."""
        device = THZDevice(connection="usb", port="/dev/null")
        mock_response = bytes.fromhex("590a06480001")  # only byte 5 non-zero

        with patch.object(device, "read_block", return_value=mock_response):
            assert device._probe_cooling_support() is True

    def test_probe_returns_true_on_runtime_error(self):
        """Probe failure defaults to cooling supported (safe fallback)."""
        device = THZDevice(connection="usb", port="/dev/null")

        with patch.object(
            device, "read_block", side_effect=RuntimeError("timeout")
        ):
            assert device._probe_cooling_support() is True

    def test_probe_returns_true_on_connection_error(self):
        """ConnectionError during probe defaults to cooling supported."""
        device = THZDevice(connection="usb", port="/dev/null")

        with patch.object(
            device, "read_block", side_effect=ConnectionError("disconnected")
        ):
            assert device._probe_cooling_support() is True

    def test_probe_returns_true_on_os_error(self):
        """OSError during probe defaults to cooling supported."""
        device = THZDevice(connection="usb", port="/dev/null")

        with patch.object(device, "read_block", side_effect=OSError("io error")):
            assert device._probe_cooling_support() is True

    def test_short_response_treated_as_cooling(self):
        """Response shorter than 6 bytes is treated as cooling present (safe)."""
        device = THZDevice(connection="usb", port="/dev/null")
        # Only 4 bytes — can't check bytes 4-5
        mock_response = bytes.fromhex("590a0648")

        with patch.object(device, "read_block", return_value=mock_response):
            assert device._probe_cooling_support() is True

    def test_has_cooling_default_is_true(self):
        """has_cooling is True before async_initialize is called."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device.has_cooling is True


class TestRegisterMapManagerHasCooling:
    """Tests for cooling-aware map selection in RegisterMapManager."""

    def test_has_cooling_true_includes_539_read_map(self):
        """Default (has_cooling=True) includes readings_map_539."""
        manager = RegisterMapManager("539", has_cooling=True)
        assert "readings_map_539" in manager.readings_map_names

    def test_has_cooling_false_keeps_539_read_map(self):
        """has_cooling=False keeps readings_map_539 and filters its cooling blocks."""
        manager = RegisterMapManager("539", has_cooling=False)
        assert "readings_map_539" in manager.readings_map_names
        assert "pxx0A0648" not in manager.get_all_registers()

    def test_has_cooling_true_includes_539_write_map(self):
        """Default (has_cooling=True) includes write_map_539."""
        manager = RegisterMapManagerWrite("539", has_cooling=True)
        assert "write_map_539" in manager.write_map_names

    def test_has_cooling_false_keeps_539_write_map(self):
        """has_cooling=False keeps write_map_539 and filters its cooling entries."""
        manager = RegisterMapManagerWrite("539", has_cooling=False)
        assert "write_map_539" in manager.write_map_names
        assert "p99CoolingHC1Switch" not in manager.get_all_registers()

    def test_has_cooling_false_keeps_439_maps(self):
        """Excluding 539 maps does not remove 439 read maps."""
        manager = RegisterMapManager("539", has_cooling=False)
        assert "readings_map_439" in manager.readings_map_names

    def test_has_cooling_false_keeps_439_write_maps(self):
        """Excluding 539 maps does not remove 439_539 shared write maps."""
        manager = RegisterMapManagerWrite("539", has_cooling=False)
        assert "write_map_439_539" in manager.write_map_names

    def test_cooling_exclusion_removes_cool_hc_total_register(self):
        """Register block pxx0A0648 (sCoolHCTotal) absent when has_cooling=False."""
        manager = RegisterMapManager("539", has_cooling=False)
        all_regs = manager.get_all_registers()
        assert "pxx0A0648" not in all_regs

    def test_cooling_exclusion_removes_dew_point_registers(self):
        """Dew point registers absent when has_cooling=False."""
        manager = RegisterMapManager("539", has_cooling=False)
        all_regs = manager.get_all_registers()
        assert "pxx0B0264" not in all_regs
        assert "pxx0C0264" not in all_regs

    def test_cooling_present_includes_cool_hc_total_register(self):
        """Register block pxx0A0648 (sCoolHCTotal) present when has_cooling=True."""
        manager = RegisterMapManager("539", has_cooling=True)
        all_regs = manager.get_all_registers()
        assert "pxx0A0648" in all_regs

    def test_cooling_exclusion_removes_cooling_write_registers(self):
        """Cooling write registers absent when has_cooling=False."""
        manager = RegisterMapManagerWrite("539", has_cooling=False)
        all_regs = manager.get_all_registers()
        assert "p99CoolingHC1Switch" not in all_regs
        assert "p99CoolingHC1SetTemp" not in all_regs

    def test_non_cooling_firmware_unaffected(self):
        """206 firmware maps are not affected by has_cooling flag."""
        manager_with = RegisterMapManager("206", has_cooling=True)
        manager_without = RegisterMapManager("206", has_cooling=False)
        assert (
            manager_with.readings_map_names == manager_without.readings_map_names
        )

    def test_539_firmware_no_cooling_filters_539_entries(self):
        """Explicit 5.39 firmware keeps 5.39 maps but filters cooling entries."""
        manager = RegisterMapManager("539", has_cooling=False)
        assert "readings_map_539" in manager.readings_map_names
        assert "readings_map_439" in manager.readings_map_names
        assert "pxx0A0648" not in manager.get_all_registers()

    def test_default_firmware_no_cooling_stays_439_only(self):
        """Unrecognized firmware (default) is 4.39-like -- no 5.39 entries to filter."""
        manager = RegisterMapManager("unknown_fw", has_cooling=False)
        assert "readings_map_539" not in manager.readings_map_names
        assert "readings_map_439" in manager.readings_map_names
        assert "pxx0A0648" not in manager.get_all_registers()

    def test_select_maps_for_firmware_no_cooling(self):
        """_select_maps_for_firmware still returns the 5.39 maps for explicit 539."""
        manager = RegisterMapManager("206")
        write, read = manager._select_maps_for_firmware("539", has_cooling=False)
        assert "readings_map_539" in read
        assert "write_map_539" in write
        assert "readings_map_439" in read

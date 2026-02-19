"""Tests for diagnostics module with raw blocks extension."""
import pytest
from unittest.mock import MagicMock

from custom_components.thz.const import DOMAIN


class TestDiagnosticsRawBlocks:
    """Tests for diagnostics raw blocks feature."""

    @pytest.mark.asyncio
    async def test_diagnostics_includes_raw_blocks(self):
        """Test that diagnostics output includes raw block hex dumps."""
        from custom_components.thz.diagnostics import async_get_config_entry_diagnostics

        # Create mock hass
        hass = MagicMock()
        
        # Create mock device
        mock_device = MagicMock()
        mock_device.firmware_version = "4.39"
        mock_device.connection_type = "usb"
        mock_device._initialized = True
        mock_device.last_access = "2024-01-01 12:00:00"

        # Create mock coordinators with test data
        coordinator1 = MagicMock()
        coordinator1.data = bytes.fromhex("010a070503")
        coordinator1.last_update_success = True
        coordinator1.last_update_success_time = None
        coordinator1.update_interval = None

        coordinator2 = MagicMock()
        coordinator2.data = bytes.fromhex("ff00123456")
        coordinator2.last_update_success = True
        coordinator2.last_update_success_time = None
        coordinator2.update_interval = None

        coordinators = {
            "pxxFB": coordinator1,
            "pxx0A0176": coordinator2,
        }

        # Create mock config entry
        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.title = "Test THZ"
        config_entry.version = 1
        config_entry.data = {
            "connection_type": "usb",
            "device": "/dev/ttyUSB0",
        }

        # Setup hass.data
        hass.data = {
            DOMAIN: {
                "device": mock_device,
                "test_entry": {
                    "device": mock_device,
                    "coordinators": coordinators,
                },
            }
        }

        # Call diagnostics
        result = await async_get_config_entry_diagnostics(hass, config_entry)

        # Verify raw_blocks is in result
        assert "raw_blocks" in result

        # Verify block data is correct
        raw_blocks = result["raw_blocks"]
        assert "pxxFB" in raw_blocks
        assert raw_blocks["pxxFB"]["hex"] == "010a070503"
        assert raw_blocks["pxxFB"]["length"] == 5

        assert "pxx0A0176" in raw_blocks
        assert raw_blocks["pxx0A0176"]["hex"] == "ff00123456"
        assert raw_blocks["pxx0A0176"]["length"] == 5

    @pytest.mark.asyncio
    async def test_diagnostics_empty_coordinator_data(self):
        """Test diagnostics when coordinator has no data."""
        from custom_components.thz.diagnostics import async_get_config_entry_diagnostics

        hass = MagicMock()
        mock_device = MagicMock()
        mock_device.firmware_version = "4.39"
        mock_device.connection_type = "usb"
        mock_device._initialized = True
        mock_device.last_access = "2024-01-01 12:00:00"

        # Coordinator with None data
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_success = False
        coordinator.last_update_success_time = None
        coordinator.update_interval = None

        coordinators = {"pxxFB": coordinator}

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.title = "Test THZ"
        config_entry.version = 1
        config_entry.data = {"connection_type": "usb", "device": "/dev/ttyUSB0"}

        hass.data = {
            DOMAIN: {
                "device": mock_device,
                "test_entry": {
                    "device": mock_device,
                    "coordinators": coordinators,
                },
            }
        }

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert "raw_blocks" in result
        raw_blocks = result["raw_blocks"]
        assert "pxxFB" in raw_blocks
        assert raw_blocks["pxxFB"]["hex"] is None
        assert raw_blocks["pxxFB"]["length"] == 0

    @pytest.mark.asyncio
    async def test_diagnostics_no_coordinators(self):
        """Test diagnostics when there are no coordinators."""
        from custom_components.thz.diagnostics import async_get_config_entry_diagnostics

        hass = MagicMock()
        mock_device = MagicMock()
        mock_device.firmware_version = "4.39"
        mock_device.connection_type = "usb"
        mock_device._initialized = True
        mock_device.last_access = "2024-01-01 12:00:00"

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.title = "Test THZ"
        config_entry.version = 1
        config_entry.data = {"connection_type": "usb", "device": "/dev/ttyUSB0"}

        hass.data = {
            DOMAIN: {
                "device": mock_device,
                "test_entry": {
                    "device": mock_device,
                    "coordinators": {},
                },
            }
        }

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert "raw_blocks" in result
        assert result["raw_blocks"] == {}

    @pytest.mark.asyncio
    async def test_diagnostics_large_block(self):
        """Test diagnostics with large block of data."""
        from custom_components.thz.diagnostics import async_get_config_entry_diagnostics

        hass = MagicMock()
        mock_device = MagicMock()
        mock_device.firmware_version = "4.39"
        mock_device.connection_type = "usb"
        mock_device._initialized = True
        mock_device.last_access = "2024-01-01 12:00:00"

        # Large data block (100 bytes)
        large_data = bytes(range(100))
        coordinator = MagicMock()
        coordinator.data = large_data
        coordinator.last_update_success = True
        coordinator.last_update_success_time = None
        coordinator.update_interval = None

        coordinators = {"pxxFB": coordinator}

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.title = "Test THZ"
        config_entry.version = 1
        config_entry.data = {"connection_type": "usb", "device": "/dev/ttyUSB0"}

        hass.data = {
            DOMAIN: {
                "device": mock_device,
                "test_entry": {
                    "device": mock_device,
                    "coordinators": coordinators,
                },
            }
        }

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert "raw_blocks" in result
        raw_blocks = result["raw_blocks"]
        assert "pxxFB" in raw_blocks
        assert raw_blocks["pxxFB"]["length"] == 100
        # Verify hex string is correct length (2 chars per byte)
        assert len(raw_blocks["pxxFB"]["hex"]) == 200

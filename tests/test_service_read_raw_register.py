"""Tests for the read_raw_register service."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError


class TestReadRawRegisterService:
    """Tests for read_raw_register service."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.services.async_register = MagicMock()
        hass.services.async_remove = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.async_add_executor_job = AsyncMock()
        return hass

    @pytest.fixture
    def mock_device(self):
        """Create a mock THZ device."""
        device = MagicMock()
        device.lock = asyncio.Lock()
        device.read_block = MagicMock()
        device.async_execute = AsyncMock()
        return device

    @staticmethod
    def _handler_for(mock_hass, service_name: str):
        """Return the registered handler callback for a given service name.

        _async_setup_services registers several services (read_raw_register,
        scan_raw_registers, watch_raw_registers_changes, refresh_block, ...),
        so the desired handler must be looked up by name rather than assumed
        to be the most recent (or only) call.
        """
        for call in mock_hass.services.async_register.call_args_list:
            if call[0][0] == DOMAIN and call[0][1] == service_name:
                return call[0][2]
        raise AssertionError(f"Service '{service_name}' was not registered")

    @pytest.mark.asyncio
    async def test_service_registration(self, mock_hass):
        """Test that service is registered correctly."""
        from custom_components.thz import _async_setup_services

        await _async_setup_services(mock_hass)

        # Verify read_raw_register was registered among the services
        registered = [
            call[0][1] for call in mock_hass.services.async_register.call_args_list
        ]
        assert "read_raw_register" in registered
        for call in mock_hass.services.async_register.call_args_list:
            assert call[0][0] == DOMAIN  # domain

    @pytest.mark.asyncio
    async def test_service_idempotent(self, mock_hass):
        """Test that service registration is idempotent."""
        from custom_components.thz import _async_setup_services

        # First call should register
        await _async_setup_services(mock_hass)
        first_count = mock_hass.services.async_register.call_count
        assert first_count > 0

        # Second call should not register (already exists)
        mock_hass.services.has_service = MagicMock(return_value=True)
        await _async_setup_services(mock_hass)
        assert mock_hass.services.async_register.call_count == first_count  # Unchanged

    @pytest.mark.asyncio
    async def test_read_raw_register_success(self, mock_hass, mock_device):
        """Test successful read of raw register."""
        from custom_components.thz import _async_setup_services

        # Setup device in hass.data (per-entry)
        mock_hass.data[DOMAIN]["test_entry"] = {"device": mock_device}
        test_data = bytes.fromhex("010a070503001234ff")
        mock_device.async_execute = AsyncMock(return_value=test_data)

        # Register service and get handler
        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        # Create service call
        call = MagicMock()
        call.data = {"command": "FB"}

        # Call the handler
        result = await handler(call)

        # Verify result
        assert result["success"] is True
        assert result["command"] == "FB"
        assert result["length"] == len(test_data)
        assert result["hex"] == test_data.hex()
        assert "formatted" in result
        assert "0000:" in result["formatted"]

        # Verify persistent notification was created
        mock_hass.services.async_call.assert_called()
        notification_call = mock_hass.services.async_call.call_args_list[-1]
        assert notification_call[0][0] == "persistent_notification"
        assert notification_call[0][1] == "create"

    @pytest.mark.asyncio
    async def test_read_raw_register_invalid_hex(self, mock_hass, mock_device):
        """Test read with invalid hex command."""
        from custom_components.thz import _async_setup_services

        mock_hass.data[DOMAIN]["test_entry"] = {"device": mock_device}

        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        call = MagicMock()
        call.data = {"command": "INVALID"}

        with pytest.raises(ServiceValidationError, match="INVALID"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_read_raw_register_no_device(self, mock_hass):
        """Test read when device is not initialized."""
        from custom_components.thz import _async_setup_services

        # No device in hass.data
        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        call = MagicMock()
        call.data = {"command": "FB"}

        with pytest.raises(HomeAssistantError, match="not initialized"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_read_raw_register_multiple_entries_no_entry_id(
        self, mock_hass, mock_device
    ):
        """Test error when multiple entries exist and entry_id is not supplied."""
        from custom_components.thz import _async_setup_services

        # Two config entries present
        mock_hass.data[DOMAIN]["entry_a"] = {"device": mock_device}
        mock_hass.data[DOMAIN]["entry_b"] = {"device": mock_device}

        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        call = MagicMock()
        call.data = {"command": "FB"}

        with pytest.raises(ServiceValidationError) as exc_info:
            await handler(call)
        err = str(exc_info.value).lower()
        assert "entry_id" in err or "multiple" in err

    @pytest.mark.asyncio
    async def test_read_raw_register_multiple_entries_with_entry_id(
        self, mock_hass, mock_device
    ):
        """Test success when multiple entries exist and correct entry_id is given."""
        from custom_components.thz import _async_setup_services

        test_data = bytes.fromhex("010a070503001234ff")
        mock_device.async_execute = AsyncMock(return_value=test_data)

        mock_hass.data[DOMAIN]["entry_a"] = {"device": mock_device}
        mock_hass.data[DOMAIN]["entry_b"] = {"device": mock_device}

        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        call = MagicMock()
        call.data = {"command": "FB", "entry_id": "entry_a"}

        result = await handler(call)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_read_raw_register_multiple_entries_unknown_entry_id(
        self, mock_hass, mock_device
    ):
        """Test error when entry_id does not match any loaded entry."""
        from custom_components.thz import _async_setup_services

        mock_hass.data[DOMAIN]["entry_a"] = {"device": mock_device}

        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        call = MagicMock()
        call.data = {"command": "FB", "entry_id": "nonexistent"}

        with pytest.raises(ServiceValidationError, match="nonexistent"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_read_raw_register_device_error(self, mock_hass, mock_device):
        """Test read when device raises an error."""
        from custom_components.thz import _async_setup_services

        mock_hass.data[DOMAIN]["test_entry"] = {"device": mock_device}

        # Mock read_block to raise an error
        mock_device.async_execute = AsyncMock(
            side_effect=RuntimeError("Communication error")
        )

        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        call = MagicMock()
        call.data = {"command": "FB"}

        with pytest.raises(HomeAssistantError, match="Communication error"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_formatted_hex_output(self, mock_hass, mock_device):
        """Test that formatted hex output is correct."""
        from custom_components.thz import _async_setup_services

        mock_hass.data[DOMAIN]["test_entry"] = {"device": mock_device}

        # Create test data with more than 16 bytes to test multi-line formatting
        test_data = bytes(range(32))
        mock_device.async_execute = AsyncMock(return_value=test_data)

        await _async_setup_services(mock_hass)
        handler = self._handler_for(mock_hass, "read_raw_register")

        call = MagicMock()
        call.data = {"command": "0A0176"}

        result = await handler(call)

        assert result["success"] is True
        formatted = result["formatted"]

        # Check that we have multiple lines
        lines = formatted.split("\n")
        assert len(lines) == 2  # 32 bytes = 2 lines of 16 bytes each

        # Check first line format
        assert lines[0].startswith("  0000:")
        # Check second line format
        assert lines[1].startswith("  0010:")

    @pytest.mark.asyncio
    async def test_service_cleanup_on_unload(self, mock_hass):
        """Test that service is removed when last entry is unloaded."""
        from custom_components.thz import async_unload_entry

        # Create mock config entry
        entry = MagicMock()
        entry.entry_id = "test_entry"

        # Setup hass.data
        mock_hass.data[DOMAIN] = {
            "test_entry": {
                "device": MagicMock(close=MagicMock()),
            }
        }

        # Mock config_entries.async_entries to return no remaining entries
        mock_hass.config_entries = MagicMock()
        mock_hass.config_entries.async_entries = MagicMock(return_value=[])
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        # Unload entry
        result = await async_unload_entry(mock_hass, entry)

        assert result is True
        # Verify all registered services (including read_raw_register) were removed
        removed = [
            call.args[1] for call in mock_hass.services.async_remove.call_args_list
        ]
        assert "read_raw_register" in removed
        for call in mock_hass.services.async_remove.call_args_list:
            assert call.args[0] == DOMAIN

    @pytest.mark.asyncio
    async def test_service_not_removed_with_remaining_entries(self, mock_hass):
        """Test that service is not removed when there are remaining entries."""
        from custom_components.thz import async_unload_entry

        entry = MagicMock()
        entry.entry_id = "test_entry"

        mock_hass.data[DOMAIN] = {
            "test_entry": {
                "device": MagicMock(close=MagicMock()),
            }
        }

        # Mock config_entries.async_entries to return remaining entry
        other_entry = MagicMock()
        other_entry.entry_id = "other_entry"
        mock_hass.config_entries = MagicMock()
        mock_hass.config_entries.async_entries = MagicMock(
            return_value=[entry, other_entry]
        )
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        # Unload entry
        result = await async_unload_entry(mock_hass, entry)

        assert result is True
        # Verify service was NOT removed (still have other entries)
        mock_hass.services.async_remove.assert_not_called()

    def test_hex_command_validation(self):
        """Test that various hex command formats are accepted."""
        valid_commands = ["FB", "fb", "F2", "0A0176", "FC", "FD", "FE"]

        for cmd in valid_commands:
            try:
                bytes.fromhex(cmd)
            except ValueError:
                pytest.fail(f"Valid command '{cmd}' failed validation")

    def test_hex_command_invalid(self):
        """Test that invalid hex commands are rejected."""
        invalid_commands = ["ZZ", "GG", "Hello", "0x123"]

        for cmd in invalid_commands:
            with pytest.raises(ValueError):
                bytes.fromhex(cmd)

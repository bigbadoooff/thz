"""Tests for _async_update_block()'s handling of unsupported registers.

Regression coverage for a bug where a device's clean "register not
supported" response (THZRegisterNotSupportedError) was turned into a hard
UpdateFailed instead of being treated as "no data for this block" — which
crashed the whole config entry's first refresh (shown to the user as
"Failed setup, will retry: Error reading <block>: Failed to decode device
response") instead of just skipping that one unsupported block, as the
caller in async_setup_entry already expects
(``if coordinator.data is None: unsupported_blocks.add(block)``).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.thz_device import THZRegisterNotSupportedError


class TestAsyncUpdateBlock:
    """Tests for _async_update_block()."""

    @pytest.fixture
    def mock_device(self):
        """Create a mock THZ device with a real lock."""
        device = MagicMock()
        device.lock = asyncio.Lock()
        return device

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_unsupported_register_returns_none(self, mock_hass, mock_device):
        """A clean "not supported" response must not raise UpdateFailed."""
        from custom_components.thz import _async_update_block

        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=THZRegisterNotSupportedError("not supported")
        )

        result = await _async_update_block(mock_hass, mock_device, "pxx0A033B")

        assert result is None

    @pytest.mark.asyncio
    async def test_genuine_decode_failure_raises_update_failed(
        self, mock_hass, mock_device
    ):
        """A real decode/comms failure must still surface as UpdateFailed."""
        from custom_components.thz import _async_update_block
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=RuntimeError("Failed to decode device response")
        )

        with pytest.raises(UpdateFailed):
            await _async_update_block(mock_hass, mock_device, "pxx0A033B")

    @pytest.mark.asyncio
    async def test_successful_read_returns_result(self, mock_hass, mock_device):
        """A normal successful read still returns the raw block bytes."""
        from custom_components.thz import _async_update_block

        test_data = bytes.fromhex("010a070503001234ff")
        mock_hass.async_add_executor_job = AsyncMock(return_value=test_data)

        result = await _async_update_block(mock_hass, mock_device, "pxxFB")

        assert result == test_data

"""Additional coverage tests for diagnostics.py.

Complements tests/test_diagnostics_raw_blocks.py by exercising the
register_manager / write_manager branches, coordinator timestamp/interval
formatting, and missing entry_data / device defaults.
"""
from unittest.mock import MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)


def _make_config_entry(entry_id="test_entry", data=None):
    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    config_entry.title = "Test THZ"
    config_entry.version = 1
    config_entry.data = data or {"connection_type": "usb", "device": "/dev/ttyUSB0"}
    return config_entry


class TestDiagnosticsRegisterCounts:
    """Tests for the register_manager / write_manager sections."""

    @pytest.mark.asyncio
    async def test_includes_register_manager_counts(self):
        register_manager = MagicMock()
        register_manager.get_all_registers.return_value = {
            "pxxFB": [{"name": "a"}, {"name": "b"}],
            "pxxF2": [{"name": "c"}],
        }

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device": MagicMock(),
                    "coordinators": {},
                    "register_manager": register_manager,
                }
            }
        }
        config_entry = _make_config_entry()

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert result["registers"]["read_blocks"] == 2
        assert result["registers"]["read_sensors"] == 3

    @pytest.mark.asyncio
    async def test_includes_write_manager_counts_and_types(self):
        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "p01": {"type": "number"},
            "p02": {"type": "number"},
            "pSwitch": {"type": "switch"},
            "pSelect": {"type": "select"},
            "pUnknownTypeEntry": {},  # missing "type" -> "unknown"
        }

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device": MagicMock(),
                    "coordinators": {},
                    "write_manager": write_manager,
                }
            }
        }
        config_entry = _make_config_entry()

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert result["registers"]["write_entities"] == 5
        type_counts = result["registers"]["write_entity_types"]
        assert type_counts["number"] == 2
        assert type_counts["switch"] == 1
        assert type_counts["select"] == 1
        assert type_counts["unknown"] == 1

    @pytest.mark.asyncio
    async def test_no_register_manager_or_write_manager(self):
        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device": MagicMock(),
                    "coordinators": {},
                }
            }
        }
        config_entry = _make_config_entry()

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert result["registers"] == {}


class TestDiagnosticsCoordinatorInfo:
    """Tests for coordinator timestamp / update_interval formatting."""

    @pytest.mark.asyncio
    async def test_coordinator_with_last_update_time_and_interval(self):
        from datetime import timedelta

        coordinator = MagicMock()
        coordinator.data = bytes.fromhex("0102")
        coordinator.last_update_success = True
        coordinator.last_update_success_time = "2024-01-01T00:00:00"
        coordinator.update_interval = timedelta(seconds=600)

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device": MagicMock(),
                    "coordinators": {"pxxFB": coordinator},
                }
            }
        }
        config_entry = _make_config_entry()

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        coord_info = result["coordinators"]["pxxFB"]
        assert coord_info["last_update_time"] == "2024-01-01T00:00:00"
        assert coord_info["update_interval"] == str(timedelta(seconds=600))
        assert coord_info["data_length"] == 2

    @pytest.mark.asyncio
    async def test_coordinator_without_time_or_interval(self):
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_success = False
        coordinator.last_update_success_time = None
        coordinator.update_interval = None

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device": MagicMock(),
                    "coordinators": {"pxxFB": coordinator},
                }
            }
        }
        config_entry = _make_config_entry()

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        coord_info = result["coordinators"]["pxxFB"]
        assert coord_info["last_update_time"] is None
        assert coord_info["update_interval"] is None
        assert coord_info["data_length"] == 0


class TestDiagnosticsMissingEntryData:
    """Tests for defaults when entry_data / device are missing entirely."""

    @pytest.mark.asyncio
    async def test_missing_entry_data_uses_defaults(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        config_entry = _make_config_entry(entry_id="missing_entry")

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert result["device"]["firmware_version"] == "unknown"
        assert result["device"]["connection_type"] == "unknown"
        assert result["device"]["initialized"] is False
        assert result["device"]["last_access"] == "never"
        assert result["coordinators"] == {}
        assert result["registers"] == {}
        assert result["raw_blocks"] == {}

    @pytest.mark.asyncio
    async def test_missing_domain_data_uses_defaults(self):
        hass = MagicMock()
        hass.data = {}
        config_entry = _make_config_entry(entry_id="missing_entry")

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert result["device"]["firmware_version"] == "unknown"

    @pytest.mark.asyncio
    async def test_redact_keys_used_for_config_data(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        config_entry = _make_config_entry(
            data={"host": "10.0.0.5", "device": "/dev/ttyUSB0", "other": "value"}
        )

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        # conftest's async_redact_data mock is a passthrough, but verify
        # TO_REDACT contains the expected sensitive keys.
        assert TO_REDACT == {"host", "device", "unique_id", "serial"}
        assert result["config_entry"]["data"]["other"] == "value"

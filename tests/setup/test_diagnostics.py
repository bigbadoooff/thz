"""More tests for diagnostics.py.

Complements tests/setup/test_diagnostics_raw_blocks.py by exercising the
register_manager / write_manager branches, coordinator timestamp/interval
formatting, and missing entry_data / device defaults.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.thz.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)


def _make_config_entry(entry_id="test_entry", data=None, runtime_data=None):
    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    config_entry.title = "Test THZ"
    config_entry.version = 1
    config_entry.data = data or {"connection_type": "usb", "device": "/dev/ttyUSB0"}
    config_entry.runtime_data = {} if runtime_data is None else runtime_data
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
        config_entry = _make_config_entry(
            runtime_data={
                "device": MagicMock(),
                "coordinators": {},
                "register_manager": register_manager,
            }
        )

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
        config_entry = _make_config_entry(
            runtime_data={
                "device": MagicMock(),
                "coordinators": {},
                "write_manager": write_manager,
            }
        )

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
        config_entry = _make_config_entry(
            runtime_data={
                "device": MagicMock(),
                "coordinators": {},
            }
        )

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
        config_entry = _make_config_entry(
            runtime_data={
                "device": MagicMock(),
                "coordinators": {"pxxFB": coordinator},
            }
        )

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
        config_entry = _make_config_entry(
            runtime_data={
                "device": MagicMock(),
                "coordinators": {"pxxFB": coordinator},
            }
        )

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
        config_entry = _make_config_entry(entry_id="missing_entry")

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert result["device"]["firmware_version"] == "unknown"
        assert result["device"]["connection_type"] == "unknown"
        assert result["device"]["initialized"] is False
        assert result["coordinators"] == {}
        assert result["registers"] == {}
        assert result["raw_blocks"] == {}

    @pytest.mark.asyncio
    async def test_none_runtime_data_uses_defaults(self):
        hass = MagicMock()
        config_entry = _make_config_entry(entry_id="missing_entry")
        config_entry.runtime_data = None  # simulate an entry never fully set up

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert result["device"]["firmware_version"] == "unknown"

    @pytest.mark.asyncio
    async def test_redact_keys_used_for_config_data(self):
        hass = MagicMock()
        config_entry = _make_config_entry(
            data={
                "host": "10.0.0.5",
                "device": "/dev/ttyUSB0",
                "alias": "Keller",
                "area": "Basement",
                "other": "value",
            }
        )
        config_entry.title = "THZ (ip: 10.0.0.5)"

        result = await async_get_config_entry_diagnostics(hass, config_entry)

        assert {"host", "device", "unique_id", "serial"} <= TO_REDACT
        data = result["config_entry"]["data"]
        for key in ("host", "device", "alias", "area"):
            assert data[key] == "**REDACTED**"
        assert data["other"] == "value"
        # The title embeds the host as well.
        assert "10.0.0.5" not in str(result)

    @pytest.mark.asyncio
    async def test_reports_real_device_attributes(self):
        from custom_components.thz.thz_device import THZDevice

        device = THZDevice(connection="ip", host="h", tcp_port=1)
        hass = MagicMock()
        config_entry = _make_config_entry(runtime_data={"device": device})

        # Firmware still unknown: must not raise from the firmware_version
        # property.
        result = await async_get_config_entry_diagnostics(hass, config_entry)
        assert result["device"]["firmware_version"] == "unknown"
        assert result["device"]["connection_type"] == "ip"

        device._firmware_version = "439"
        result = await async_get_config_entry_diagnostics(hass, config_entry)
        assert result["device"]["firmware_version"] == "439"

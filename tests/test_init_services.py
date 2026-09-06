"""Coverage tests for the service handlers registered by async_setup_services.

read_raw_register is already covered by test_service_read_raw_register.py.
This file covers scan_raw_registers, watch_raw_registers_changes,
refresh_block, and set_diverter_valve. backup_parameters, restore_parameters,
and list_parameter_backups are covered by test_backup_restore_services.py.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.services import async_setup_services
from custom_components.thz.const import DOMAIN
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError


def _mock_hass():
    """Build a mock hass whose config_entries.async_entries() reflects hass.data.

    Production code resolves per-entry state via config_entry.runtime_data
    (looked up through hass.config_entries.async_entries(DOMAIN)) rather than
    hass.data. Tests still populate hass.data[DOMAIN]["entry_id"] = {...} as a
    convenient fixture shape; this adapter turns those entries into fake
    ConfigEntry mocks with a matching .runtime_data on each lookup.
    """
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.async_add_executor_job = AsyncMock()
    hass.config = MagicMock()
    hass.config.config_dir = "/config"

    def _fake_async_entries(domain):
        entries = []
        for entry_id, runtime_data in hass.data.get(domain, {}).items():
            entry = MagicMock()
            entry.entry_id = entry_id
            entry.runtime_data = runtime_data
            entries.append(entry)
        return entries

    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(side_effect=_fake_async_entries)
    return hass


def _handler_for(hass, service_name: str):
    for call in hass.services.async_register.call_args_list:
        if call[0][0] == DOMAIN and call[0][1] == service_name:
            return call[0][2]
    raise AssertionError(f"Service '{service_name}' was not registered")


def _mock_device():
    device = MagicMock()
    device.async_execute = AsyncMock()
    return device


class TestServiceRegistration:
    @pytest.mark.asyncio
    async def test_all_services_registered(self):
        hass = _mock_hass()
        await async_setup_services(hass)

        registered = {
            call[0][1] for call in hass.services.async_register.call_args_list
        }
        assert registered == {
            "read_raw_register",
            "scan_raw_registers",
            "watch_raw_registers_changes",
            "refresh_block",
            "set_diverter_valve",
            "backup_parameters",
            "restore_parameters",
            "list_parameter_backups",
        }

    @pytest.mark.asyncio
    async def test_skips_registration_if_service_exists(self):
        hass = _mock_hass()
        hass.services.has_service = MagicMock(return_value=True)
        await async_setup_services(hass)
        hass.services.async_register.assert_not_called()


class TestScanRawRegisters:
    @pytest.mark.asyncio
    async def test_max_results_must_be_positive(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {"pattern": "0A017X", "max_results": 0}
        with pytest.raises(ServiceValidationError, match="max_results"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_requires_pattern_xor_range(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {}
        with pytest.raises(ServiceValidationError, match="pattern"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_invalid_pattern_returns_error(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {"pattern": "ZZZZZZ"}
        with pytest.raises(ServiceValidationError):
            await handler(call)

    @pytest.mark.asyncio
    async def test_no_device_returns_error(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {"pattern": "0A0176"}
        with pytest.raises(HomeAssistantError, match="not initialized"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_successful_scan_with_pattern(self):
        hass = _mock_hass()
        device = _mock_device()
        device.async_execute = AsyncMock(return_value=bytes.fromhex("0100" + "1234"))
        hass.data[DOMAIN]["entry1"] = {"device": device}

        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {"pattern": "0A0176", "decode_values": True}
        result = await handler(call)

        assert result["success"] is True
        assert result["summary"]["scanned"] == 1
        assert result["summary"]["success_count"] == 1
        assert result["results"][0]["success"] is True
        assert "decoded" in result["results"][0]
        hass.services.async_call.assert_awaited()

    @pytest.mark.asyncio
    async def test_scan_with_range_and_errors_included(self):
        hass = _mock_hass()
        device = _mock_device()
        device.async_execute = AsyncMock(side_effect=RuntimeError("boom"))
        hass.data[DOMAIN]["entry1"] = {"device": device}

        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {
            "start": "0A0000",
            "end": "0A0001",
            "include_errors": True,
            "max_results": 1,
        }
        result = await handler(call)

        assert result["success"] is True
        assert result["summary"]["error_count"] == 1
        assert result["results"][0]["success"] is False

    @pytest.mark.asyncio
    async def test_multiple_entries_without_entry_id_errors(self):
        hass = _mock_hass()
        hass.data[DOMAIN]["entry1"] = {"device": _mock_device()}
        hass.data[DOMAIN]["entry2"] = {"device": _mock_device()}

        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {"pattern": "0A0176"}
        with pytest.raises(ServiceValidationError, match="Multiple"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_unknown_entry_id_errors(self):
        hass = _mock_hass()
        hass.data[DOMAIN]["entry1"] = {"device": _mock_device()}

        await async_setup_services(hass)
        handler = _handler_for(hass, "scan_raw_registers")

        call = MagicMock()
        call.data = {"pattern": "0A0176", "entry_id": "nope"}
        with pytest.raises(ServiceValidationError, match="nope"):
            await handler(call)


class TestWatchRawRegistersChanges:
    @pytest.mark.asyncio
    async def test_duration_must_be_at_least_one(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "watch_raw_registers_changes")

        call = MagicMock()
        call.data = {"pattern": "0A0176", "duration_seconds": 0}
        with pytest.raises(ServiceValidationError, match="duration_seconds"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_interval_must_be_non_negative(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "watch_raw_registers_changes")

        call = MagicMock()
        call.data = {
            "pattern": "0A0176",
            "duration_seconds": 1,
            "interval_seconds": -1,
        }
        with pytest.raises(ServiceValidationError, match="interval_seconds"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_no_device_returns_error(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "watch_raw_registers_changes")

        call = MagicMock()
        call.data = {"pattern": "0A0176", "duration_seconds": 1}
        with pytest.raises(HomeAssistantError, match="not initialized"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_detects_a_change_across_iterations(self):
        hass = _mock_hass()
        device = _mock_device()
        # First read (pre-scan validation) then repeated reads inside the
        # watch loop: return a changed value on the second read onward.
        device.async_execute = AsyncMock(
            side_effect=[
                bytes.fromhex("01000000"),
                bytes.fromhex("01000001"),
                bytes.fromhex("01000001"),
                bytes.fromhex("01000001"),
            ]
        )
        hass.data[DOMAIN]["entry1"] = {"device": device}

        await async_setup_services(hass)
        handler = _handler_for(hass, "watch_raw_registers_changes")

        call = MagicMock()
        call.data = {
            "pattern": "0A0176",
            "duration_seconds": 1,
            "interval_seconds": 0,
        }
        result = await handler(call)

        assert result["success"] is True
        assert result["summary"]["valid_count"] == 1
        assert result["summary"]["changes_detected"] >= 1


class TestRefreshBlockService:
    @pytest.mark.asyncio
    async def test_missing_block_param_errors(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "refresh_block")

        call = MagicMock()
        call.data = {"block": ""}
        with pytest.raises(ServiceValidationError, match="required"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_found_returns_success(self):
        hass = _mock_hass()
        coordinator = MagicMock()
        coordinator.async_request_refresh = AsyncMock()
        hass.data[DOMAIN]["entry1"] = {"coordinators": {"pxxFB": coordinator}}

        await async_setup_services(hass)
        handler = _handler_for(hass, "refresh_block")

        call = MagicMock()
        call.data = {"block": "FB"}
        result = await handler(call)

        assert result["success"] is True
        assert result["block"] == "pxxFB"

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        hass = _mock_hass()
        hass.data[DOMAIN]["entry1"] = {"coordinators": {}}

        await async_setup_services(hass)
        handler = _handler_for(hass, "refresh_block")

        call = MagicMock()
        call.data = {"block": "FB"}
        with pytest.raises(ServiceValidationError, match="pxxFB"):
            await handler(call)


class TestSetDiverterValveService:
    @staticmethod
    def _coordinator(data: bytes):
        coord = MagicMock()
        coord.data = data
        return coord

    @pytest.mark.asyncio
    async def test_no_entries_returns_error(self):
        hass = _mock_hass()
        await async_setup_services(hass)
        handler = _handler_for(hass, "set_diverter_valve")

        call = MagicMock()
        call.data = {"position": "off"}
        with pytest.raises(HomeAssistantError, match="not initialized"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_multiple_entries_without_entry_id_errors(self):
        hass = _mock_hass()
        hass.data[DOMAIN]["entry1"] = {"device": _mock_device(), "coordinators": {}}
        hass.data[DOMAIN]["entry2"] = {"device": _mock_device(), "coordinators": {}}

        await async_setup_services(hass)
        handler = _handler_for(hass, "set_diverter_valve")

        call = MagicMock()
        call.data = {"position": "off"}
        with pytest.raises(ServiceValidationError, match="Multiple"):
            await handler(call)

    @pytest.mark.asyncio
    async def test_off_position_stops_and_confirms(self):
        hass = _mock_hass()
        device = _mock_device()
        # _stop_and_verify reads heating then dhw motor state; both report OFF.
        device.async_execute = AsyncMock(
            side_effect=[
                None,  # write heating off
                None,  # write dhw off
                bytes.fromhex("0000"),  # read heating state
                bytes.fromhex("0000"),  # read dhw state
            ]
        )
        hass.data[DOMAIN]["entry1"] = {"device": device, "coordinators": {}}

        await async_setup_services(hass)
        handler = _handler_for(hass, "set_diverter_valve")

        call = MagicMock()
        call.data = {"position": "off"}
        result = await handler(call)

        assert result["success"] is True
        assert result["position"] == "off"

    @pytest.mark.asyncio
    async def test_dhw_refused_when_heating_active(self):
        hass = _mock_hass()
        device = _mock_device()
        # diverterValve bit clear (byte index 5, bit 3) -> heating circuit active
        cooling_coord = self._coordinator(bytes(12))
        hass.data[DOMAIN]["entry1"] = {
            "device": device,
            "coordinators": {"pxxF2": cooling_coord},
        }

        await async_setup_services(hass)
        handler = _handler_for(hass, "set_diverter_valve")

        call = MagicMock()
        call.data = {"position": "dhw"}
        with pytest.raises(HomeAssistantError, match="refused"):
            await handler(call)
        device.async_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_device_error_during_move_returns_error(self):
        hass = _mock_hass()
        device = _mock_device()
        device.async_execute = AsyncMock(side_effect=ConnectionError("lost"))
        hass.data[DOMAIN]["entry1"] = {"device": device, "coordinators": {}}

        await async_setup_services(hass)
        handler = _handler_for(hass, "set_diverter_valve")

        call = MagicMock()
        call.data = {"position": "off"}
        with pytest.raises(
            HomeAssistantError, match="Error sending diverter valve command"
        ):
            await handler(call)


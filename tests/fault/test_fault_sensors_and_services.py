"""Fault-memory sensors and the probe/acknowledge/clear services."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.thz import fault_sensor
from custom_components.thz.const import DOMAIN
from custom_components.thz.fault_sensor import (
    NO_FAULT,
    THZFaultMemorySensor,
    THZFaultStatusSensor,
    THZLatestFaultSensor,
    THZNewFaultsSensor,
    async_setup_fault_sensors,
    supports_fault_memory,
)
from custom_components.thz.fault_state import THZFaultTracker
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManager,
)
from custom_components.thz.services import async_setup_services
from tests.fault.test_fault_memory import R3, R5, R11, FakeStore, _payload


def _tracker():
    return THZFaultTracker(FakeStore())


def _coordinator(payload):
    coordinator = MagicMock()
    coordinator.data = payload
    coordinator.async_add_listener = MagicMock(return_value=MagicMock())
    return coordinator


class TestSupportsFaultMemory:
    @pytest.mark.parametrize("fw", ["419", "439", "509", "539", "709"])
    def test_one_byte_layout_firmware_is_supported(self, fw):
        assert supports_fault_memory(RegisterMapManager(fw))

    @pytest.mark.parametrize("fw", ["206", "214", "214j"])
    def test_2xx_layout_is_not_supported(self, fw):
        assert not supports_fault_memory(RegisterMapManager(fw))


class TestSensors:
    def _sensors(self, payload):
        coordinator = _coordinator(payload)
        tracker = _tracker()
        args = (coordinator, tracker, "dev")
        return (
            coordinator,
            tracker,
            [
                THZFaultStatusSensor(*args),
                THZFaultMemorySensor(*args),
                THZLatestFaultSensor(*args),
                THZNewFaultsSensor(*args),
            ],
        )

    def test_ids_and_translation_keys(self):
        _, _, sensors = self._sensors(_payload())
        assert [s._attr_unique_id for s in sensors] == [
            "thz_dev_fault_status",
            "thz_dev_fault_memory",
            "thz_dev_fault_latest",
            "thz_dev_fault_new",
        ]
        assert [s._attr_translation_key for s in sensors] == [
            "fault_status",
            "fault_memory",
            "fault_latest",
            "fault_new",
        ]

    def test_device_info_links_to_the_device(self):
        _, _, (status, *_) = self._sensors(_payload())
        assert status.device_info == {"identifiers": {(DOMAIN, "dev")}}

    def test_empty_memory(self):
        _, _, (status, memory, latest, new) = self._sensors(_payload())
        assert status.native_value == "ok"
        assert memory.native_value == 0
        assert latest.native_value == NO_FAULT
        assert latest.extra_state_attributes == {}
        assert new.native_value == 0

    def test_existing_history_is_not_an_alarm_on_first_read(self):
        _, _, (status, memory, latest, new) = self._sensors(_payload(R3, R5))
        assert status.native_value == "ok"
        assert memory.native_value == 2
        assert latest.native_value == "F05_OutletFanFault"
        assert latest.extra_state_attributes["fault_code"] == "F05"
        assert latest.extra_state_attributes["time"] == "23:59"
        assert new.native_value == 0
        assert memory.extra_state_attributes["entries"][0]["fault_number"] == 5

    def test_a_new_fault_raises_the_status_and_lists_the_record(self):
        coordinator, _, (status, _, latest, new) = self._sensors(_payload(R3))
        assert status.native_value == "ok"  # baseline
        coordinator.data = _payload(R3, R11)
        assert status.native_value == "fault"
        assert new.native_value == 1
        assert new.extra_state_attributes["entries"][0]["fault_number"] == 11
        assert status.extra_state_attributes["latest_new"]["fault_number"] == 11
        assert latest.extra_state_attributes["acknowledged"] is False

    def test_unavailable_when_the_payload_is_unusable(self):
        _, _, sensors = self._sensors(b"\x00")
        assert [s.native_value for s in sensors] == [None] * 4


def _entry(coordinators, register_manager):
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    config_entry.runtime_data = {
        "coordinators": coordinators,
        "register_manager": register_manager,
        "device_id": "dev",
    }
    return config_entry


class TestSetup:
    @pytest.mark.asyncio
    async def test_creates_four_sensors_and_exposes_tracker(self):
        coordinator = _coordinator(_payload(R3))
        config_entry = _entry({"pxxD1": coordinator}, RegisterMapManager("439"))
        add = MagicMock()
        with patch.object(fault_sensor, "Store", return_value=FakeStore()):
            await async_setup_fault_sensors(MagicMock(), config_entry, add)

        (entities,), _ = add.call_args
        assert len(entities) == 4
        data = config_entry.runtime_data
        assert isinstance(data["fault_tracker"], THZFaultTracker)
        assert data["fault_source"] is coordinator
        coordinator.async_add_listener.assert_called_once()
        config_entry.async_on_unload.assert_called_once()

    @pytest.mark.asyncio
    async def test_baseline_is_persisted_on_first_setup(self):
        store = FakeStore()
        config_entry = _entry(
            {"pxxD1": _coordinator(_payload(R3))}, RegisterMapManager("439")
        )
        with patch.object(fault_sensor, "Store", return_value=store):
            await async_setup_fault_sensors(MagicMock(), config_entry, MagicMock())
        assert store.saved[0]["acknowledged_records"] == [R3.hex().upper()]

    @pytest.mark.asyncio
    async def test_nothing_without_the_d1_block(self):
        add = MagicMock()
        config_entry = _entry({}, RegisterMapManager("439"))
        await async_setup_fault_sensors(MagicMock(), config_entry, add)
        add.assert_not_called()
        assert "fault_tracker" not in config_entry.runtime_data

    @pytest.mark.asyncio
    async def test_nothing_on_an_unsupported_layout(self):
        add = MagicMock()
        config_entry = _entry(
            {"pxxD1": _coordinator(_payload())}, RegisterMapManager("206")
        )
        await async_setup_fault_sensors(MagicMock(), config_entry, add)
        add.assert_not_called()

    @pytest.mark.asyncio
    async def test_listener_updates_the_tracker_and_persists_changes(self):
        store = FakeStore()
        coordinator = _coordinator(_payload(R3))
        config_entry = _entry({"pxxD1": coordinator}, RegisterMapManager("439"))
        hass = MagicMock()
        hass.async_create_task = MagicMock(side_effect=lambda coro: coro.close())
        with patch.object(fault_sensor, "Store", return_value=store):
            await async_setup_fault_sensors(hass, config_entry, MagicMock())
        listener = coordinator.async_add_listener.call_args[0][0]
        tracker = config_entry.runtime_data["fault_tracker"]

        coordinator.data = _payload(R3, R5)
        listener()
        assert tracker.state["new_count"] == 1
        hass.async_create_task.assert_not_called()  # nothing to persist yet

        coordinator.data = _payload()  # device-side clear -> baseline changes
        listener()
        hass.async_create_task.assert_called_once()


def _hass_with(entry_data):
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.runtime_data = entry_data
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    return hass


async def _handler(hass, name):
    async_setup_services(hass)
    for call in hass.services.async_register.call_args_list:
        if call[0][1] == name:
            return call[0][2]
    raise AssertionError(name)


def _call(**data):
    call = MagicMock()
    call.data = data
    return call


def _device(firmware="419"):
    device = MagicMock()
    device.async_execute = AsyncMock(return_value=_payload(R3))
    return device


class TestProbeService:
    @pytest.mark.asyncio
    async def test_returns_decoded_memory(self):
        hass = _hass_with({"device": _device()})
        handler = await _handler(hass, "probe_fault_memory")
        result = await handler(_call())
        assert result["success"] is True
        assert result["decoded"]["fault_count_reported"] == 1

    @pytest.mark.asyncio
    async def test_communication_error_becomes_homeassistant_error(self):
        device = _device()
        device.async_execute = AsyncMock(side_effect=OSError("boom"))
        handler = await _handler(_hass_with({"device": device}), "probe_fault_memory")
        with pytest.raises(HomeAssistantError, match="Could not read"):
            await handler(_call())

    @pytest.mark.asyncio
    async def test_unsupported_register_is_reported(self):
        from custom_components.thz.thz_device import THZRegisterNotSupportedError

        device = _device()
        device.async_execute = AsyncMock(side_effect=THZRegisterNotSupportedError("x"))
        handler = await _handler(_hass_with({"device": device}), "probe_fault_memory")
        with pytest.raises(HomeAssistantError, match="not supported"):
            await handler(_call())


class TestAcknowledgeService:
    @pytest.mark.asyncio
    async def test_acknowledges_and_persists(self):
        store = FakeStore()
        tracker = THZFaultTracker(store)
        tracker.process(_payload(R3))
        tracker.process(_payload(R3, R5))
        source = MagicMock()
        source.async_request_refresh = AsyncMock()
        hass = _hass_with(
            {"device": _device(), "fault_tracker": tracker, "fault_source": source}
        )
        handler = await _handler(hass, "acknowledge_faults")
        result = await handler(_call())
        assert result == {"success": True, "acknowledged": 1}
        source.async_request_refresh.assert_awaited_once()
        source.async_update_listeners.assert_called_once()
        assert store.saved  # persisted

    @pytest.mark.asyncio
    async def test_unavailable_without_fault_tracking(self):
        handler = await _handler(
            _hass_with({"device": _device()}), "acknowledge_faults"
        )
        with pytest.raises(ServiceValidationError, match="not available"):
            await handler(_call())

    @pytest.mark.asyncio
    async def test_no_data_yet_is_an_error(self):
        source = MagicMock()
        source.async_request_refresh = AsyncMock()
        hass = _hass_with(
            {"device": _device(), "fault_tracker": _tracker(), "fault_source": source}
        )
        handler = await _handler(hass, "acknowledge_faults")
        with pytest.raises(HomeAssistantError, match="No fault data"):
            await handler(_call())


class TestClearService:
    @pytest.mark.asyncio
    async def test_wrong_phrase_is_rejected_before_touching_the_device(self):
        device = _device()
        handler = await _handler(_hass_with({"device": device}), "clear_fault_memory")
        with pytest.raises(ServiceValidationError, match="CLEAR D1"):
            await handler(_call(confirmation="clear d1"))
        device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("firmware", ["419", "439", "539", "509"])
    async def test_available_on_every_firmware(self, firmware):
        hass = _hass_with({"device": _device(firmware=firmware)})
        handler = await _handler(hass, "clear_fault_memory")
        with patch(
            "custom_components.thz.services.faults.clear_fault_memory",
            AsyncMock(
                return_value={"cleared": True, "before_count": 1, "after_count": 0}
            ),
        ) as clear:
            result = await handler(_call(confirmation="CLEAR D1"))
        clear.assert_awaited_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_success_refreshes_the_source_coordinator(self):
        source = MagicMock()
        source.async_request_refresh = AsyncMock()
        hass = _hass_with({"device": _device(), "fault_source": source})
        handler = await _handler(hass, "clear_fault_memory")
        with patch(
            "custom_components.thz.services.faults.clear_fault_memory",
            AsyncMock(
                return_value={"cleared": True, "before_count": 2, "after_count": 0}
            ),
        ) as clear:
            result = await handler(_call(confirmation="CLEAR D1"))
        clear.assert_awaited_once()
        assert result == {
            "success": True,
            "cleared": True,
            "before_count": 2,
            "after_count": 0,
        }
        source.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clear_failure_becomes_homeassistant_error(self):
        hass = _hass_with({"device": _device()})
        handler = await _handler(hass, "clear_fault_memory")
        with (
            patch(
                "custom_components.thz.services.faults.clear_fault_memory",
                AsyncMock(side_effect=RuntimeError("D1 still reports 1 fault(s)")),
            ),
            pytest.raises(HomeAssistantError, match="still reports"),
        ):
            await handler(_call(confirmation="CLEAR D1"))


class TestTranslationsAndIcons:
    _KEYS = ("fault_status", "fault_memory", "fault_latest", "fault_new")

    @pytest.mark.parametrize(
        "path", ["strings.json", "translations/en.json", "translations/de.json"]
    )
    def test_every_sensor_has_a_name(self, path):
        import json
        import pathlib

        base = pathlib.Path(__file__).resolve().parents[2] / "custom_components"
        with open(base / "thz" / path, encoding="utf-8") as fh:
            sensors = json.load(fh)["entity"]["sensor"]
        for key in self._KEYS:
            assert sensors[key]["name"], key
        assert set(sensors["fault_status"]["state"]) == {"ok", "fault"}

    def test_every_sensor_has_an_icon(self):
        import json
        import pathlib

        base = pathlib.Path(__file__).resolve().parents[2] / "custom_components"
        with open(base / "thz" / "icons.json", encoding="utf-8") as fh:
            icons = json.load(fh)["entity"]["sensor"]
        for key in self._KEYS:
            assert icons[key]["default"].startswith("mdi:"), key

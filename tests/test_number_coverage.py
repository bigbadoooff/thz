"""Coverage tests for number.py (THZNumber entity and async_setup_entry)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.number import THZNumber, async_setup_entry


def _make_device():
    device = MagicMock()
    device.lock = asyncio.Lock()
    device.write_value = MagicMock()
    device.async_execute = AsyncMock()
    return device


def _number_entry(command="0A0800", decode_type="hex2int", step=0.5):
    return {
        "command": command,
        "type": "number",
        "icon": "mdi:thermometer",
        "min": 0,
        "max": 100,
        "step": step,
        "unit": "°C",
        "device_class": "temperature",
        "decode_type": decode_type,
    }


def _make_entity(name="p01RoomTempDayHC1", entry=None, device=None):
    entity = THZNumber(
        name=name,
        entry=entry if entry is not None else _number_entry(),
        device=device or _make_device(),
        device_id="dev1",
    )
    entity.name = name
    return entity


class TestAsyncSetupEntry:
    """Tests for number.py's async_setup_entry via async_setup_write_platform."""

    @pytest.mark.asyncio
    async def test_creates_number_entities(self):
        write_manager = MagicMock()
        write_manager.get_all_registers.return_value = {
            "p01RoomTempDayHC1": _number_entry("0A0801"),
            "pSwitchOne": {"command": "0A0802", "type": "switch"},
        }

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "entry1": {
                    "write_manager": write_manager,
                    "device": _make_device(),
                    "device_id": "dev1",
                }
            }
        }
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.data = {}

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities, update_before_add = async_add_entities.call_args[0]
        assert len(entities) == 1
        assert isinstance(entities[0], THZNumber)
        assert update_before_add is True


class TestTHZNumberInit:
    """Tests for THZNumber initialization."""

    def test_init_defaults(self):
        entity = _make_entity()
        assert entity._attr_native_min_value == 0.0
        assert entity._attr_native_max_value == 100.0
        assert entity._attr_native_step == 0.5
        assert entity._attr_native_unit_of_measurement == "°C"
        assert entity.native_value is None

    def test_init_empty_min_max_step_use_defaults(self):
        entry = _number_entry()
        entry["min"] = ""
        entry["max"] = ""
        entry["step"] = ""
        entity = _make_entity(entry=entry)
        assert entity._attr_native_min_value == 0.0
        assert entity._attr_native_max_value == 100.0
        assert entity._attr_native_step == 1.0

    def test_init_step_defaults_when_missing_key(self):
        entry = _number_entry()
        del entry["step"]
        entity = _make_entity(entry=entry)
        assert entity._attr_native_step == 1.0


class TestTHZNumberUpdate:
    """Tests for THZNumber.async_update."""

    @pytest.mark.asyncio
    async def test_async_update_standard_decode(self):
        entity = _make_entity(entry=_number_entry(decode_type="hex2int", step=0.5))
        entity.hass = MagicMock()
        # value 40 (signed big-endian) * step 0.5 = 20.0
        entity._device.async_execute = AsyncMock(
            return_value=(40).to_bytes(2, "big", signed=True)
        )

        await entity.async_update()

        assert entity.native_value == 20.0

    @pytest.mark.asyncio
    async def test_async_update_0clean_decode(self):
        entity = _make_entity(entry=_number_entry(decode_type="0clean"))
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=bytes([7]))

        await entity.async_update()

        assert entity.native_value == 7.0

    @pytest.mark.asyncio
    async def test_async_update_no_data_keeps_previous(self):
        entity = _make_entity()
        entity._attr_native_value = 5.0
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=b"")

        await entity.async_update()

        assert entity.native_value == 5.0

    @pytest.mark.asyncio
    async def test_async_update_decode_error_keeps_previous(self, monkeypatch):
        entity = _make_entity()
        entity._attr_native_value = 5.0
        entity.hass = MagicMock()
        entity._device.async_execute = AsyncMock(return_value=bytes([1, 2]))

        from custom_components.thz import number as number_mod

        def _raise(*_args, **_kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(number_mod.THZValueCodec, "decode_number", _raise)

        await entity.async_update()

        assert entity.native_value == 5.0


class TestTHZNumberAvailability:
    """Tests for THZNumber availability tracking on connectivity errors."""

    @pytest.mark.asyncio
    async def test_becomes_unavailable_on_connection_error(self):
        entity = _make_entity()
        entity.hass = MagicMock()
        assert entity.available is True
        entity._device.async_execute = AsyncMock(side_effect=ConnectionError("lost"))

        await entity.async_update()

        assert entity.available is False
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_becomes_available_again_after_recovery(self):
        entity = _make_entity(entry=_number_entry(decode_type="hex2int", step=0.5))
        entity.hass = MagicMock()
        entity._attr_available = False
        entity._device.async_execute = AsyncMock(
            return_value=(40).to_bytes(2, "big", signed=True)
        )

        await entity.async_update()

        assert entity.available is True
        assert entity.native_value == 20.0


class TestTHZNumberSetNativeValue:
    """Tests for THZNumber.async_set_native_value."""

    @pytest.mark.asyncio
    async def test_async_set_native_value_success(self):
        device = _make_device()
        entity = _make_entity(
            entry=_number_entry(decode_type="hex2int", step=0.5), device=device
        )
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(20.0)

        assert entity.native_value == 20.0
        entity.async_write_ha_state.assert_called_once()
        write_call = device.async_execute.call_args[0]
        assert write_call[1] == device.write_value
        assert write_call[3] == (40).to_bytes(2, "big", signed=True)

    @pytest.mark.asyncio
    async def test_async_set_native_value_0clean(self):
        device = _make_device()
        entity = _make_entity(entry=_number_entry(decode_type="0clean"), device=device)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(3.0)

        write_call = device.async_execute.call_args[0]
        assert write_call[3] == bytes([3])

    @pytest.mark.asyncio
    async def test_async_set_native_value_encode_error_logged_not_raised(
        self, monkeypatch
    ):
        entity = _make_entity()
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        from custom_components.thz import number as number_mod

        def _raise(*_args, **_kwargs):
            raise TypeError("boom")

        monkeypatch.setattr(number_mod.THZValueCodec, "encode_number", _raise)

        await entity.async_set_native_value(10.0)

        entity._device.async_execute.assert_not_awaited()
        entity.async_write_ha_state.assert_not_called()

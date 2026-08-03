"""Coverage-focused tests for custom_components/thz/sensor.py.

Exercises async_setup_entry's entity-creation loop (block skipping, bit-type
skipping, duplicate-name skipping, metadata pass-through) as well as the
THZGenericSensor entity properties under varied coordinator-data states.
"""
from unittest.mock import MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.sensor import (
    THZGenericSensor,
    async_setup_entry,
    decode_value,
)


class FakeRegisterManager:
    """Minimal stand-in for RegisterMapManager exposing get_all_registers()."""

    def __init__(self, registers: dict):
        self._registers = registers

    def get_all_registers(self) -> dict:
        return self._registers


def _make_hass_and_entry(registers, coordinators, unsupported_blocks=None,
                          device_id="dev1", firmware_version="2.06"):
    """Build a (hass, config_entry) pair with entry_data for both platforms.

    Populates entry_data for sensor.async_setup_entry and the cop_sensor
    setup it delegates to.
    """
    device = MagicMock()
    device.firmware_version = firmware_version

    hass = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    config_entry.runtime_data = {
        "register_manager": FakeRegisterManager(registers),
        "coordinators": coordinators,
        "device_id": device_id,
        "device": device,
        "unsupported_blocks": unsupported_blocks or set(),
    }
    return hass, config_entry


class TestDecodeValue:
    """Tests for the decode_value backward-compatible wrapper."""

    def test_decode_hex2int(self):
        raw = (100).to_bytes(2, byteorder="big", signed=True)
        assert decode_value(raw, "hex2int", 10) == 10.0

    def test_decode_hex(self):
        raw = (50).to_bytes(2, byteorder="big")
        assert decode_value(raw, "hex", 1) == 50

    def test_decode_bit(self):
        assert decode_value(bytes([0x04]), "bit2", 1) is True

    def test_decode_unknown_returns_hex(self):
        assert decode_value(bytes([0xAB]), "unknown_type") == "ab"


class TestAsyncSetupEntry:
    """Tests for the async_setup_entry entity-creation loop."""

    @pytest.mark.asyncio
    async def test_creates_sensors_and_skips_bit_types(self):
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {
            "pxxFB": [
                ("outsideTemp", 0, 4, "hex2int", 10),
                ("compressor", 8, 1, "bit3", 1),  # skipped: handled by binary_sensor
                ("filterAlarm", 10, 1, "nbit1", 1),  # skipped
            ]
        }
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        sensors, should_refresh = async_add_entities.call_args[0]
        assert should_refresh is True
        assert len(sensors) == 1
        assert sensors[0]._entity_name == "outsideTemp"

    @pytest.mark.asyncio
    async def test_skips_block_without_coordinator(self):
        registers = {
            "pxxFB": [("outsideTemp", 0, 4, "hex2int", 10)],
            "pxxNoCoord": [("someValue", 0, 4, "hex2int", 1)],
        }
        hass, config_entry = _make_hass_and_entry(
            registers, {"pxxFB": MagicMock(data=bytes(20))}
        )
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        sensors, _ = async_add_entities.call_args[0]
        assert len(sensors) == 1
        assert sensors[0]._entity_name == "outsideTemp"

    @pytest.mark.asyncio
    async def test_skips_unsupported_block(self):
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {
            "pxxFB": [("outsideTemp", 0, 4, "hex2int", 10)],
            "pxxUnsupported": [("someValue", 0, 4, "hex2int", 1)],
        }
        hass, config_entry = _make_hass_and_entry(
            registers,
            {"pxxFB": coord, "pxxUnsupported": coord},
            unsupported_blocks={"pxxUnsupported"},
        )
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        sensors, _ = async_add_entities.call_args[0]
        assert len(sensors) == 1
        assert sensors[0]._entity_name == "outsideTemp"

    @pytest.mark.asyncio
    async def test_skips_duplicate_sensor_names(self):
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {
            "pxxFB": [
                ("outsideTemp", 0, 4, "hex2int", 10),
                ("outsideTemp", 4, 4, "hex2int", 10),
            ]
        }
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        sensors, _ = async_add_entities.call_args[0]
        assert len(sensors) == 1

    @pytest.mark.asyncio
    async def test_strips_whitespace_and_colon_from_name(self):
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {"pxxFB": [("  outsideTemp: ", 0, 4, "hex2int", 10)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        sensors, _ = async_add_entities.call_args[0]
        assert sensors[0]._entity_name == "outsideTemp"

    @pytest.mark.asyncio
    async def test_metadata_dict_passed_through(self):
        coord = MagicMock()
        coord.data = bytes(20)
        meta = {
            "unit": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
            "icon": "mdi:thermometer",
            "translation_key": "outside_temp",
        }
        registers = {"pxxFB": [("outsideTemp", 0, 4, "hex2int", 10, meta)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        sensors, _ = async_add_entities.call_args[0]
        sensor = sensors[0]
        assert sensor.native_unit_of_measurement == "°C"
        assert sensor.device_class == "temperature"
        assert sensor.state_class == "measurement"
        # translation_key is set -> icon comes from icons.json instead of
        # the hardcoded "icon" metadata field.
        assert sensor.icon is None
        assert sensor._attr_translation_key == "outside_temp"

    @pytest.mark.asyncio
    async def test_non_bit_entry_at_even_offset_length_one(self):
        # Exercises the nibble-offset-adjustment branch's "if" without
        # taking either bit/nbit inner branch (decode is not bit-prefixed).
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {"pxxFB": [("weekdayNow", 0, 1, "weekday", 1)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        sensors, _ = async_add_entities.call_args[0]
        assert len(sensors) == 1
        assert sensors[0]._decode_type == "weekday"

    @pytest.mark.asyncio
    async def test_delegates_to_cop_sensor_setup(self):
        # Firmware below 439 => cop sensor setup returns early without
        # calling async_add_entities a second time.
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {"pxxFB": [("outsideTemp", 0, 4, "hex2int", 10)]}
        hass, config_entry = _make_hass_and_entry(
            registers, {"pxxFB": coord}, firmware_version="2.06"
        )
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        # Called exactly once: the cop sensor setup found nothing to add.
        assert async_add_entities.call_count == 1


class TestTHZGenericSensor:
    """Tests for THZGenericSensor entity properties."""

    @staticmethod
    def _make_entry(**overrides):
        entry = {
            "name": "outsideTemp",
            "offset": 0,
            "length": 4,
            "decode": "hex2int",
            "factor": 10,
            "unit": "°C",
            "device_class": "temperature",
            "state_class": "measurement",
            "icon": "mdi:thermometer",
            "translation_key": None,
        }
        entry.update(overrides)
        return entry

    def test_init_with_translation_key_sets_no_attr_name(self):
        coord = MagicMock()
        coord.data = None
        entry = self._make_entry(translation_key="outside_temp")
        sensor = THZGenericSensor(
            coord, entry=entry, block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor._attr_translation_key == "outside_temp"
        assert sensor._attr_has_entity_name is True
        assert not hasattr(sensor, "_attr_name")

    def test_init_without_translation_key_sets_attr_name(self):
        coord = MagicMock()
        coord.data = None
        entry = self._make_entry(translation_key=None)
        sensor = THZGenericSensor(
            coord, entry=entry, block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor._attr_name == "outsideTemp"

    def test_advanced_sensor_gets_diagnostic_category(self):
        from homeassistant.const import EntityCategory

        coord = MagicMock()
        coord.data = None
        entry = self._make_entry(name="p13GradientHC1")
        sensor = THZGenericSensor(
            coord, entry=entry, block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_normal_sensor_has_no_entity_category(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert getattr(sensor, "_attr_entity_category", None) is None

    def test_native_value_none_when_no_data(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.native_value is None

    def test_native_value_none_when_payload_too_short(self):
        coord = MagicMock()
        coord.data = bytes(2)
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.native_value is None

    def test_native_value_success(self):
        coord = MagicMock()
        coord.data = (250).to_bytes(4, byteorder="big", signed=True)
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.native_value == 25.0

    def test_native_value_handles_decode_error(self):
        coord = MagicMock()
        coord.data = bytes(4)
        # length=0 -> raw_bytes empty -> bit0 decode raises IndexError internally.
        entry = self._make_entry(decode="bit0", length=0)
        sensor = THZGenericSensor(
            coord, entry=entry, block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.native_value is None

    def test_native_unit_of_measurement(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.native_unit_of_measurement == "°C"

    def test_device_class(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.device_class == "temperature"

    def test_state_class(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.state_class == "measurement"

    def test_icon(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor.icon == "mdi:thermometer"

    def test_unique_id(self):
        # THZGenericSensor.unique_id embeds the block's Python bytes repr
        # (not its hex string) — this is established/documented behavior,
        # see tests/test_sensor_naming.py::TestSensorUniqueIdExtraction.
        coord = MagicMock()
        coord.data = None
        entry = self._make_entry(name="Outside Temp")
        block = bytes.fromhex("FB")
        sensor = THZGenericSensor(
            coord, entry=entry, block=block, device_id="dev1"
        )
        assert sensor.unique_id == f"thz_{block}_0_outside_temp"
        assert sensor.unique_id.endswith("_0_outside_temp")

    def test_extra_state_attributes(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"), device_id="dev1"
        )
        attrs = sensor.extra_state_attributes
        assert attrs["register_block"] == "pxxFB"
        assert attrs["register_offset"] == 0
        assert attrs["register_length"] == 4
        assert attrs["register_decode_type"] == "hex2int"
        assert attrs["register_factor"] == 10

    def test_device_info(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZGenericSensor(
            coord, entry=self._make_entry(), block=bytes.fromhex("FB"),
            device_id="my_device",
        )
        info = sensor.device_info
        assert (DOMAIN, "my_device") in info["identifiers"]

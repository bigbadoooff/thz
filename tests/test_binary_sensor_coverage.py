"""Coverage-focused tests for custom_components/thz/binary_sensor.py.

Exercises async_setup_entry's entity-creation loop (block skipping,
non-bit skipping, duplicate-name skipping, nibble-offset adjustment) as
well as additional THZBinarySensor property paths not already covered by
tests/test_entity_platforms.py.
"""
from unittest.mock import MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.binary_sensor import THZBinarySensor, async_setup_entry


class FakeRegisterManager:
    """Minimal stand-in for RegisterMapManager exposing get_all_registers()."""

    def __init__(self, registers: dict):
        self._registers = registers

    def get_all_registers(self) -> dict:
        return self._registers


def _make_hass_and_entry(registers, coordinators, device_id="dev1"):
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry1": {
                "register_manager": FakeRegisterManager(registers),
                "coordinators": coordinators,
                "device_id": device_id,
            }
        }
    }
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    return hass, config_entry


class TestAsyncSetupEntry:
    """Tests for the binary_sensor async_setup_entry entity-creation loop."""

    @pytest.mark.asyncio
    async def test_creates_only_bit_decoded_entries(self):
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {
            "pxxFB": [
                ("outsideTemp", 0, 4, "hex2int", 10),  # skipped: not bit-decoded
                ("compressor", 8, 1, "bit3", 1),
                ("filterAlarm", 10, 1, "nbit1", 1),
            ]
        }
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities, should_refresh = async_add_entities.call_args[0]
        assert should_refresh is True
        assert len(entities) == 2
        names = {e._entity_name for e in entities}
        assert names == {"compressor", "filterAlarm"}

    @pytest.mark.asyncio
    async def test_skips_block_without_coordinator(self):
        registers = {
            "pxxFB": [("compressor", 8, 1, "bit3", 1)],
            "pxxNoCoord": [("pump", 8, 1, "bit1", 1)],
        }
        hass, config_entry = _make_hass_and_entry(
            registers, {"pxxFB": MagicMock(data=bytes(20))}
        )
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        assert len(entities) == 1
        assert entities[0]._entity_name == "compressor"

    @pytest.mark.asyncio
    async def test_skips_duplicate_sensor_names(self):
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {
            "pxxFB": [
                ("compressor", 8, 1, "bit3", 1),
                ("compressor", 9, 1, "bit1", 1),
            ]
        }
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        assert len(entities) == 1

    @pytest.mark.asyncio
    async def test_strips_whitespace_and_colon_from_name(self):
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {"pxxFB": [("  compressor: ", 8, 1, "bit3", 1)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        assert entities[0]._entity_name == "compressor"

    @pytest.mark.asyncio
    async def test_metadata_dict_passed_through(self):
        coord = MagicMock()
        coord.data = bytes(20)
        meta = {"icon": "mdi:engine", "translation_key": "compressor"}
        registers = {"pxxFB": [("compressor", 8, 1, "bit3", 1, meta)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        entity = entities[0]
        assert entity.icon == "mdi:engine"
        assert entity._attr_translation_key == "compressor"

    @pytest.mark.asyncio
    async def test_nibble_offset_adjustment_bit_even_offset(self):
        # offset=0 (even), length=1, decode="bit3" -> effective "bit7"
        # Byte 0x80 has bit7 set (high nibble bit3), bit3 clear.
        coord = MagicMock()
        coord.data = bytes([0x80]) + bytes(19)
        registers = {"pxxFB": [("compressor", 0, 1, "bit3", 1)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        entity = entities[0]
        assert entity._decode_type == "bit7"
        assert entity.is_on is True

    @pytest.mark.asyncio
    async def test_nibble_offset_adjustment_nbit_even_offset(self):
        # offset=0 (even), length=1, decode="nbit1" -> effective "nbit5"
        coord = MagicMock()
        coord.data = bytes([0x00]) + bytes(19)
        registers = {"pxxFB": [("filterAlarm", 0, 1, "nbit1", 1)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        entity = entities[0]
        assert entity._decode_type == "nbit5"
        # bit5 is 0 in 0x00, nbit inverts -> True
        assert entity.is_on is True

    @pytest.mark.asyncio
    async def test_odd_offset_bit_not_adjusted(self):
        # offset=1 (odd) -> no adjustment, decode stays "bit2"
        coord = MagicMock()
        coord.data = bytes(20)
        registers = {"pxxFB": [("pump", 1, 1, "bit2", 1)]}
        hass, config_entry = _make_hass_and_entry(registers, {"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        assert entities[0]._decode_type == "bit2"


class TestTHZBinarySensorAdditional:
    """Additional THZBinarySensor property/behavior tests not already covered
    by tests/test_entity_platforms.py::TestBinarySensorModule.
    """

    def test_init_without_translation_key_sets_attr_name(self):
        coord = MagicMock()
        coord.data = None
        entity = THZBinarySensor(
            coord,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="dev1",
        )
        assert entity._attr_name == "compressor"
        assert not hasattr(entity, "_attr_translation_key")

    def test_init_with_translation_key_sets_has_entity_name(self):
        coord = MagicMock()
        coord.data = None
        entity = THZBinarySensor(
            coord,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": "compressor",
            },
            block=bytes.fromhex("FB"),
            device_id="dev1",
        )
        assert entity._attr_translation_key == "compressor"
        assert entity._attr_has_entity_name is True

    def test_is_on_payload_too_short_returns_none(self):
        coord = MagicMock()
        coord.data = bytes(0)
        entity = THZBinarySensor(
            coord,
            entry={
                "name": "compressor",
                "offset": 5,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="dev1",
        )
        assert entity.is_on is None

    def test_is_on_handles_decode_error(self, monkeypatch):
        import custom_components.thz.binary_sensor as bs_mod

        coord = MagicMock()
        coord.data = bytes([0x01])
        entity = THZBinarySensor(
            coord,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="dev1",
        )

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(bs_mod, "decode_raw_value", _raise)
        assert entity.is_on is None

    def test_extra_state_attributes(self):
        coord = MagicMock()
        coord.data = None
        entity = THZBinarySensor(
            coord,
            entry={
                "name": "compressor",
                "offset": 3,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="dev1",
        )
        attrs = entity.extra_state_attributes
        assert attrs["register_block"] == "pxxFB"
        assert attrs["register_offset"] == 3
        assert attrs["register_length"] == 1
        assert attrs["register_decode_type"] == "bit3"

    def test_icon_property(self):
        coord = MagicMock()
        coord.data = None
        entity = THZBinarySensor(
            coord,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": "mdi:engine",
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="dev1",
        )
        assert entity.icon == "mdi:engine"

    def test_device_class_for_service_entity(self):
        coord = MagicMock()
        coord.data = None
        entity = THZBinarySensor(
            coord,
            entry={
                "name": "serviceFlag",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="dev1",
        )
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert entity._attr_device_class == BinarySensorDeviceClass.PROBLEM

    def test_device_class_for_heating(self):
        from custom_components.thz.binary_sensor import _get_device_class
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert _get_device_class("heatingActive") == BinarySensorDeviceClass.HEAT

    def test_device_class_for_cooling_defrost(self):
        from custom_components.thz.binary_sensor import _get_device_class
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert _get_device_class("coolingMode") == BinarySensorDeviceClass.COLD
        assert _get_device_class("defrostActive") == BinarySensorDeviceClass.COLD

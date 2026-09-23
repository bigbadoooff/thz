"""Tests for register_maps/model.py: nibble positions to bytes and bits."""

import pytest

from custom_components.thz.register_maps.model import ReadField, normalize_field_name
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManager,
)


def _field(offset, length, decode="hex", factor=1, meta=None):
    entry = ("name:", offset, length, decode, factor)
    if meta is not None:
        entry = (*entry, meta)
    return ReadField.from_tuple("pxxFB", entry)


@pytest.mark.parametrize(
    ("offset", "length", "byte_offset", "byte_length"),
    [(8, 4, 4, 2), (8, 8, 4, 4), (9, 1, 4, 1), (8, 2, 4, 1), (8, 1, 4, 1)],
)
def test_byte_position(offset, length, byte_offset, byte_length):
    read_field = _field(offset, length)
    assert (read_field.byte_offset, read_field.byte_length) == (
        byte_offset,
        byte_length,
    )


def test_single_nibble_half():
    assert _field(8, 1).nibble == "high"
    assert _field(9, 1).nibble == "low"
    assert _field(8, 2).nibble is None


@pytest.mark.parametrize(
    ("offset", "decode", "bit", "byte_decode"),
    [
        (9, "bit2", 2, "bit2"),  # low nibble: bits as in the map
        (8, "bit2", 6, "bit6"),  # high nibble: four bits up
        (8, "nbit1", 5, "nbit5"),
        (8, "hex", None, "hex"),
    ],
)
def test_bit_in_the_byte(offset, decode, bit, byte_decode):
    read_field = _field(offset, 1, decode)
    assert read_field.bit == bit
    assert read_field.is_bit is (bit is not None)
    assert read_field.byte_decode_type == byte_decode


def test_decode_types_that_only_look_like_flags():
    assert not _field(8, 1, "bitmap").is_bit
    assert not _field(8, 1, "nbit").is_bit


def test_factor_and_meta():
    read_field = _field(8, 4, "hex2int", 10, {"translation_key": "outside_temp"})
    assert read_field.factor == 10
    assert isinstance(read_field.factor, int)
    assert read_field.scale == 10.0
    assert read_field.translation_key == "outside_temp"
    assert _field(8, 4, factor=0).scale == 1.0
    assert _field(8, 4).translation_key is None
    assert _field(8, 4).meta == {}


def test_names_are_normalized():
    assert normalize_field_name(" switchingProg: ") == "switchingProg"
    assert ReadField.from_tuple("pxxFB", (" a : ", 8, 2, "hex", 1)).name == "a"


def test_manager_finds_fields_by_block_and_name():
    manager = RegisterMapManager("439")
    read_field = manager.find_field("pxx0A0176", "compressor:")
    assert read_field is not None
    assert (read_field.byte_offset, read_field.bit) == (5, 1)
    assert manager.find_field("pxx0A0176", "nonexistent") is None
    assert manager.find_field("pxxNONE", "compressor") is None
    assert manager.block_fields("pxxNONE") == []
    assert set(manager.fields()) == set(manager.get_all_registers())

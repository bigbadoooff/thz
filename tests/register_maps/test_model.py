"""Tests for register_maps/model.py: nibble positions to bytes and bits."""

import pytest

from custom_components.thz.register_maps.model import (
    BlockLayout,
    ReadField,
    WriteParam,
    normalize_field_name,
)
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManager,
    RegisterMapManagerWrite,
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


def test_fields_are_hashable_and_read_only():
    read_field = _field(8, 4, meta={"unit": "°C"})
    same = _field(8, 4, meta={"unit": "°C"})
    assert read_field == same
    assert {read_field, same} == {read_field}
    with pytest.raises(TypeError):
        read_field.meta["unit"] = "K"  # type: ignore[index]


# ---------------------------------------------------------------------------
# WriteParam
# ---------------------------------------------------------------------------


def _write_entry(**fields):
    entry = {"command": "0B0005", "type": "number", "decode_type": "5temp"}
    entry.update(fields)
    return entry


def test_direct_param():
    param = WriteParam.from_entry(
        "p01RoomTempDayHC1",
        _write_entry(min="12", max="32", step=0.1, unit=" °C", icon="mdi:x"),
    )
    assert param.name == "p01RoomTempDayHC1"
    assert (param.command, param.type, param.decode_type) == (
        "0B0005",
        "number",
        "5temp",
    )
    assert (param.min, param.max) == ("12", "32")
    assert (param.min_value, param.max_value) == (12.0, 32.0)
    assert param.step == 0.1
    assert param.unit == " °C"
    assert param.block is None
    assert param.signed is True


@pytest.mark.parametrize(
    ("step", "expected"), [("0.5", 0.5), (1, 1.0), ("", None), ("x", None)]
)
def test_step_parsing(step, expected):
    assert WriteParam.from_entry("p", _write_entry(step=step)).step == expected
    assert WriteParam.from_entry("p", _write_entry()).step is None


def test_time_bounds_stay_text():
    param = WriteParam.from_entry(
        "pHolidayBeginTime", _write_entry(type="time", min="00:00", max="23:59")
    )
    assert (param.min, param.max) == ("00:00", "23:59")
    assert param.min_value is None


def test_missing_or_none_text_fields_are_empty():
    param = WriteParam.from_entry("p", _write_entry(icon=None))
    assert (param.icon, param.unit, param.min, param.device_class) == ("", "", "", "")


def test_block_param():
    param = WriteParam.from_entry(
        "progHC1Friday",
        _write_entry(
            command="0B",
            parent="pHeatProg",
            write_mode="block",
            offset=8,
            length=1,
            bit=4,
            signed=False,
        ),
    )
    assert param.parent == "pHeatProg"
    assert param.block == BlockLayout(offset=8, length=1, bit=4, signed=False)
    assert param.signed is False


def test_manager_types_every_write_entry():
    manager = RegisterMapManagerWrite("206")
    params = manager.params()
    assert set(params) == set(manager.get_all_registers())
    day = manager.param("p01RoomTempDay")
    assert day is not None
    assert day.block is not None
    assert (day.command, day.block.offset, day.block.length) == ("17", 2, 2)
    assert manager.param("nonexistent") is None

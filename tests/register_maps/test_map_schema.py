"""Schema checks over the register maps of every firmware profile.

The maps are hand-written tables; these tests catch a typo in a decode type,
a field placed in a block's header, a flag longer than a nibble, a missing
translation, or write bounds the wrong way round, for every profile in
FIRMWARE_MAPS, with and without cooling. They check the shape of the maps,
not their contents: the offsets themselves were confirmed on devices.
"""

from collections import Counter
import json
from pathlib import Path

import pytest

from custom_components.thz.register_maps.register_map_manager import (
    FIRMWARE_MAPS,
    RegisterMapManager,
    RegisterMapManagerWrite,
)
from custom_components.thz.value_codec import _DECODE_DISPATCH
from custom_components.thz.value_maps import SELECT_MAP

_STRINGS = json.loads(
    (Path(__file__).parents[2] / "custom_components/thz/strings.json").read_text()
)["entity"]

# Read decode types without their own decoder: skipped placeholders and
# values shown as raw hex.
_SKIPPED_READ_TYPES = {"disabled", "n.a.", "n.a"}
_HEX_READ_TYPES = {"raw", "swver", "hex2ascii", "opmode2"}
_META_KEYS = {"unit", "device_class", "state_class", "icon", "translation_key"}

_WRITE_TYPES = {"number", "select", "switch", "time", "schedule", "ptime", "button"}
_WRITE_DECODE_TYPES = {
    "0clean",
    "1clean",
    "4temp",
    "5temp",
    "6gradient",
    "7prog",
    "8party",
    "9holy",
    "D1last",
    "pClean",
}

_PROFILES = [
    pytest.param(firmware, cooling, id=f"{firmware}-{'cool' if cooling else 'nocool'}")
    for firmware in FIRMWARE_MAPS
    for cooling in (True, False)
]


def _fields(firmware, cooling):
    manager = RegisterMapManager(firmware, has_cooling=cooling)
    for block, fields in manager.fields().items():
        for read_field in fields:
            yield block, read_field


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_read_fields_are_well_formed(firmware, cooling):
    for block, read_field in _fields(firmware, cooling):
        where = f"{firmware} {block} {read_field.name}"
        assert block.startswith("pxx"), where
        assert read_field.name, where
        assert read_field.nibble_offset >= 0, where
        assert read_field.nibble_length >= 1, where
        assert isinstance(read_field.factor, int | float), where
        assert read_field.factor >= 0, where
        assert set(read_field.meta) <= _META_KEYS, where


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_read_decode_types_are_known(firmware, cooling):
    known = set(_DECODE_DISPATCH) | _SKIPPED_READ_TYPES | _HEX_READ_TYPES
    for block, read_field in _fields(firmware, cooling):
        assert read_field.is_bit or read_field.decode_type in known, (
            f"{firmware} {block} {read_field.name}: {read_field.decode_type}"
        )


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_flags_are_one_nibble(firmware, cooling):
    """A flag's bit (0..3) counts within its nibble; ReadField.bit relies on it."""
    for block, read_field in _fields(firmware, cooling):
        if read_field.is_bit:
            where = f"{firmware} {block} {read_field.name}"
            assert read_field.nibble_length == 1, where
            assert int(read_field.decode_type.lstrip("nbit")) <= 3, where


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_fields_start_after_the_block_header(firmware, cooling):
    """The decoded block starts with the CRC byte and the address echo."""
    for block, read_field in _fields(firmware, cooling):
        if read_field.decode_type in _SKIPPED_READ_TYPES:
            continue
        header = 1 + len(bytes.fromhex(block.removeprefix("pxx")))
        assert read_field.byte_offset >= header, f"{firmware} {block} {read_field.name}"


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_field_names_are_unique_per_block(firmware, cooling):
    manager = RegisterMapManager(firmware, has_cooling=cooling)
    for block, fields in manager.fields().items():
        duplicates = [n for n, c in Counter(f.name for f in fields).items() if c > 1]
        assert duplicates == [], f"{firmware} {block}"


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_read_translation_keys_exist(firmware, cooling):
    for block, read_field in _fields(firmware, cooling):
        key = read_field.translation_key
        # Placeholders ("n.a.", "disabled") get no entity, so no name.
        if key is None or read_field.decode_type in _SKIPPED_READ_TYPES:
            continue
        platform = "binary_sensor" if read_field.is_bit else "sensor"
        assert key in _STRINGS[platform], f"{firmware} {block} {read_field.name}"


def _bound(value: str) -> float:
    """A numeric bound, or an "HH:MM" time in minutes."""
    if ":" in value:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    return float(value)


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_write_params_are_well_formed(firmware, cooling):
    registers = RegisterMapManagerWrite(firmware, has_cooling=cooling)
    # Every map entry becomes a typed parameter; none is dropped.
    assert set(registers.params()) == set(registers.get_all_registers())
    for name, entry in registers.get_all_registers().items():
        where = f"{firmware} {name}"
        bytes.fromhex(entry["command"])
        assert entry["type"] in _WRITE_TYPES, where
        if entry["type"] == "select":
            assert entry["decode_type"] in SELECT_MAP, where
        else:
            assert entry["decode_type"] in _WRITE_DECODE_TYPES, where
        if entry.get("step") not in (None, ""):
            float(entry["step"])

        low, high = entry["min"], entry["max"]
        assert (low == "") == (high == ""), where
        if low != "":
            if entry["type"] == "button":
                assert _bound(low) <= _bound(high), where
            else:
                assert _bound(low) < _bound(high), where


@pytest.mark.parametrize(("firmware", "cooling"), _PROFILES)
def test_2xx_block_params_have_a_layout(firmware, cooling):
    """Every 2.x parameter inside a block found its position in the read map."""
    registers = RegisterMapManagerWrite(firmware, has_cooling=cooling)
    for name, entry in registers.get_all_registers().items():
        if "parent" not in entry or entry["type"] == "ptime":
            continue
        where = f"{firmware} {name}"
        assert entry.get("write_mode") == "block", where
        # CRC at 0 and the one-byte address echo at 1 come first.
        assert entry["offset"] >= 2, where
        assert entry["length"] >= 1, where
        assert entry.get("bit", 0) in range(8), where


def _translation_keys_in_use() -> dict[str, set[str]]:
    """Entity translation keys any firmware profile's maps can produce."""
    from custom_components.thz.entity_translations import get_translation_key

    used: dict[str, set[str]] = {}
    for firmware in FIRMWARE_MAPS:
        for cooling in (True, False):
            registers = RegisterMapManagerWrite(firmware, has_cooling=cooling)
            for name, param in registers.params().items():
                key = get_translation_key(name)
                if key is None:
                    continue
                if param.type == "schedule":
                    used.setdefault("time", set()).update(
                        {f"{key}_start", f"{key}_end"}
                    )
                    continue
                used.setdefault(param.type, set()).add(key)
                if param.decode_type == "8party":
                    used.setdefault("time", set()).add(f"{key}_end")
            for _block, read_field in _fields(firmware, cooling):
                if read_field.decode_type in _SKIPPED_READ_TYPES:
                    continue
                if read_field.translation_key is not None:
                    platform = "binary_sensor" if read_field.is_bit else "sensor"
                    used.setdefault(platform, set()).add(read_field.translation_key)
    return used


def test_every_entity_translation_is_used():
    """strings.json names no entity that no firmware profile creates.

    A key counts as used if a register map produces it, a fault sensor
    class has it, or the code names it (climate and COP entities set
    theirs directly).
    """
    from custom_components.thz.fault_sensor import _THZFaultSensor

    used = _translation_keys_in_use()
    used.setdefault("sensor", set()).update(
        f"fault_{cls.KEY}" for cls in _THZFaultSensor.__subclasses__()
    )
    source = "\n".join(
        path.read_text()
        for path in (Path(__file__).parents[2] / "custom_components/thz").rglob("*.py")
    )
    unused = [
        f"{platform}.{key}"
        for platform, keys in _STRINGS.items()
        for key in keys
        if key not in used.get(platform, set()) and f'"{key}"' not in source
    ]
    assert unused == []

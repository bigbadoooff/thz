"""Typed view of the read-map entries.

The map modules keep FHEM's notation: each field is a tuple
``(name, offset, length, decode_type, factor[, meta])`` with offset and
length counted in nibbles (hex characters of the answer), because that is
how FHEM's 00_THZ.pm and the device documentation describe them. ReadField
turns such a tuple into byte positions once, so the nibble arithmetic lives
here and nowhere else.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

# Decode types of single-bit flags: "bit0".."bit3" and the negated "nbit0"...
_BIT_PREFIXES = ("nbit", "bit")


def normalize_field_name(name: str) -> str:
    """Return a map name without surrounding blanks and trailing colon."""
    return name.strip().rstrip(":").strip()


def _bit_parts(decode_type: str) -> tuple[str, int] | None:
    """Return (prefix, bit) of a "bitN"/"nbitN" decode type, else None."""
    for prefix in _BIT_PREFIXES:
        rest = decode_type.removeprefix(prefix)
        if rest != decode_type and rest.isdigit():
            return prefix, int(rest)
    return None


@dataclass(frozen=True, slots=True)
class ReadField:
    """One field of a read-map block, in the map's nibble notation."""

    block: str
    name: str
    nibble_offset: int
    nibble_length: int
    decode_type: str
    # Kept as given in the map (int or float): decoding divides by it, and
    # an int keeps whole-number values integral.
    factor: int | float
    # Read-only (see from_tuple) and left out of the hash, so a field can be
    # used as a dict key or in a set.
    meta: Mapping[str, Any] = field(default_factory=dict, hash=False)

    @classmethod
    def from_tuple(cls, block: str, entry: tuple[Any, ...]) -> ReadField:
        """Build a field from a map tuple ``(name, offset, length, decode, factor[, meta])``."""
        name, offset, length, decode_type, factor = entry[:5]
        meta = entry[5] if len(entry) > 5 else {}
        return cls(
            block=block,
            name=normalize_field_name(name),
            nibble_offset=int(offset),
            nibble_length=int(length),
            decode_type=str(decode_type),
            factor=factor,
            meta=MappingProxyType(dict(meta)),
        )

    @property
    def byte_offset(self) -> int:
        """Offset of the first byte in the decoded block (CRC at 0)."""
        return self.nibble_offset // 2

    @property
    def byte_length(self) -> int:
        """Number of bytes that hold the field (a single nibble takes one)."""
        return (self.nibble_length + 1) // 2

    @property
    def nibble(self) -> str | None:
        """For a one-nibble field: "high" (even offset) or "low" half of its byte."""
        if self.nibble_length != 1:
            return None
        return "high" if self.nibble_offset % 2 == 0 else "low"

    @property
    def is_bit(self) -> bool:
        """True for a single-bit flag ("bitN" or "nbitN")."""
        return _bit_parts(self.decode_type) is not None

    @property
    def bit(self) -> int | None:
        """Bit index within the byte, or None if the field is not a flag.

        The map counts the bits of the field's nibble; a flag in the high
        nibble (even nibble offset) is four bits up in the byte.
        """
        parts = _bit_parts(self.decode_type)
        if parts is None:
            return None
        return parts[1] + 4 if self.nibble == "high" else parts[1]

    @property
    def byte_decode_type(self) -> str:
        """The decode type for the field's whole byte ("bit1" in the high nibble → "bit5")."""
        parts = _bit_parts(self.decode_type)
        if parts is None or self.bit is None:
            return self.decode_type
        return f"{parts[0]}{self.bit}"

    @property
    def scale(self) -> float:
        """The factor as a float divisor; 0 or missing counts as 1."""
        return float(self.factor) if self.factor else 1.0

    @property
    def translation_key(self) -> str | None:
        """The entity translation key from the field's meta data."""
        value = self.meta.get("translation_key")
        return str(value) if value is not None else None


def _text(entry: Mapping[str, Any], key: str) -> str:
    """Return a text field of a write-map dict; missing or None is ""."""
    value = entry.get(key)
    return "" if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    """Return a map number ("12", 0.5, "") as float; None if unset or text."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class BlockLayout:
    """Where a 2.x parameter lives inside its register block.

    The parameter is read out of the block and written by read-modify-write
    of the whole block (THZDevice.write_block_value).
    """

    # Byte offset in the decoded block (CRC at 0, address echo at 1).
    offset: int
    length: int
    # Bit of a single-bit flag sharing its byte with others, else None.
    bit: int | None
    # FHEM reads 2.x values unsigned unless the read map says "hex2int".
    signed: bool


@dataclass(frozen=True, slots=True)
class WriteParam:
    """One entry of the write map: a setting the integration can change.

    Built from the merged (and for 2.x firmware enriched) write-map dict.
    The bounds keep the map's text because times use "HH:MM"; numeric
    bounds and the step are also available as floats.
    """

    name: str
    # Register of the parameter, or the parent block for a 2.x parameter.
    command: str
    # Entity platform: "number", "select", "switch", "time", "schedule",
    # "ptime" or "button".
    type: str
    decode_type: str
    min: str = ""
    max: str = ""
    # Encoding step (e.g. 0.1 for tenths); None if the map leaves it empty.
    step: float | None = None
    unit: str = ""
    device_class: str = ""
    icon: str = ""
    # 2.x parameter group ("p01-p12") whose block holds the value.
    parent: str | None = None
    block: BlockLayout | None = None

    @classmethod
    def from_entry(cls, name: str, entry: Mapping[str, Any]) -> WriteParam:
        """Build a parameter from a write-map dict."""
        block = None
        if entry.get("write_mode") == "block":
            bit = entry.get("bit")
            block = BlockLayout(
                offset=int(entry["offset"]),
                length=int(entry["length"]),
                bit=int(bit) if bit is not None else None,
                signed=bool(entry.get("signed", True)),
            )
        parent = entry.get("parent")
        return cls(
            name=name,
            command=str(entry["command"]),
            type=str(entry["type"]),
            decode_type=str(entry["decode_type"]),
            min=_text(entry, "min"),
            max=_text(entry, "max"),
            step=_optional_float(entry.get("step")),
            unit=_text(entry, "unit"),
            device_class=_text(entry, "device_class"),
            icon=_text(entry, "icon"),
            parent=str(parent) if parent is not None else None,
            block=block,
        )

    @property
    def min_value(self) -> float | None:
        """The lower bound as a number, or None if unset or not numeric."""
        return _optional_float(self.min)

    @property
    def max_value(self) -> float | None:
        """The upper bound as a number, or None if unset or not numeric."""
        return _optional_float(self.max)

    @property
    def signed(self) -> bool:
        """Whether the value is decoded as signed (4.x/5.x registers always are)."""
        return self.block.signed if self.block is not None else True

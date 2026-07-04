"""Value encoding and decoding for THZ device communication.

This module centralizes the logic for encoding values to send to the device
and decoding values received from the device.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable

from .value_maps import SELECT_MAP

_LOGGER = logging.getLogger(__name__)


def _dec_hex2int(raw: bytes, factor: float) -> int | float:
    return int.from_bytes(raw, byteorder="big", signed=True) / factor


def _dec_hex(raw: bytes, factor: float) -> int | float:
    return int.from_bytes(raw, byteorder="big") / factor


def _dec_esp_mant(raw: bytes, factor: float) -> float:
    if len(raw) != 4:
        raise ValueError(
            f"Invalid esp_mant length: expected 4 bytes, got {len(raw)}"
        )
    try:
        mant = struct.unpack(">f", raw)[0]
    except struct.error as err:
        raise ValueError(f"Failed to decode esp_mant value: {err}") from err
    return round(mant, 3)


def _dec_hexdate(raw: bytes, factor: float) -> str:
    val = int.from_bytes(raw, byteorder="big")
    return f"{val // 100:02d}.{val % 100:02d}"


def _dec_clockdate(raw: bytes, factor: float) -> str:
    if len(raw) != 3:
        raise ValueError(
            f"Invalid clockdate length: expected 3 bytes, got {len(raw)}"
        )
    year = raw[0] + 2000
    month = raw[1]
    day = raw[2]
    return f"{year:04d}-{month:02d}-{day:02d}"


def _dec_somwinmode(raw: bytes, factor: float) -> str:
    key = raw.hex()
    return SELECT_MAP.get("SomWinMode", {}).get(key, key)


def _dec_weekday(raw: bytes, factor: float) -> str:
    key = str(int.from_bytes(raw, byteorder="big"))
    return SELECT_MAP.get("weekday", {}).get(key, key)


def _dec_opmodehc(raw: bytes, factor: float) -> str:
    key = str(int.from_bytes(raw, byteorder="big"))
    return SELECT_MAP.get("OpModeHC", {}).get(key, key)


def _dec_party_time(raw: bytes, factor: float) -> int | float:
    return int.from_bytes(raw, byteorder="big") / factor


def _dec_faultmap(raw: bytes, factor: float) -> str:
    """Decode a fault code integer to a human-readable fault name.

    The raw bytes are interpreted as a big-endian unsigned integer and looked
    up in SELECT_MAP['faultmap'].  Matches FHEM: ``$faultmap{(hex($value))}``.
    Returns the fault name string, or the numeric value as a string when the
    code is not in the map.
    """
    code = int.from_bytes(raw, byteorder="big")
    return SELECT_MAP.get("faultmap", {}).get(str(code), str(code))


def _dec_hex2time(raw: bytes, factor: float) -> str:
    """Decode a device time value to a "HH:MM" string.

    The raw bytes hold a decimal-encoded time stored as a big-endian unsigned
    integer: ``value = hours * 100 + minutes``.  This matches FHEM firmware
    206: ``sprintf("%02u:%02u", hex($value)/100, hex($value)%100)``.

    Example: bytes ``0x04 0xCE`` → 1230 → "12:30".
    """
    value = int.from_bytes(raw, byteorder="big")
    hours = value // 100
    minutes = value % 100
    return f"{hours:02d}:{minutes:02d}"


def _dec_hex2error(raw: bytes, factor: float) -> str:
    r"""Decode a 4-byte active-error bitmap to a comma-separated fault list.

    Each bit in the 4-byte (32-bit) value represents one error code.  Bits
    are enumerated LSB-first within each byte (matching Perl's ``unpack('b32',
    pack('H*', $value))``).  Bit position N (0-indexed) maps to fault key
    ``str(N + 1)`` in SELECT_MAP['faultmap'].

    Returns a comma-separated string of active fault names, or ``"n.a."`` when
    no faults are active.  This matches FHEM: ``bitmap2string(unpack('b32',
    pack('H*', $value)), \%faultmap)``.
    """
    faultmap = SELECT_MAP.get("faultmap", {})
    active: list[str] = []
    for byte_idx, byte_val in enumerate(raw):
        for bit_idx in range(8):  # LSB-first within each byte
            if byte_val & (1 << bit_idx):
                fault_key = str(byte_idx * 8 + bit_idx + 1)
                fault_name = faultmap.get(fault_key)
                if fault_name and fault_name != "n.a.":
                    active.append(fault_name)
    return ", ".join(active) if active else "n.a."


# Dispatch table mapping exact decode_type strings to their handler functions.
# For prefix-based types ("bit*", "nbit*") see decode_raw_value() below.
# Note: "8party" is the protocol-defined decode_type string used in register maps.
_DECODE_DISPATCH: dict[str, Callable[[bytes, float], int | float | bool | str]] = {
    "hex2int": _dec_hex2int,
    "hex": _dec_hex,
    "esp_mant": _dec_esp_mant,
    "hexdate": _dec_hexdate,
    "clockdate": _dec_clockdate,
    "somwinmode": _dec_somwinmode,
    "weekday": _dec_weekday,
    "opmodehc": _dec_opmodehc,
    "8party": _dec_party_time,
    "faultmap": _dec_faultmap,
    "hex2time": _dec_hex2time,
    "hex2error": _dec_hex2error,
}


def decode_raw_value(
    raw: bytes, decode_type: str, factor: float = 1.0
) -> int | float | bool | str:
    """Decode a raw byte value according to the specified decode type.

    Args:
        raw: The raw bytes to decode.
        decode_type: The type of decoding to apply. Supported types:
            - "hex2int": Signed integer divided by factor.
            - "hex": Unsigned integer divided by factor.
            - "bitX": Extracts bit number X (e.g., "bit3").
            - "nbitX": Negation of bit X (e.g., "nbit2").
            - "esp_mant": Mantissa and exponent representation.
            - "hexdate": 2-byte unsigned int formatted as "DD.MM"
              (value/100 . value%100).
            - "clockdate": 3-byte date (year-offset, month, day) → "YYYY-MM-DD".
            - "somwinmode": Map lookup for summer/winter mode.
            - "weekday": Map lookup for day of week.
            - "opmodehc": Map lookup for HC operating mode.
            - "8party": Unsigned integer (party time in minutes).
            - "faultmap": Big-endian unsigned int looked up in faultmap table.
            - "hex2time": Big-endian 2-byte decimal-encoded time → "HH:MM"
              (value/100 gives hours, value%100 gives minutes).
            - "hex2error": 4-byte LSB-first bitmap of active fault codes →
              comma-separated list of fault names, or "n.a." if none active.
            - Any other: Returns hexadecimal representation.
        factor: The divisor for "hex2int", "hex", and "8party" decoding.
            Defaults to 1.0.

    Returns:
        The decoded value (int, float, bool, or str).
    """
    handler = _DECODE_DISPATCH.get(decode_type)
    if handler is not None:
        return handler(raw, factor)
    if decode_type.startswith("nbit"):
        bitnum = int(decode_type[4:])
        return not bool((raw[0] >> bitnum) & 0x01)
    if decode_type.startswith("bit"):
        bitnum = int(decode_type[3:])
        return bool((raw[0] >> bitnum) & 0x01)
    return raw.hex()


class THZValueCodec:
    """Handles encoding and decoding of values for THZ device communication.

    This class provides methods to convert between Home Assistant values
    and the byte representations used by the THZ device protocol.
    """

    @staticmethod
    def encode_number(
        value: float, step: float, decode_type: str, length: int = 2
    ) -> bytes:
        """Encode a numeric value for device communication.

        Args:
            value: The numeric value to encode.
            step: The step size (for scaling).
            decode_type: The encoding type ("hex2int", "0clean", etc.).
            length: Number of bytes for the encoded value (default 2 for 4xx/5xx
                firmware; pass the register-map length for 2xx block writes).

        Returns:
            Encoded bytes ready to send to device.
        """
        if decode_type == "0clean":
            # Single byte encoding
            return bytes([int(value)])
        else:
            # Standard signed integer encoding scaled by step.
            value_int = int(value / step)
            return value_int.to_bytes(length, byteorder="big", signed=True)

    @staticmethod
    def decode_number(value_bytes: bytes, step: float, decode_type: str) -> float:
        """Decode a numeric value from device response.

        Args:
            value_bytes: The raw bytes from device.
            step: The step size (for scaling).
            decode_type: The decoding type.

        Returns:
            The decoded numeric value.

        Raises:
            ValueError: If decoding fails.
        """
        if not value_bytes:
            raise ValueError("No data to decode")

        if decode_type == "0clean":
            # Single byte decoding
            return float(value_bytes[0])
        else:
            # Standard 2-byte signed integer decoding with scaling
            value = int.from_bytes(value_bytes, byteorder="big", signed=True)
            return value * step

    @staticmethod
    def encode_select(option: str, decode_type: str) -> bytes:
        """Encode a select option for device communication.

        Args:
            option: The selected option string.
            decode_type: The mapping type (must exist in SELECT_MAP).

        Returns:
            Encoded bytes ready to send to device.

        Raises:
            ValueError: If decode_type not found or option invalid.
        """
        if decode_type not in SELECT_MAP:
            raise ValueError(f"Unknown decode_type: {decode_type}")

        # Create reverse mapping from option strings to numeric keys
        # Note: Keys in SELECT_MAP are strings, possibly zero-padded
        reverse_map = {v: k for k, v in SELECT_MAP[decode_type].items()}

        if option not in reverse_map:
            raise ValueError(
                f"Invalid option '{option}' for decode_type '{decode_type}'"
            )

        # Get the string key and convert to int
        key_str = reverse_map[option]
        value = int(key_str)

        # "2opmode" type: device uses single-byte encoding (FHEM legacy format)
        # Value goes in first byte; second byte is always zero padding.
        # All other types use 2-byte big-endian.
        if decode_type == "2opmode":
            return bytes([value & 0xFF, 0])

        # Encode as 2-byte big-endian (matches device register width)
        return value.to_bytes(2, byteorder="big", signed=False)

    @staticmethod
    def decode_select(value_bytes: bytes, decode_type: str) -> str | None:
        """Decode a select value from device response.

        Args:
            value_bytes: The raw bytes from device.
            decode_type: The mapping type (must exist in SELECT_MAP).

        Returns:
            The decoded option string, or None if not found.

        Raises:
            ValueError: If decode_type not found or decoding fails.
        """
        if not value_bytes:
            raise ValueError("No data to decode")

        if decode_type not in SELECT_MAP:
            raise ValueError(f"Unknown decode_type: {decode_type}")

        # "2opmode" type: device returns value in first byte only (FHEM legacy format)
        # FHEM reads 2 hex chars (1 byte) at the value offset; second byte is padding.
        if decode_type == "2opmode":
            value = value_bytes[0]
        else:
            # Decode as big-endian (matches device register byte order)
            value = int.from_bytes(value_bytes, byteorder="big", signed=False)

        # Special case for SomWinMode: zero-pad to 2 digits
        if decode_type == "SomWinMode":
            value_str = str(value).zfill(2)
        else:
            value_str = str(value)

        # Map to option string
        if value_str in SELECT_MAP[decode_type]:
            return SELECT_MAP[decode_type][value_str]

        _LOGGER.warning(
            "Unknown value %s for decode_type %s, available: %s",
            value_str,
            decode_type,
            list(SELECT_MAP[decode_type].keys())
        )
        return None

    @staticmethod
    def encode_switch(is_on: bool) -> bytes:
        """Encode a switch state for device communication.

        Args:
            is_on: True for on, False for off.

        Returns:
            Encoded bytes (1 for on, 0 for off).
        """
        value = 1 if is_on else 0
        return value.to_bytes(2, byteorder="big", signed=False)

    @staticmethod
    def decode_switch(value_bytes: bytes) -> bool:
        """Decode a switch state from device response.

        Args:
            value_bytes: The raw bytes from device.

        Returns:
            True if on, False if off.

        Raises:
            ValueError: If decoding fails.
        """
        if not value_bytes:
            raise ValueError("No data to decode")

        value = int.from_bytes(value_bytes, byteorder="big", signed=False)
        return value != 0

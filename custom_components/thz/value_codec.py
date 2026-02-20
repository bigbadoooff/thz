"""Value encoding and decoding for THZ device communication.

This module centralizes the logic for encoding values to send to the device
and decoding values received from the device.
"""

from __future__ import annotations

import logging
import struct

from .value_maps import SELECT_MAP

_LOGGER = logging.getLogger(__name__)


def decode_raw_value(
    raw: bytes, decode_type: str, factor: float = 1.0
) -> int | float | bool | str:
    """Decode a raw byte value according to the specified decode type.

    Args:
        raw: The raw bytes to decode.
        decode_type: The type of decoding to apply. Supported types:
            - "hex2int": Signed integer divided by factor.
            - "hex": Unsigned integer.
            - "bitX": Extracts bit number X (e.g., "bit3").
            - "nbitX": Negation of bit X (e.g., "nbit2").
            - "esp_mant": Mantissa and exponent representation.
            - Any other: Returns hexadecimal representation.
        factor: The divisor for "hex2int" decoding. Defaults to 1.0.

    Returns:
        The decoded value (int, float, bool, or str).
    """
    if decode_type == "hex2int":
        return int.from_bytes(raw, byteorder="big", signed=True) / factor
    if decode_type == "hex":
        return int.from_bytes(raw, byteorder="big")
    if decode_type.startswith("bit"):
        bitnum = int(decode_type[3:])
        return bool((raw[0] >> bitnum) & 0x01)
    if decode_type.startswith("nbit"):
        bitnum = int(decode_type[4:])
        return not bool((raw[0] >> bitnum) & 0x01)
    if decode_type == "esp_mant":
        mant = struct.unpack(">f", raw)[0]
        return round(mant, 3)
    return raw.hex()


class THZValueCodec:
    """Handles encoding and decoding of values for THZ device communication.

    This class provides methods to convert between Home Assistant values
    and the byte representations used by the THZ device protocol.
    """

    @staticmethod
    def encode_number(value: float, step: float, decode_type: str) -> bytes:
        """Encode a numeric value for device communication.

        Args:
            value: The numeric value to encode.
            step: The step size (for scaling).
            decode_type: The encoding type ("hex2int", "0clean", etc.).

        Returns:
            Encoded bytes ready to send to device.
        """
        if decode_type == "0clean":
            # Single byte encoding
            return bytes([int(value)])
        else:
            # Standard 2-byte signed integer encoding
            value_int = int(value / step)
            return value_int.to_bytes(2, byteorder="big", signed=True)

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
            raise ValueError(f"Invalid option '{option}' for decode_type '{decode_type}'")

        # Get the string key and convert to int
        key_str = reverse_map[option]
        value = int(key_str)

        # Encode as single byte (little-endian as per original select.py)
        return value.to_bytes(1, byteorder="little", signed=False)

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

        # Decode as little-endian (as per original select.py)
        value = int.from_bytes(value_bytes, byteorder="little", signed=False)

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

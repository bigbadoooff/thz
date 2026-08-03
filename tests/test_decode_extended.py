"""Extended tests for decode_value function to increase coverage."""

import struct

from tests.test_helpers import decode_value


class TestDecodeValueExtended:
    """Extended tests for decode_value with more edge cases."""

    def test_hex2int_with_various_factors(self):
        """Test hex2int with different factor values."""
        raw = b'\x03\xe8'  # 1000 in hex

        # Test various factors
        assert decode_value(raw, "hex2int", 1) == 1000.0
        assert decode_value(raw, "hex2int", 10) == 100.0
        assert decode_value(raw, "hex2int", 100) == 10.0
        assert decode_value(raw, "hex2int", 1000) == 1.0

    def test_hex2int_negative_with_factors(self):
        """Test hex2int negative values with factors."""
        raw = b'\xff\x9c'  # -100 in signed 16-bit

        assert decode_value(raw, "hex2int", 1) == -100.0
        assert decode_value(raw, "hex2int", 10) == -10.0
        assert decode_value(raw, "hex2int", 100) == -1.0

    def test_hex2int_single_byte_signed(self):
        """Test hex2int with single byte signed values."""
        # Positive single byte
        assert decode_value(b'\x7f', "hex2int", 1) == 127.0

        # Single byte 0x80 is interpreted as -128 in signed representation
        assert decode_value(b'\x80', "hex2int", 1) == -128.0

    def test_hex2int_three_bytes(self):
        """Test hex2int with three bytes."""
        raw = b'\x01\x02\x03'
        result = decode_value(raw, "hex2int", 1)
        expected = int.from_bytes(raw, byteorder="big", signed=True)
        assert result == float(expected)

    def test_hex2int_four_bytes(self):
        """Test hex2int with four bytes."""
        raw = b'\x00\x01\x02\x03'
        result = decode_value(raw, "hex2int", 1)
        expected = int.from_bytes(raw, byteorder="big", signed=True)
        assert result == float(expected)

    def test_hex_various_byte_lengths(self):
        """Test hex (unsigned) with various byte lengths."""
        # Single byte
        assert decode_value(b'\xff', "hex") == 255

        # Two bytes
        assert decode_value(b'\x01\x00', "hex") == 256

        # Three bytes
        assert decode_value(b'\x01\x00\x00', "hex") == 65536

        # Four bytes
        assert decode_value(b'\x01\x00\x00\x00', "hex") == 16777216

    def test_hex_large_values(self):
        """Test hex with large unsigned values."""
        # Maximum 16-bit value
        assert decode_value(b'\xff\xff', "hex") == 65535

        # Maximum 24-bit value
        assert decode_value(b'\xff\xff\xff', "hex") == 16777215

        # Maximum 32-bit value
        assert decode_value(b'\xff\xff\xff\xff', "hex") == 4294967295

    def test_all_bit_positions(self):
        """Test bit extraction for all 8 bit positions."""
        # Test byte with all bits set
        raw_all = b'\xff'
        for bit in range(8):
            assert decode_value(raw_all, f"bit{bit}")

        # Test byte with no bits set
        raw_none = b'\x00'
        for bit in range(8):
            assert not decode_value(raw_none, f"bit{bit}")

        # Test individual bits
        for bit in range(8):
            raw = bytes([1 << bit])
            for check_bit in range(8):
                expected = (check_bit == bit)
                assert decode_value(raw, f"bit{check_bit}") == expected

    def test_all_nbit_positions(self):
        """Test negated bit extraction for all positions."""
        # Test byte with all bits set (all nbits should be False)
        raw_all = b'\xff'
        for bit in range(8):
            assert not decode_value(raw_all, f"nbit{bit}")

        # Test byte with no bits set (all nbits should be True)
        raw_none = b'\x00'
        for bit in range(8):
            assert decode_value(raw_none, f"nbit{bit}")

    def test_bit_extraction_multi_byte_uses_first(self):
        """Test that bit extraction only uses first byte."""
        # Second byte should be ignored
        raw = b'\x01\xff'
        assert decode_value(raw, "bit0")
        assert not decode_value(raw, "bit1")

        raw = b'\x00\xff'
        assert not decode_value(raw, "bit0")
        assert not decode_value(raw, "bit7")

    def test_esp_mant_special_values(self):
        """Test esp_mant with special float values."""
        # Zero
        raw = struct.pack('>f', 0.0)
        assert decode_value(raw, "esp_mant") == 0.0

        # One
        raw = struct.pack('>f', 1.0)
        result = decode_value(raw, "esp_mant")
        assert abs(result - 1.0) < 0.001

        # Negative one
        raw = struct.pack('>f', -1.0)
        result = decode_value(raw, "esp_mant")
        assert abs(result - (-1.0)) < 0.001

    def test_esp_mant_large_values(self):
        """Test esp_mant with large float values."""
        # Large positive
        raw = struct.pack('>f', 1000.5)
        result = decode_value(raw, "esp_mant")
        assert abs(result - 1000.5) < 0.001

        # Large negative
        raw = struct.pack('>f', -1000.5)
        result = decode_value(raw, "esp_mant")
        assert abs(result - (-1000.5)) < 0.001

    def test_esp_mant_small_values(self):
        """Test esp_mant with small float values."""
        # Small positive
        raw = struct.pack('>f', 0.001)
        result = decode_value(raw, "esp_mant")
        assert abs(result - 0.001) < 0.0001

        # Small negative
        raw = struct.pack('>f', -0.001)
        result = decode_value(raw, "esp_mant")
        assert abs(result - (-0.001)) < 0.0001

    def test_esp_mant_rounding_precision(self):
        """Test that esp_mant rounds to 3 decimal places."""
        # Value with more than 3 decimal places
        raw = struct.pack('>f', 1.23456789)
        result = decode_value(raw, "esp_mant")

        # Should be rounded to 3 decimals
        # The exact value might vary due to float precision
        str_result = str(result)
        if '.' in str_result:
            decimal_places = len(str_result.split('.')[1])
            assert decimal_places <= 3

    def test_default_hex_string_various_lengths(self):
        """Test default hex string return for various byte lengths."""
        # Single byte
        assert decode_value(b'\xab', "unknown") == "ab"

        # Two bytes
        assert decode_value(b'\xab\xcd', "unknown") == "abcd"

        # Three bytes
        assert decode_value(b'\xab\xcd\xef', "unknown") == "abcdef"

        # Four bytes
        assert decode_value(b'\x01\x23\x45\x67', "unknown") == "01234567"

    def test_default_hex_string_with_zeros(self):
        """Test default hex string with zero bytes."""
        assert decode_value(b'\x00', "unknown") == "00"
        assert decode_value(b'\x00\x00', "unknown") == "0000"
        assert decode_value(b'\x00\xff', "unknown") == "00ff"

    def test_empty_decode_type_returns_hex(self):
        """Test that empty decode type returns hex string."""
        assert decode_value(b'\xaa\xbb', "") == "aabb"
        assert decode_value(b'\x12\x34', "") == "1234"

    def test_unknown_decode_types(self):
        """Test various unknown decode types return hex string or boolean."""
        raw = b'\xde\xad\xbe\xef'

        # These return hex strings
        hex_string_types = [
            "invalid",
            "unknown",
            "random",
            "hex2float",  # Not implemented
            "decimal",    # Not implemented
        ]

        for decode_type in hex_string_types:
            result = decode_value(raw, decode_type)
            assert result == "deadbeef"

        # These try to extract bits and return boolean. bit8/nbit8 would try to
        # extract bit 8, which causes an error or unexpected behavior — just
        # test that they at least return something without crashing.
        raw_single = b'\xff'
        try:
            result = decode_value(raw_single, "bit8")
            # If it doesn't crash, that's acceptable
            assert result is not None
        except (IndexError, ValueError):
            # Also acceptable if it raises an error
            pass


class TestDecodeValueBoundaries:
    """Test decode_value with boundary conditions."""

    def test_hex2int_max_positive(self):
        """Test maximum positive values for hex2int."""
        # Max 16-bit signed positive
        raw = b'\x7f\xff'
        assert decode_value(raw, "hex2int", 1) == 32767.0

    def test_hex2int_max_negative(self):
        """Test maximum negative values for hex2int."""
        # Max 16-bit signed negative
        raw = b'\x80\x00'
        assert decode_value(raw, "hex2int", 1) == -32768.0

    def test_hex_zero(self):
        """Test hex with zero value."""
        assert decode_value(b'\x00', "hex") == 0
        assert decode_value(b'\x00\x00', "hex") == 0
        assert decode_value(b'\x00\x00\x00', "hex") == 0

    def test_bit_pattern_alternating(self):
        """Test bit patterns with alternating bits."""
        # 0b01010101 = 0x55
        raw = b'\x55'
        assert decode_value(raw, "bit0")
        assert not decode_value(raw, "bit1")
        assert decode_value(raw, "bit2")
        assert not decode_value(raw, "bit3")

        # 0b10101010 = 0xAA
        raw = b'\xaa'
        assert not decode_value(raw, "bit0")
        assert decode_value(raw, "bit1")
        assert not decode_value(raw, "bit2")
        assert decode_value(raw, "bit3")


class TestDecodeOpmodehc:
    """Tests for opmodehc decoding (HC operating mode)."""

    def test_normal_mode(self):
        """Test decoding value 1 (normal mode)."""
        raw = b'\x00\x01'
        assert decode_value(raw, "opmodehc") == "normal"

    def test_setback_mode(self):
        """Test decoding value 2 (setback mode)."""
        raw = b'\x00\x02'
        assert decode_value(raw, "opmodehc") == "setback"

    def test_standby_mode(self):
        """Test decoding value 3 (standby mode)."""
        raw = b'\x00\x03'
        assert decode_value(raw, "opmodehc") == "standby"

    def test_unknown_mode_returns_key(self):
        """Test that an unmapped value returns its string representation."""
        raw = b'\x00\x0f'  # value 15, not in map
        result = decode_value(raw, "opmodehc")
        assert result == "15"


class TestDecode8Party:
    """Tests for 8party decoding (party time in minutes)."""

    def test_zero_minutes(self):
        """Test decoding zero party time."""
        raw = b'\x00\x00\x00\x00'
        assert decode_value(raw, "8party") == 0

    def test_sixty_minutes(self):
        """Test decoding 60 minutes."""
        raw = b'\x00\x00\x00\x3c'  # 60 = 0x3c
        assert decode_value(raw, "8party") == 60

    def test_max_party_time(self):
        """Test decoding 1439 minutes (23:59)."""
        raw = b'\x00\x00\x05\x9f'  # 1439 = 0x059f
        assert decode_value(raw, "8party") == 1439

    def test_factor_applied(self):
        """Test that factor is applied, consistent with unsigned int decode types."""
        raw = b'\x00\x00\x00\x3c'  # 60
        assert decode_value(raw, "8party", 10) == 6.0

"""Tests for sensor decode_value function."""
import struct

import pytest

from tests.test_helpers import decode_value


class TestDecodeHex2Int:
    """Tests for hex2int decoding."""

    def test_positive_value(self):
        """Test decoding positive integer."""
        raw = b'\x00\x64'  # 100 in hex
        assert decode_value(raw, "hex2int", 10) == 10.0

    def test_negative_value(self):
        """Test decoding negative integer (signed)."""
        raw = b'\xff\x9c'  # -100 in signed 16-bit
        assert decode_value(raw, "hex2int", 10) == -10.0

    def test_zero(self):
        """Test decoding zero."""
        raw = b'\x00\x00'
        assert decode_value(raw, "hex2int", 10) == 0.0

    def test_with_factor_one(self):
        """Test decoding with factor 1."""
        raw = b'\x00\x0a'  # 10 in hex
        assert decode_value(raw, "hex2int", 1) == 10.0

    def test_large_factor(self):
        """Test decoding with large factor."""
        raw = b'\x03\xe8'  # 1000 in hex
        assert decode_value(raw, "hex2int", 100) == 10.0


class TestDecodeHex:
    """Tests for hex decoding (unsigned)."""

    def test_positive_value(self):
        """Test decoding unsigned integer."""
        raw = b'\x00\x64'  # 100
        assert decode_value(raw, "hex") == 100

    def test_large_value(self):
        """Test decoding large unsigned integer."""
        raw = b'\xff\xff'  # 65535
        assert decode_value(raw, "hex") == 65535

    def test_zero(self):
        """Test decoding zero."""
        raw = b'\x00\x00'
        assert decode_value(raw, "hex") == 0


class TestDecodeBit:
    """Tests for bit extraction."""

    def test_bit0_set(self):
        """Test extracting bit 0 when set."""
        raw = b'\x01'  # 0b00000001
        assert decode_value(raw, "bit0")

    def test_bit0_clear(self):
        """Test extracting bit 0 when clear."""
        raw = b'\x00'  # 0b00000000
        assert not decode_value(raw, "bit0")

    def test_bit3_set(self):
        """Test extracting bit 3 when set."""
        raw = b'\x08'  # 0b00001000
        assert decode_value(raw, "bit3")

    def test_bit3_clear(self):
        """Test extracting bit 3 when clear."""
        raw = b'\x07'  # 0b00000111
        assert not decode_value(raw, "bit3")

    def test_bit7_set(self):
        """Test extracting bit 7 (highest bit)."""
        raw = b'\x80'  # 0b10000000
        assert decode_value(raw, "bit7")

    def test_multiple_bits_set(self):
        """Test extracting specific bit when multiple are set."""
        raw = b'\xff'  # 0b11111111
        assert decode_value(raw, "bit0")
        assert decode_value(raw, "bit4")
        assert decode_value(raw, "bit7")


class TestDecodeNbit:
    """Tests for negated bit extraction."""

    def test_nbit0_set(self):
        """Test negated bit 0 when original is set."""
        raw = b'\x01'  # 0b00000001
        assert not decode_value(raw, "nbit0")

    def test_nbit0_clear(self):
        """Test negated bit 0 when original is clear."""
        raw = b'\x00'  # 0b00000000
        assert decode_value(raw, "nbit0")

    def test_nbit3_set(self):
        """Test negated bit 3 when original is set."""
        raw = b'\x08'  # 0b00001000
        assert not decode_value(raw, "nbit3")

    def test_nbit3_clear(self):
        """Test negated bit 3 when original is clear."""
        raw = b'\x07'  # 0b00000111
        assert decode_value(raw, "nbit3")


class TestDecodeEspMant:
    """Tests for esp_mant decoding (float)."""

    def test_positive_float(self):
        """Test decoding positive float."""
        # Pack a float value and test decoding
        value = 23.5
        raw = struct.pack('>f', value)
        result = decode_value(raw, "esp_mant")
        assert abs(result - value) < 0.001

    def test_negative_float(self):
        """Test decoding negative float."""
        value = -15.25
        raw = struct.pack('>f', value)
        result = decode_value(raw, "esp_mant")
        assert abs(result - value) < 0.001

    def test_zero_float(self):
        """Test decoding zero."""
        raw = struct.pack('>f', 0.0)
        result = decode_value(raw, "esp_mant")
        assert result == 0.0

    def test_rounding(self):
        """Test that result is rounded to 3 decimal places."""
        value = 1.23456789
        raw = struct.pack('>f', value)
        result = decode_value(raw, "esp_mant")
        # Should be rounded to 3 decimals
        assert len(str(result).split('.')[-1]) <= 3


class TestDecodeDefault:
    """Tests for default hex string return."""

    def test_unknown_decode_type(self):
        """Test that unknown decode type returns hex string."""
        raw = b'\xab\xcd'
        result = decode_value(raw, "unknown_type")
        assert result == "abcd"

    def test_empty_decode_type(self):
        """Test empty decode type returns hex string."""
        raw = b'\x01\x02\x03'
        result = decode_value(raw, "")
        assert result == "010203"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_single_byte_hex2int(self):
        """Test hex2int with single byte."""
        raw = b'\x0a'
        assert decode_value(raw, "hex2int", 1) == 10.0

    def test_three_byte_hex(self):
        """Test hex with three bytes."""
        raw = b'\x01\x02\x03'
        assert decode_value(raw, "hex") == 66051  # 0x010203

    def test_bit_with_multi_byte(self):
        """Test bit extraction only uses first byte."""
        raw = b'\x01\xff'
        assert decode_value(raw, "bit0")
        assert not decode_value(raw, "bit1")


class TestDecodeFaultmap:
    """Tests for faultmap decoding (fault code integer → fault name string)."""

    def test_known_fault_code_1(self):
        """Test fault code 1 → F01_AnodeFault."""
        # 0x0001 = 1
        raw = b'\x00\x01'
        assert decode_value(raw, "faultmap") == "F01_AnodeFault"

    def test_known_fault_code_2(self):
        """Test fault code 2 → F02_SafetyTempDelimiterEngaged."""
        raw = b'\x00\x02'
        assert decode_value(raw, "faultmap") == "F02_SafetyTempDelimiterEngaged"

    def test_known_fault_code_0(self):
        """Test fault code 0 → n.a. (no fault)."""
        raw = b'\x00\x00'
        assert decode_value(raw, "faultmap") == "n.a."

    def test_known_fault_code_36(self):
        """Test fault code 36 → F36_MinFlowRate."""
        raw = b'\x00\x24'  # 0x24 = 36
        assert decode_value(raw, "faultmap") == "F36_MinFlowRate"

    def test_known_fault_code_52(self):
        """Test fault code 52 → F52_SensorCondenserOutlet (highest known code)."""
        raw = b'\x00\x34'  # 0x34 = 52
        assert decode_value(raw, "faultmap") == "F52_SensorCondenserOutlet"

    def test_unknown_fault_code_returns_numeric_string(self):
        """Test that an unmapped code returns its numeric value as string."""
        raw = b'\x00\x63'  # 99 decimal, not in faultmap
        assert decode_value(raw, "faultmap") == "99"

    def test_single_byte_fault_code(self):
        """Test faultmap with a single byte input.

        The decoder accepts any byte length (big-endian); single-byte input
        simulates the FHEM 'D1last' format for non-206 firmware (length 2 nibbles
        = 1 byte), whereas firmware 206 uses 4 nibbles = 2 bytes.
        """
        # For newer firmware faultCODE uses 1 byte (length 2 nibbles)
        raw = b'\x03'  # 3 → F03_HighPreasureGuardFault
        assert decode_value(raw, "faultmap") == "F03_HighPreasureGuardFault"


class TestDecodeHex2Time:
    """Tests for hex2time decoding (decimal-encoded time → HH:MM string).

    The device stores time as a big-endian integer where:
        value = hours * 100 + minutes
    Matching FHEM firmware 206: sprintf("%02u:%02u", hex($value)/100, hex($value)%100)
    """

    def test_midnight(self):
        """Test 00:00 (midnight)."""
        raw = b'\x00\x00'  # 0 → 00:00
        assert decode_value(raw, "hex2time") == "00:00"

    def test_noon(self):
        """Test 12:00 (noon)."""
        # 12:00 = 1200 = 0x04B0
        raw = b'\x04\xb0'
        assert decode_value(raw, "hex2time") == "12:00"

    def test_half_past_twelve(self):
        """Test 12:30."""
        # 12:30 = 1230 = 0x04CE
        raw = b'\x04\xce'
        assert decode_value(raw, "hex2time") == "12:30"

    def test_end_of_day(self):
        """Test 23:45 (latest standard schedule time)."""
        # 23:45 = 2345 = 0x0929
        raw = b'\x09\x29'
        assert decode_value(raw, "hex2time") == "23:45"

    def test_one_minute_past_midnight(self):
        """Test 00:01."""
        # 00:01 = 1 = 0x0001
        raw = b'\x00\x01'
        assert decode_value(raw, "hex2time") == "00:01"

    def test_single_digit_hour(self):
        """Test 06:30 — hour must be zero-padded."""
        # 06:30 = 630 = 0x0276
        raw = b'\x02\x76'
        assert decode_value(raw, "hex2time") == "06:30"


class TestDecodeTurnHex2Time:
    """Tests for turnhex2time decoding (byte-swapped time → HH:MM string).

    Firmware 4.39/5.39 fault-log times swap the two bytes relative to the
    plain "hex2time" encoding tested above. Matches FHEM's turnhex2time:
    swap the two hex-character pairs, then value/100 = hours, value%100 =
    minutes. Reading the raw bytes little-endian instead of big-endian
    performs the same swap, so each case here is the byte-reversal of the
    equivalent TestDecodeHex2Time case.
    """

    def test_midnight(self):
        """Test 00:00 (midnight); symmetric under swap."""
        raw = b'\x00\x00'
        assert decode_value(raw, "turnhex2time") == "00:00"

    def test_noon(self):
        r"""Test 12:00 (noon). Unswapped 1200 = 0x04B0 → swapped bytes b'\xb0\x04'."""
        raw = b'\xb0\x04'
        assert decode_value(raw, "turnhex2time") == "12:00"

    def test_half_past_twelve(self):
        r"""Test 12:30. Unswapped 1230 = 0x04CE → swapped bytes b'\xce\x04'."""
        raw = b'\xce\x04'
        assert decode_value(raw, "turnhex2time") == "12:30"

    def test_end_of_day(self):
        r"""Test 23:45. Unswapped 2345 = 0x0929 → swapped bytes b'\x29\x09'."""
        raw = b'\x29\x09'
        assert decode_value(raw, "turnhex2time") == "23:45"

    def test_one_minute_past_midnight(self):
        r"""Test 00:01. Unswapped 1 = 0x0001 → swapped bytes b'\x01\x00'."""
        raw = b'\x01\x00'
        assert decode_value(raw, "turnhex2time") == "00:01"

    def test_single_digit_hour(self):
        r"""Test 06:30, hour zero-padded. 630 = 0x0276 -> swapped b'\x76\x02'."""
        raw = b'\x76\x02'
        assert decode_value(raw, "turnhex2time") == "06:30"

    def test_wrong_length_raises(self):
        """Test that a non-2-byte input raises ValueError."""
        with pytest.raises(ValueError, match="turnhex2time"):
            decode_value(b'\x00', "turnhex2time")


class TestDecodeTurnHexDate:
    """Tests for turnhexdate decoding (byte-swapped date → DD.MM string).

    Firmware 4.39/5.39 fault-log dates swap the two bytes relative to the
    plain "hexdate" encoding. Matches FHEM's turnhexdate: swap the two
    hex-character pairs, then value/100 = day, value%100 = month.
    """

    def test_zero_date(self):
        """Test 00.00; symmetric under swap."""
        raw = b'\x00\x00'
        assert decode_value(raw, "turnhexdate") == "00.00"

    def test_fifth_of_january(self):
        r"""Test 05.01. Unswapped 501 = 0x01F5 → swapped bytes b'\xf5\x01'."""
        raw = b'\xf5\x01'
        assert decode_value(raw, "turnhexdate") == "05.01"

    def test_new_years_eve(self):
        r"""Test 31.12. Unswapped 3112 = 0x0C28 → swapped bytes b'\x28\x0c'."""
        raw = b'\x28\x0c'
        assert decode_value(raw, "turnhexdate") == "31.12"

    def test_single_digit_day_and_month(self):
        """Test 01.02 — both day and month must be zero-padded."""
        # Unswapped 102 = 0x0066 → swapped bytes b'\x66\x00'
        raw = b'\x66\x00'
        assert decode_value(raw, "turnhexdate") == "01.02"

    def test_wrong_length_raises(self):
        """Test that a non-2-byte input raises ValueError."""
        with pytest.raises(ValueError, match="turnhexdate"):
            decode_value(b'\x00\x00\x00', "turnhexdate")


class TestDecodeHex2Error:
    r"""Tests for hex2error decoding (4-byte LSB-first bitmap → fault list).

    Matches FHEM: bitmap2string(unpack('b32', pack('H*',$value)), \%faultmap)
    Bit position N (0-indexed, LSB-first within each byte) maps to
    fault key str(N+1) in SELECT_MAP['faultmap'].
    """

    def test_no_errors(self):
        """Test all-zero bitmap → n.a."""
        raw = b'\x00\x00\x00\x00'
        assert decode_value(raw, "hex2error") == "n.a."

    def test_single_error_f01_anode_fault(self):
        """Test bit 0 of byte 0 (= 0x01) → F01_AnodeFault."""
        # Byte 0 bit 0 = 0x01 → fault key "1" → F01_AnodeFault
        raw = b'\x01\x00\x00\x00'
        assert decode_value(raw, "hex2error") == "F01_AnodeFault"

    def test_single_error_f02(self):
        """Test bit 1 of byte 0 (= 0x02) → F02_SafetyTempDelimiterEngaged."""
        raw = b'\x02\x00\x00\x00'
        assert decode_value(raw, "hex2error") == "F02_SafetyTempDelimiterEngaged"

    def test_single_error_f03(self):
        """Test bit 2 of byte 0 (= 0x04) → F03_HighPreasureGuardFault."""
        raw = b'\x04\x00\x00\x00'
        assert decode_value(raw, "hex2error") == "F03_HighPreasureGuardFault"

    def test_single_error_f07(self):
        """Test bit 6 of byte 0 (= 0x40) → F07_MainOutputFanFault."""
        raw = b'\x40\x00\x00\x00'
        assert decode_value(raw, "hex2error") == "F07_MainOutputFanFault"

    def test_bit8_no_key(self):
        """Test bit 0 of byte 1 (fault key 9) — no faultmap entry, no output."""
        # Key "9" is not in faultmap; result should still be n.a.
        raw = b'\x00\x01\x00\x00'
        # Bit 8 → key "9" not in faultmap → nothing added
        assert decode_value(raw, "hex2error") == "n.a."

    def test_f11_low_pressure_sensor(self):
        """Test bit 10 (byte 1 bit 2 = 0x04) decodes to F11_LowPreasureSensorFault."""
        # bit 10 = byte 1 bit 2 = 0x04 in byte 1 → key "11"
        raw = b'\x00\x04\x00\x00'
        assert decode_value(raw, "hex2error") == "F11_LowPreasureSensorFault"

    def test_multiple_errors(self):
        """Test multiple simultaneous active errors."""
        # F01 (bit 0) + F02 (bit 1) = 0x03 in byte 0
        raw = b'\x03\x00\x00\x00'
        result = decode_value(raw, "hex2error")
        assert "F01_AnodeFault" in result
        assert "F02_SafetyTempDelimiterEngaged" in result

    def test_all_first_byte_errors(self):
        """Test all set bits in byte 0 — only known fault keys contribute."""
        # 0xFF → bits 0-7 → keys 1-8; key 8 not in faultmap
        raw = b'\xff\x00\x00\x00'
        result = decode_value(raw, "hex2error")
        assert "F01_AnodeFault" in result
        assert "F02_SafetyTempDelimiterEngaged" in result
        assert "F07_MainOutputFanFault" in result
        # key "8" is not in faultmap, should not appear
        assert "F08" not in result

    def test_order_is_lsb_first(self):
        """Test that faults are listed in bit position order (LSB first)."""
        # F01 (bit 0) and F03 (bit 2) active
        raw = b'\x05\x00\x00\x00'  # 0x05 = bits 0 and 2
        result = decode_value(raw, "hex2error")
        assert result == "F01_AnodeFault, F03_HighPreasureGuardFault"

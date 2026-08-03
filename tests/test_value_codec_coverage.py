"""Coverage tests for value_codec.py.

Covers THZValueCodec.encode_number/decode_number/encode_select/decode_select/
encode_switch/decode_switch, plus the module-level _dec_* helper functions
reached via decode_raw_value that are not exercised by
test_decode_value.py / test_decode_extended.py.
"""
import pytest

from custom_components.thz.value_codec import THZValueCodec, decode_raw_value


class TestEncodeNumber:
    """Tests for THZValueCodec.encode_number."""

    def test_0clean_encoding(self):
        result = THZValueCodec.encode_number(7.0, 1, "0clean")
        assert result == bytes([7])

    def test_standard_signed_int_encoding(self):
        # value 20.0 / step 0.5 = 40 -> 2-byte big-endian signed
        result = THZValueCodec.encode_number(20.0, 0.5, "hex2int")
        assert result == (40).to_bytes(2, byteorder="big", signed=True)

    def test_standard_negative_value_encoding(self):
        result = THZValueCodec.encode_number(-10.0, 0.5, "hex2int")
        assert result == (-20).to_bytes(2, byteorder="big", signed=True)

    def test_standard_step_one(self):
        result = THZValueCodec.encode_number(15.0, 1, "hex")
        assert result == (15).to_bytes(2, byteorder="big", signed=True)


class TestDecodeNumber:
    """Tests for THZValueCodec.decode_number."""

    def test_0clean_decoding(self):
        result = THZValueCodec.decode_number(bytes([9]), 1, "0clean")
        assert result == 9.0

    def test_standard_decoding_with_scaling(self):
        raw = (40).to_bytes(2, byteorder="big", signed=True)
        result = THZValueCodec.decode_number(raw, 0.5, "hex2int")
        assert result == 20.0

    def test_standard_decoding_negative(self):
        raw = (-20).to_bytes(2, byteorder="big", signed=True)
        result = THZValueCodec.decode_number(raw, 0.5, "hex2int")
        assert result == -10.0

    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError):
            THZValueCodec.decode_number(b"", 1, "hex2int")


class TestEncodeSelect:
    """Tests for THZValueCodec.encode_select."""

    def test_2opmode_single_byte_encoding(self):
        result = THZValueCodec.encode_select("automatic", "2opmode")
        assert result == bytes([11, 0])

    def test_standard_two_byte_encoding(self):
        result = THZValueCodec.encode_select("summer", "SomWinMode")
        assert result == (2).to_bytes(2, byteorder="big", signed=False)

    def test_unknown_decode_type_raises(self):
        with pytest.raises(ValueError, match="Unknown decode_type"):
            THZValueCodec.encode_select("anything", "not_a_real_type")

    def test_unknown_option_raises(self):
        with pytest.raises(ValueError, match="Invalid option"):
            THZValueCodec.encode_select("not_a_real_option", "2opmode")


class TestDecodeSelect:
    """Tests for THZValueCodec.decode_select."""

    def test_2opmode_decoding(self):
        result = THZValueCodec.decode_select(bytes([11, 0]), "2opmode")
        assert result == "automatic"

    def test_standard_two_byte_decoding(self):
        raw = (2).to_bytes(2, byteorder="big", signed=False)
        result = THZValueCodec.decode_select(raw, "SomWinMode")
        assert result == "summer"

    def test_somwinmode_zero_padding(self):
        raw = (1).to_bytes(2, byteorder="big", signed=False)
        result = THZValueCodec.decode_select(raw, "SomWinMode")
        assert result == "winter"

    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError, match="No data to decode"):
            THZValueCodec.decode_select(b"", "2opmode")

    def test_unknown_decode_type_raises(self):
        with pytest.raises(ValueError, match="Unknown decode_type"):
            THZValueCodec.decode_select(bytes([1, 0]), "not_a_real_type")

    def test_unmapped_value_returns_none(self):
        # "2opmode" reads only the first byte; 250 has no mapping.
        raw = bytes([250, 0])
        result = THZValueCodec.decode_select(raw, "2opmode")
        assert result is None


class TestEncodeDecodeSwitch:
    """Tests for THZValueCodec.encode_switch / decode_switch."""

    def test_encode_switch_on(self):
        assert THZValueCodec.encode_switch(True) == (1).to_bytes(2, "big")

    def test_encode_switch_off(self):
        assert THZValueCodec.encode_switch(False) == (0).to_bytes(2, "big")

    def test_decode_switch_on(self):
        assert THZValueCodec.decode_switch(bytes([0, 1])) is True

    def test_decode_switch_off(self):
        assert THZValueCodec.decode_switch(bytes([0, 0])) is False

    def test_decode_switch_empty_raises(self):
        with pytest.raises(ValueError, match="No data to decode"):
            THZValueCodec.decode_switch(b"")


class TestDecodeRawValueHelpers:
    """Tests for module-level _dec_* helpers reached via decode_raw_value."""

    def test_dec_hex2int_signed(self):
        raw = (-5).to_bytes(2, byteorder="big", signed=True)
        assert decode_raw_value(raw, "hex2int", 1.0) == -5

    def test_dec_hex_unsigned(self):
        raw = (200).to_bytes(2, byteorder="big")
        assert decode_raw_value(raw, "hex", 10.0) == 20.0

    def test_dec_esp_mant_valid(self):
        import struct

        raw = struct.pack(">f", 3.14159)
        result = decode_raw_value(raw, "esp_mant", 1.0)
        assert abs(result - 3.142) < 0.01

    def test_dec_esp_mant_invalid_length_raises(self):
        with pytest.raises(ValueError, match="Invalid esp_mant length"):
            decode_raw_value(b"\x01\x02", "esp_mant", 1.0)

    def test_dec_esp_mant_struct_error_wrapped_as_value_error(self, monkeypatch):
        """Force struct.unpack to raise struct.error and verify it is wrapped."""
        import struct

        from custom_components.thz import value_codec as codec_mod

        def _raise(*_args, **_kwargs):
            raise struct.error("bad format")

        monkeypatch.setattr(codec_mod.struct, "unpack", _raise)

        with pytest.raises(ValueError, match="Failed to decode esp_mant value"):
            decode_raw_value(b"\x01\x02\x03\x04", "esp_mant", 1.0)

    def test_dec_hexdate(self):
        raw = (1225).to_bytes(2, byteorder="big")  # 12.25
        assert decode_raw_value(raw, "hexdate", 1.0) == "12.25"

    def test_dec_clockdate_valid(self):
        raw = bytes([24, 3, 15])  # 2024-03-15
        assert decode_raw_value(raw, "clockdate", 1.0) == "2024-03-15"

    def test_dec_clockdate_invalid_length_raises(self):
        with pytest.raises(ValueError, match="Invalid clockdate length"):
            decode_raw_value(bytes([1, 2]), "clockdate", 1.0)

    def test_dec_somwinmode_known(self):
        raw = bytes([1])  # hex "01" -> winter
        assert decode_raw_value(raw, "somwinmode", 1.0) == "winter"

    def test_dec_somwinmode_unknown_returns_hex(self):
        raw = bytes([0xFF])
        assert decode_raw_value(raw, "somwinmode", 1.0) == "ff"

    def test_dec_weekday_known(self):
        raw = bytes([1])
        result = decode_raw_value(raw, "weekday", 1.0)
        assert isinstance(result, str)

    def test_dec_weekday_unknown_returns_key(self):
        raw = (999).to_bytes(2, byteorder="big")
        assert decode_raw_value(raw, "weekday", 1.0) == "999"

    def test_dec_opmodehc_known(self):
        raw = bytes([1])
        result = decode_raw_value(raw, "opmodehc", 1.0)
        assert isinstance(result, str)

    def test_dec_opmodehc_unknown_returns_key(self):
        raw = (999).to_bytes(2, byteorder="big")
        assert decode_raw_value(raw, "opmodehc", 1.0) == "999"

    def test_dec_party_time(self):
        raw = (120).to_bytes(2, byteorder="big")
        assert decode_raw_value(raw, "8party", 2.0) == 60.0

    def test_dec_faultmap_known(self):
        raw = bytes([1])
        result = decode_raw_value(raw, "faultmap", 1.0)
        assert result == "F01_AnodeFault"

    def test_dec_faultmap_unknown_returns_code_str(self):
        raw = (9999).to_bytes(2, byteorder="big")
        assert decode_raw_value(raw, "faultmap", 1.0) == "9999"

    def test_dec_hex2time(self):
        raw = (1230).to_bytes(2, byteorder="big")  # 0x04CE
        assert decode_raw_value(raw, "hex2time", 1.0) == "12:30"

    def test_dec_hex2time_midnight(self):
        raw = (0).to_bytes(2, byteorder="big")
        assert decode_raw_value(raw, "hex2time", 1.0) == "00:00"

    def test_dec_hex2error_no_faults(self):
        raw = bytes([0, 0, 0, 0])
        assert decode_raw_value(raw, "hex2error", 1.0) == "n.a."

    def test_dec_hex2error_bit0_active(self):
        # bit 0 of byte 0 -> fault key "1" -> F01_AnodeFault
        raw = bytes([0x01, 0, 0, 0])
        result = decode_raw_value(raw, "hex2error", 1.0)
        assert "F01_AnodeFault" in result

    def test_dec_hex2error_multiple_bits(self):
        # bit0 and bit1 of byte0 active -> faults 1 and 2
        raw = bytes([0x03, 0, 0, 0])
        result = decode_raw_value(raw, "hex2error", 1.0)
        assert "F01_AnodeFault" in result
        assert "F02_SafetyTempDelimiterEngaged" in result
        assert result.count(",") == 1

    def test_bit_prefix_dispatch(self):
        raw = bytes([0b00001000])  # bit3 set
        assert decode_raw_value(raw, "bit3", 1.0) is True
        assert decode_raw_value(raw, "bit0", 1.0) is False

    def test_nbit_prefix_dispatch(self):
        raw = bytes([0b00000001])  # bit0 set
        assert decode_raw_value(raw, "nbit0", 1.0) is False
        assert decode_raw_value(raw, "nbit1", 1.0) is True

    def test_unknown_decode_type_returns_hex(self):
        raw = bytes([0xAB, 0xCD])
        assert decode_raw_value(raw, "totally_unknown_type", 1.0) == "abcd"

    def test_default_factor(self):
        raw = (100).to_bytes(2, byteorder="big")
        assert decode_raw_value(raw, "hex") == 100

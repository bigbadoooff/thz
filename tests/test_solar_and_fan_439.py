"""Tests for the solar circuit ("pxx16") and fan status ("pxxE8") blocks (fw 4.39/5.39).

These were entirely unported gaps found via a systematic audit against
FHEM's 00_THZ.pm: firmware 4.39/5.39 (and everything read via the shared
readings_map_439 base) had no equivalent of FHEM's "sSol" (command 16,
solar-circuit temperatures/runtime) or "sFan" (command E8, live fan
speed/airflow/power) at all, distinct from the already-implemented
p80EnableSolar (on/off switch), solar_pump (running-status bit), and the
p07/08/09/12/43-46/99 fan-stage *setting* write entities.
"""
import pytest

from custom_components.thz.register_maps import readings_map_439
from custom_components.thz.value_codec import decode_raw_value


class TestSolarBlockDefinition:
    """Structural tests for the pxx16 (sSol) block."""

    def test_pxx16_block_exists(self):
        assert "pxx16" in readings_map_439.REGISTER_MAP

    def test_pxx16_has_six_entries(self):
        entries = readings_map_439.REGISTER_MAP["pxx16"]
        assert len(entries) == 6

    @pytest.mark.parametrize(
        "index,name,offset,length,decode,factor",
        [
            (0, "collectorTemp", 4, 4, "hex2int", 10),
            (1, "dhwTemp", 8, 4, "hex2int", 10),
            (2, "flowTemp", 12, 4, "hex2int", 10),
            (3, "edSolPump", 16, 2, "hex2int", 1),
            (4, "out", 26, 4, "raw", 1),
            (5, "status", 30, 2, "raw", 1),
        ],
    )
    def test_entries_match_fhem_16sol(
        self, index, name, offset, length, decode, factor
    ):
        entries = readings_map_439.REGISTER_MAP["pxx16"]
        entry_name, entry_offset, entry_length, entry_decode, entry_factor = (
            entries[index][:5]
        )
        assert entry_name.strip().rstrip(":") == name
        assert (entry_offset, entry_length, entry_decode, entry_factor) == (
            offset,
            length,
            decode,
            factor,
        )


class TestFanBlockDefinition:
    """Structural tests for the pxxE8 (sFan) block."""

    def test_pxxe8_block_exists(self):
        assert "pxxE8" in readings_map_439.REGISTER_MAP

    def test_pxxe8_has_six_entries(self):
        entries = readings_map_439.REGISTER_MAP["pxxE8"]
        assert len(entries) == 6

    @pytest.mark.parametrize(
        "index,name,offset,length",
        [
            (0, "inputFanSpeed", 58, 2),
            (1, "outputFanSpeed", 60, 2),
            (2, "pFanstageXAirflowInlet", 62, 4),
            (3, "pFanstageXAirflowOutlet", 66, 4),
            (4, "inputFanPower", 70, 2),
            (5, "outputFanPower", 72, 2),
        ],
    )
    def test_entries_match_fhem_e8fan(self, index, name, offset, length):
        entries = readings_map_439.REGISTER_MAP["pxxE8"]
        entry_name, entry_offset, entry_length, entry_decode, _factor = (
            entries[index][:5]
        )
        assert entry_name.strip().rstrip(":") == name
        assert (entry_offset, entry_length, entry_decode) == (offset, length, "hex")


class TestSolarEndToEndDecode:
    """End-to-end decode of a synthetic pxx16 device response."""

    @staticmethod
    def _extract(
        message_hex: str,
        offset_nibbles: int,
        length_nibbles: int,
        decode_type: str,
        factor: float,
    ):
        byte_offset = offset_nibbles // 2
        byte_length = (length_nibbles + 1) // 2
        raw = bytes.fromhex(message_hex)[byte_offset : byte_offset + byte_length]
        return decode_raw_value(raw, decode_type, factor)

    def _decode_block(self, message: bytes) -> dict:
        message_hex = message.hex()
        entries = readings_map_439.REGISTER_MAP["pxx16"]
        results = {}
        for entry in entries:
            name, offset, length, decode, factor = entry[:5]
            results[name.strip().rstrip(":")] = self._extract(
                message_hex, offset, length, decode, factor
            )
        return results

    def test_typical_solar_reading(self):
        raw = bytearray(16)
        raw[2], raw[3] = 0x01, 0xC8  # collectorTemp = 456 / 10 = 45.6
        raw[4], raw[5] = 0x01, 0xF6  # dhwTemp = 502 / 10 = 50.2
        raw[6], raw[7] = 0x01, 0xE3  # flowTemp = 483 / 10 = 48.3
        raw[8] = 0x78  # edSolPump = 120
        raw[13], raw[14] = 0xAB, 0xCD  # out (raw)
        raw[15] = 0x02  # status (raw)

        results = self._decode_block(bytes(raw))

        assert results["collectorTemp"] == pytest.approx(45.6)
        assert results["dhwTemp"] == pytest.approx(50.2)
        assert results["flowTemp"] == pytest.approx(48.3)
        assert results["edSolPump"] == 120
        assert results["out"] == "abcd"
        assert results["status"] == "02"


class TestFanEndToEndDecode:
    """End-to-end decode of a synthetic pxxE8 device response."""

    @staticmethod
    def _extract(
        message_hex: str,
        offset_nibbles: int,
        length_nibbles: int,
        decode_type: str,
        factor: float,
    ):
        byte_offset = offset_nibbles // 2
        byte_length = (length_nibbles + 1) // 2
        raw = bytes.fromhex(message_hex)[byte_offset : byte_offset + byte_length]
        return decode_raw_value(raw, decode_type, factor)

    def _decode_block(self, message: bytes) -> dict:
        message_hex = message.hex()
        entries = readings_map_439.REGISTER_MAP["pxxE8"]
        results = {}
        for entry in entries:
            name, offset, length, decode, factor = entry[:5]
            results[name.strip().rstrip(":")] = self._extract(
                message_hex, offset, length, decode, factor
            )
        return results

    def test_typical_fan_reading(self):
        raw = bytearray(37)
        raw[29] = 50  # inputFanSpeed
        raw[30] = 45  # outputFanSpeed
        raw[31], raw[32] = 0x00, 0xB4  # pFanstageXAirflowInlet = 180 m3/h
        raw[33], raw[34] = 0x00, 0xAF  # pFanstageXAirflowOutlet = 175 m3/h
        raw[35] = 60  # inputFanPower
        raw[36] = 55  # outputFanPower

        results = self._decode_block(bytes(raw))

        assert results["inputFanSpeed"] == 50
        assert results["outputFanSpeed"] == 45
        assert results["pFanstageXAirflowInlet"] == 180
        assert results["pFanstageXAirflowOutlet"] == 175
        assert results["inputFanPower"] == 60
        assert results["outputFanPower"] == 55

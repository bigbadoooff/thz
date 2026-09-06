"""Tests for the firmware 4.39/5.39 fault log ("pxxD1") register block.

Regression/feature coverage for closing a gap where this fork only ported
FHEM's fault-log read ("D1last") for firmware 2.06 (register_map_206's
"pxxD1" block); firmware 4.39/5.39 only had the write-side
"zResetLast10errors" button with no matching read-back, so there was no way
to see what a fault actually was before (or instead of) clearing it.

Firmware 4.39/5.39 differ from 2.06 in two ways for this block, both taken
verbatim from FHEM's "D1last" parsing table (as opposed to "D1last206"):
  - fault*CODE is 1 byte (length 2 nibbles) instead of 2 bytes (length 4).
  - fault*TIME/fault*DATE have their two bytes swapped relative to the plain
    "hex2time"/"hexdate" decoders, requiring the "turnhex2time"/"turnhexdate"
    decode types (see value_codec.py).
"""
import pytest

from custom_components.thz.register_maps import readings_map_439
from custom_components.thz.value_codec import decode_raw_value


class TestFaultLogBlockDefinition:
    """Structural tests for the pxxD1 block in readings_map_439.REGISTER_MAP."""

    def test_pxxd1_block_exists(self):
        """Test that the fault-log block is registered for firmware 4.39."""
        assert "pxxD1" in readings_map_439.REGISTER_MAP

    def test_pxxd1_has_thirteen_entries(self):
        """Test entry count: number_of_faults + 4 faults * (CODE, TIME, DATE)."""
        entries = readings_map_439.REGISTER_MAP["pxxD1"]
        assert len(entries) == 13

    def test_number_of_faults_entry(self):
        """Test the number_of_faults entry matches FHEM's D1last offset/type."""
        entries = readings_map_439.REGISTER_MAP["pxxD1"]
        name, offset, length, decode, factor = entries[0][:5]
        assert name.strip().rstrip(":") == "number_of_faults"
        assert (offset, length, decode) == (4, 2, "hex")

    @pytest.mark.parametrize(
        "index,fault_num,code_offset,time_offset,date_offset",
        [
            (1, 0, 8, 12, 16),
            (4, 1, 20, 24, 28),
            (7, 2, 32, 36, 40),
            (10, 3, 44, 48, 52),
        ],
    )
    def test_fault_offsets_match_fhem_d1last(
        self, index, fault_num, code_offset, time_offset, date_offset
    ):
        """Offsets/lengths/decode-types must match FHEM's D1last table verbatim."""
        entries = readings_map_439.REGISTER_MAP["pxxD1"]
        code_name, code_off, code_len, code_decode, _ = entries[index][:5]
        time_name, time_off, time_len, time_decode, _ = entries[index + 1][:5]
        date_name, date_off, date_len, date_decode, _ = entries[index + 2][:5]

        assert code_name.strip().rstrip(":") == f"fault{fault_num}CODE"
        assert (code_off, code_len, code_decode) == (code_offset, 2, "faultmap")

        assert time_name.strip().rstrip(":") == f"fault{fault_num}TIME"
        assert (time_off, time_len, time_decode) == (
            time_offset,
            4,
            "turnhex2time",
        )

        assert date_name.strip().rstrip(":") == f"fault{fault_num}DATE"
        assert (date_off, date_len, date_decode) == (date_offset, 4, "turnhexdate")


class TestFaultLogEndToEndDecode:
    """End-to-end decode of a synthetic pxxD1 device response.

    Mirrors the nibble-offset -> byte-offset conversion sensor.py applies
    (offset // 2, (length + 1) // 2) so this test would catch a regression
    in either the register map offsets or the decode functions, not just
    one in isolation.
    """

    @staticmethod
    def _extract(
        message_hex: str, offset_nibbles: int, length_nibbles: int, decode_type: str
    ):
        byte_offset = offset_nibbles // 2
        byte_length = (length_nibbles + 1) // 2
        raw = bytes.fromhex(message_hex)[byte_offset : byte_offset + byte_length]
        return decode_raw_value(raw, decode_type, 1)

    def _decode_block(self, message: bytes) -> dict:
        message_hex = message.hex()
        entries = readings_map_439.REGISTER_MAP["pxxD1"]
        results = {}
        for entry in entries:
            name, offset, length, decode, factor = entry[:5]
            results[name.strip().rstrip(":")] = self._extract(
                message_hex, offset, length, decode
            )
        return results

    def test_single_active_fault(self):
        """One active fault (fault0), the other three slots all-zero/n.a."""
        raw = bytearray(28)
        raw[2] = 0x01  # number_of_faults = 1
        raw[4] = 0x03  # fault0CODE = 3 -> F03_HighPreasureGuardFault
        raw[6], raw[7] = 0xCE, 0x04  # fault0TIME swapped -> 12:30
        raw[8], raw[9] = 0xF5, 0x01  # fault0DATE swapped -> 05.01
        # bytes 10-27 (fault1..fault3) stay zero -> n.a. / 00:00 / 00.00

        results = self._decode_block(bytes(raw))

        assert results["number_of_faults"] == 1
        assert results["fault0CODE"] == "F03_HighPreasureGuardFault"
        assert results["fault0TIME"] == "12:30"
        assert results["fault0DATE"] == "05.01"
        assert results["fault1CODE"] == "n.a."
        assert results["fault1TIME"] == "00:00"
        assert results["fault1DATE"] == "00.00"

    def test_all_faults_populated(self):
        """All four fault slots populated with distinct code/time/date values."""
        raw = bytearray(28)
        raw[2] = 0x04  # number_of_faults = 4

        raw[4] = 0x01  # fault0CODE -> F01_AnodeFault
        raw[6], raw[7] = 0xB0, 0x04  # fault0TIME swapped -> 12:00
        raw[8], raw[9] = 0x28, 0x0C  # fault0DATE swapped -> 31.12

        raw[10] = 0x02  # fault1CODE -> F02_SafetyTempDelimiterEngaged
        raw[12], raw[13] = 0x29, 0x09  # fault1TIME swapped -> 23:45
        raw[14], raw[15] = 0x66, 0x00  # fault1DATE swapped -> 01.02

        raw[16] = 0x24  # fault2CODE (36) -> F36_MinFlowRate
        raw[18], raw[19] = 0x01, 0x00  # fault2TIME swapped -> 00:01
        raw[20], raw[21] = 0xF5, 0x01  # fault2DATE swapped -> 05.01

        raw[22] = 0x34  # fault3CODE (52) -> F52_SensorCondenserOutlet
        raw[24], raw[25] = 0x76, 0x02  # fault3TIME swapped -> 06:30
        raw[26], raw[27] = 0x00, 0x00  # fault3DATE -> 00.00

        results = self._decode_block(bytes(raw))

        assert results["number_of_faults"] == 4
        assert results["fault0CODE"] == "F01_AnodeFault"
        assert results["fault0TIME"] == "12:00"
        assert results["fault0DATE"] == "31.12"
        assert results["fault1CODE"] == "F02_SafetyTempDelimiterEngaged"
        assert results["fault1TIME"] == "23:45"
        assert results["fault1DATE"] == "01.02"
        assert results["fault2CODE"] == "F36_MinFlowRate"
        assert results["fault2TIME"] == "00:01"
        assert results["fault2DATE"] == "05.01"
        assert results["fault3CODE"] == "F52_SensorCondenserOutlet"
        assert results["fault3TIME"] == "06:30"
        assert results["fault3DATE"] == "00.00"

    def test_no_faults(self):
        """An all-zero response decodes as zero faults, no crash."""
        raw = bytes(28)
        results = self._decode_block(raw)
        assert results["number_of_faults"] == 0
        assert results["fault0CODE"] == "n.a."

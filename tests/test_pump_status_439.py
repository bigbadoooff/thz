"""Tests for live pump-running status (the "pxxFB" block) on firmware 4.39/5.39.

Regression/feature coverage for a gap surfaced by a user report of the
zPumpHC/zPumpDHW technician "force" select entities showing "unknown" --
those are one-shot write-only commands with no readable state (matching
FHEM's own model, which defines no GET counterpart for them either), so
"unknown" there is expected. What the user actually wanted was the genuine,
read-only "is this pump currently running" status, which firmware 2.06/2.14
already expose via their own pxxFB block but firmware 4.39/5.39 never had
wired up in this fork, even though the FB command is already read for the
COP calculation (see cop_sensor.py) and the offsets are well documented in
FHEM's "FBglob" parsing table.
"""
import pytest

from custom_components.thz.register_maps import readings_map_439
from custom_components.thz.value_codec import decode_raw_value


class TestPumpStatusBlockDefinition:
    """Structural tests for the pxxFB block in readings_map_439.REGISTER_MAP."""

    def test_pxxfb_block_exists(self):
        """Test that the pump-status block is registered for firmware 4.39."""
        assert "pxxFB" in readings_map_439.REGISTER_MAP

    def test_pxxfb_has_three_entries(self):
        """Test entry count: dhwPump, heatingCircuitPump, solarPump."""
        entries = readings_map_439.REGISTER_MAP["pxxFB"]
        assert len(entries) == 3

    @pytest.mark.parametrize(
        "index,name,bit",
        [
            (0, "dhwPump", "bit0"),
            (1, "heatingCircuitPump", "bit1"),
            (2, "solarPump", "bit3"),
        ],
    )
    def test_entries_match_fhem_fbglob(self, index, name, bit):
        """Offsets/bits must match FHEM's "FBglob" table verbatim."""
        entries = readings_map_439.REGISTER_MAP["pxxFB"]
        entry_name, offset, length, decode, _factor = entries[index][:5]
        assert entry_name.strip().rstrip(":") == name
        assert (offset, length, decode) == (44, 1, bit)


class TestPumpStatusEndToEndDecode:
    """End-to-end decode of a synthetic pxxFB response byte.

    Mirrors both conversions binary_sensor.py applies for bit-typed entries:
    nibble-offset -> byte-offset (offset // 2), and the even-offset ->
    high-nibble bit shift (bit N becomes bit N+4) since all three entries
    sit at nibble offset 44, an even offset, i.e. byte 22's high nibble.
    """

    @staticmethod
    def _effective_decode(decode_type: str, offset: int, length: int) -> str:
        if length == 1 and offset % 2 == 0 and decode_type.startswith("bit"):
            bitnum = int(decode_type[3:])
            return f"bit{bitnum + 4}"
        return decode_type

    def _decode_block(self, byte_at_offset22: int) -> dict:
        # nibble offset 44 // 2 = byte offset 22
        message = bytearray(23)
        message[22] = byte_at_offset22
        message_hex = bytes(message).hex()

        entries = readings_map_439.REGISTER_MAP["pxxFB"]
        results = {}
        for entry in entries:
            name, offset, length, decode, factor = entry[:5]
            byte_offset = offset // 2
            byte_length = (length + 1) // 2
            raw = bytes.fromhex(message_hex)[byte_offset : byte_offset + byte_length]
            effective = self._effective_decode(decode, offset, length)
            results[name.strip().rstrip(":")] = decode_raw_value(raw, effective, factor)
        return results

    def test_all_pumps_off(self):
        """Test byte 0x00 -> all three pumps report not running."""
        results = self._decode_block(0x00)
        assert results["dhwPump"] is False
        assert results["heatingCircuitPump"] is False
        assert results["solarPump"] is False

    def test_dhw_pump_running(self):
        """Test only bit4 (dhwPump's shifted bit0) set -> byte 0x10."""
        results = self._decode_block(0x10)
        assert results["dhwPump"] is True
        assert results["heatingCircuitPump"] is False
        assert results["solarPump"] is False

    def test_heating_circuit_pump_running(self):
        """Test only bit5 (heatingCircuitPump's shifted bit1) set -> byte 0x20."""
        results = self._decode_block(0x20)
        assert results["dhwPump"] is False
        assert results["heatingCircuitPump"] is True
        assert results["solarPump"] is False

    def test_solar_pump_running(self):
        """Test only bit7 (solarPump's shifted bit3) set -> byte 0x80."""
        results = self._decode_block(0x80)
        assert results["dhwPump"] is False
        assert results["heatingCircuitPump"] is False
        assert results["solarPump"] is True

    def test_all_pumps_running(self):
        """Test bits 4, 5, and 7 all set -> byte 0xB0."""
        results = self._decode_block(0xB0)
        assert results["dhwPump"] is True
        assert results["heatingCircuitPump"] is True
        assert results["solarPump"] is True

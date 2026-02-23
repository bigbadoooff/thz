"""Tests for FHEM nibble-offset convention fix (issue #85).

In the FHEM THZ register maps, offsets are nibble (4-bit) positions in the
raw hex string.  An even offset selects the HIGH nibble (bits 4-7) of a byte
and an odd offset selects the LOW nibble (bits 0-3).  When the code converts
these to byte offsets with ``offset // 2``, an even and the immediately
following odd offset both map to the SAME byte.

Before the fix, bit operations (e.g. ``bit0`` at even offset 44) accidentally
read the LOW nibble instead of the HIGH nibble, producing wrong values.  For
example, ``dhwPump`` (offset 44, bit0) was always reading bit0 of the LOW
nibble (which belongs to mixerOpen) instead of bit0 of the HIGH nibble, so the
pump sensor showed False regardless of actual pump state.

The fix: for a single-nibble register at an EVEN offset, the bit number is
shifted up by 4 to access the correct (high) nibble of the byte.
"""

from custom_components.thz.sensor import decode_value


class TestNibbleOffsetConvention:
    """Test the FHEM nibble-offset bit-shift logic.

    The fixture byte value 0xA5 (binary 1010_0101) is used to verify
    that even-offset registers read the HIGH nibble (0xA = 1010) and
    odd-offset registers read the LOW nibble (0x5 = 0101).
    """

    # 0xA5 = 1010 0101:
    #   HIGH nibble (bits 7-4): bit4=0 bit5=1 bit6=0 bit7=1  (0xA = 1010)
    #   LOW  nibble (bits 3-0): bit0=1 bit1=0 bit2=1 bit3=0  (0x5 = 0101)

    BYTE = bytes([0xA5])

    # --- HIGH nibble (even offset, bits shifted +4) ---

    def test_even_offset_bit0_reads_high_nibble_bit0(self):
        """bit0 at even offset (shifted to bit4) → HIGH nibble bit0 = 0."""
        # dhwPump style: offset 44 (even), bit0 → effective bit4
        # 0xA = 1010: bit0 (position 4 of byte) = 0
        assert decode_value(self.BYTE, "bit4") is False

    def test_even_offset_bit1_reads_high_nibble_bit1(self):
        """bit1 at even offset (shifted to bit5) → HIGH nibble bit1 = 1."""
        # 0xA = 1010: bit1 (position 5 of byte) = 1
        assert decode_value(self.BYTE, "bit5") is True

    def test_even_offset_bit2_reads_high_nibble_bit2(self):
        """bit2 at even offset (shifted to bit6) → HIGH nibble bit2 = 0."""
        # 0xA = 1010: bit2 (position 6 of byte) = 0
        assert decode_value(self.BYTE, "bit6") is False

    def test_even_offset_bit3_reads_high_nibble_bit3(self):
        """bit3 at even offset (shifted to bit7) → HIGH nibble bit3 = 1."""
        # 0xA = 1010: bit3 (position 7 of byte) = 1
        assert decode_value(self.BYTE, "bit7") is True

    # --- LOW nibble (odd offset, bits unchanged) ---

    def test_odd_offset_bit0_reads_low_nibble_bit0(self):
        """bit0 at odd offset (unchanged) → LOW nibble bit0 = 1."""
        # mixerOpen style: offset 45 (odd), bit0 stays bit0
        # 0x5 = 0101: bit0 = 1
        assert decode_value(self.BYTE, "bit0") is True

    def test_odd_offset_bit1_reads_low_nibble_bit1(self):
        """bit1 at odd offset (unchanged) → LOW nibble bit1 = 0."""
        # 0x5 = 0101: bit1 = 0
        assert decode_value(self.BYTE, "bit1") is False

    def test_odd_offset_bit2_reads_low_nibble_bit2(self):
        """bit2 at odd offset (unchanged) → LOW nibble bit2 = 1."""
        # 0x5 = 0101: bit2 = 1
        assert decode_value(self.BYTE, "bit2") is True

    def test_odd_offset_bit3_reads_low_nibble_bit3(self):
        """bit3 at odd offset (unchanged) → LOW nibble bit3 = 0."""
        # 0x5 = 0101: bit3 = 0
        assert decode_value(self.BYTE, "bit3") is False


class TestNibbleOffsetEffectiveDecodeLogic:
    """Test that the effective_decode calculation in sensor setup is correct.

    This mirrors the logic applied in async_setup_entry before creating sensor
    entries.
    """

    def _effective_decode(self, offset: int, length: int, decode_type: str) -> str:
        """Replicate the sensor setup nibble-offset logic."""
        if length == 1 and offset % 2 == 0:
            if decode_type.startswith("bit") and not decode_type.startswith("nbit"):
                bitnum = int(decode_type[3:])
                return f"bit{bitnum + 4}"
            elif decode_type.startswith("nbit"):
                bitnum = int(decode_type[4:])
                return f"nbit{bitnum + 4}"
        return decode_type

    # --- Even offsets: bit number must be shifted +4 ---

    def test_dhwPump_offset44_bit0_becomes_bit4(self):
        """dhwPump at offset 44 (even), length 1, bit0 → bit4."""
        assert self._effective_decode(44, 1, "bit0") == "bit4"

    def test_heatingCircuitPump_offset44_bit1_becomes_bit5(self):
        """heatingCircuitPump at offset 44 (even), bit1 → bit5."""
        assert self._effective_decode(44, 1, "bit1") == "bit5"

    def test_solarPump_offset44_bit3_becomes_bit7(self):
        """solarPump at offset 44 (even), bit3 → bit7."""
        assert self._effective_decode(44, 1, "bit3") == "bit7"

    def test_even_offset_nbit0_becomes_nbit4(self):
        """nbit0 at even offset → nbit4."""
        assert self._effective_decode(48, 1, "nbit0") == "nbit4"

    def test_even_offset_nbit1_becomes_nbit5(self):
        """nbit1 at even offset → nbit5."""
        assert self._effective_decode(48, 1, "nbit1") == "nbit5"

    # --- Odd offsets: bit number unchanged ---

    def test_mixerOpen_offset45_bit0_unchanged(self):
        """mixerOpen at offset 45 (odd), bit0 → unchanged."""
        assert self._effective_decode(45, 1, "bit0") == "bit0"

    def test_mixerClosed_offset45_bit1_unchanged(self):
        """mixerClosed at offset 45 (odd), bit1 → unchanged."""
        assert self._effective_decode(45, 1, "bit1") == "bit1"

    def test_heatPipeValve_offset45_bit2_unchanged(self):
        """heatPipeValve at offset 45 (odd), bit2 → unchanged."""
        assert self._effective_decode(45, 1, "bit2") == "bit2"

    def test_compressor_offset47_bit3_unchanged(self):
        """compressor at offset 47 (odd), bit3 → unchanged."""
        assert self._effective_decode(47, 1, "bit3") == "bit3"

    # --- Multi-nibble registers: no change regardless of offset parity ---

    def test_length2_even_offset_not_shifted(self):
        """Multi-nibble (length > 1) registers are never shifted."""
        assert self._effective_decode(44, 2, "bit0") == "bit0"

    def test_hex2int_even_offset_not_shifted(self):
        """Non-bit decode types are never shifted."""
        assert self._effective_decode(8, 4, "hex2int") == "hex2int"

    def test_hex_even_offset_not_shifted(self):
        """hex decode type is never shifted."""
        assert self._effective_decode(50, 4, "hex") == "hex"

    # --- Boundary check: bit numbers preserved after shift ---

    def test_bit0_shifts_to_bit4_not_bit3_or_bit5(self):
        """Exactly +4 shift for bit0."""
        result = self._effective_decode(44, 1, "bit0")
        assert result == "bit4"
        assert result != "bit3"
        assert result != "bit5"


class TestPumpSensorsReadCorrectBits:
    """Verify the pump sensors in pxxFB read from the correct byte/bit positions.

    This test uses a synthetic pxxFB payload to confirm that dhwPump,
    heatingCircuitPump, and solarPump are decoded from the HIGH nibble of
    byte 22 (nibble offset 44), while mixerOpen/mixerClosed are decoded from
    the LOW nibble of the same byte (nibble offset 45).
    """

    def _make_payload(self, byte22_value: int, payload_size: int = 60) -> bytes:
        """Build a synthetic payload with the given value at byte 22."""
        buf = bytearray(payload_size)
        buf[22] = byte22_value
        return bytes(buf)

    def test_dhwPump_on_reads_high_nibble_bit0(self):
        """dhwPump is on when bit4 of byte 22 is set (HIGH nibble, bit0 after +4 shift)."""
        # Set bit4: 0x10 = 0001_0000
        payload = self._make_payload(0x10)
        raw = payload[22:23]
        assert decode_value(raw, "bit4") is True

    def test_dhwPump_off_when_only_low_nibble_set(self):
        """dhwPump reads False when only the LOW nibble is set (old bug: would read True)."""
        # Set bit0 (low nibble) only: 0x01 = 0000_0001
        payload = self._make_payload(0x01)
        raw = payload[22:23]
        # Old bug: decode_value(raw, "bit0") would return True (wrong!)
        # New correct behaviour: decode_value(raw, "bit4") returns False
        assert decode_value(raw, "bit4") is False
        # And the low nibble bit0 correctly reflects mixerOpen state
        assert decode_value(raw, "bit0") is True

    def test_heatingCircuitPump_on_reads_high_nibble_bit1(self):
        """heatingCircuitPump is on when bit5 of byte 22 is set."""
        # Set bit5: 0x20 = 0010_0000
        payload = self._make_payload(0x20)
        raw = payload[22:23]
        assert decode_value(raw, "bit5") is True

    def test_both_pump_and_mixer_independent(self):
        """Pump and mixer bits are independent within the same byte."""
        # Set both high nibble bit0 (dhwPump=1) and low nibble bit1 (mixerClosed=1)
        # 0x12 = 0001_0010: bit4=1 (dhwPump=on), bit1=1 (mixerClosed=on)
        payload = self._make_payload(0x12)
        raw = payload[22:23]
        # dhwPump: bit4 = 1 (on)
        assert decode_value(raw, "bit4") is True
        # heatingCircuitPump: bit5 = 0 (off)
        assert decode_value(raw, "bit5") is False
        # mixerOpen: bit0 = 0 (closed)
        assert decode_value(raw, "bit0") is False
        # mixerClosed: bit1 = 1 (closed)
        assert decode_value(raw, "bit1") is True

"""Tests for THZ protocol functions."""

from custom_components.thz.thz_device import THZDevice


class TestChecksumCalculation:
    """Tests for thz_checksum function."""

    def test_simple_checksum(self):
        """Test checksum calculation for simple data."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x00\x00\xfb'
        checksum = device.thz_checksum(data)
        # Sum: 0x01 + 0x00 + 0xfb (skip index 2) = 0xfc
        assert checksum == b'\xfc'

    def test_checksum_with_overflow(self):
        """Test checksum calculation with modulo 256."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\xff\xff\x00\xff'
        checksum = device.thz_checksum(data)
        # Sum: 0xff + 0xff + 0xff = 0x2fd, mod 256 = 0xfd
        assert checksum == b'\xfd'

    def test_checksum_zero_data(self):
        """Test checksum of zeros."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x00\x00\x00\x00'
        checksum = device.thz_checksum(data)
        assert checksum == b'\x00'

    def test_checksum_skips_index_2(self):
        """Test that index 2 is skipped in checksum calculation."""
        device = THZDevice(connection="usb", port="/dev/null")
        # Two data sets identical except at index 2
        data1 = b'\x01\x02\x00\x04'
        data2 = b'\x01\x02\xff\x04'
        checksum1 = device.thz_checksum(data1)
        checksum2 = device.thz_checksum(data2)
        # Should be same because index 2 is skipped
        assert checksum1 == checksum2


class TestEscaping:
    """Tests for escape and unescape functions."""

    def test_escape_0x10(self):
        """Test that 0x10 is escaped to 0x10 0x10."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10'
        escaped = device.escape(data)
        assert escaped == b'\x10\x10'

    def test_escape_0x2b(self):
        """Test that 0x2B is escaped to 0x2B 0x18."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x2b'
        escaped = device.escape(data)
        assert escaped == b'\x2b\x18'

    def test_escape_multiple_0x10(self):
        """Test escaping multiple 0x10 bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10\x10'
        escaped = device.escape(data)
        assert escaped == b'\x10\x10\x10\x10'

    def test_escape_mixed_data(self):
        """Test escaping data with mixed special bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x10\x2b\x03'
        escaped = device.escape(data)
        assert escaped == b'\x01\x10\x10\x2b\x18\x03'

    def test_escape_no_special_bytes(self):
        """Test that data without special bytes is unchanged."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x02\x03\x04'
        escaped = device.escape(data)
        assert escaped == data

    def test_unescape_0x10(self):
        """Test that 0x10 0x10 is unescaped to 0x10."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10\x10'
        unescaped = device.unescape(data)
        assert unescaped == b'\x10'

    def test_unescape_0x2b(self):
        """Test that 0x2B 0x18 is unescaped to 0x2B."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x2b\x18'
        unescaped = device.unescape(data)
        assert unescaped == b'\x2b'

    def test_unescape_mixed_data(self):
        """Test unescaping data with mixed escaped bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x10\x10\x2b\x18\x03'
        unescaped = device.unescape(data)
        assert unescaped == b'\x01\x10\x2b\x03'

    def test_round_trip_escape_unescape(self):
        """Test that escape and unescape are inverse operations."""
        device = THZDevice(connection="usb", port="/dev/null")
        original = b'\x01\x10\x2b\x03'
        escaped = device.escape(original)
        unescaped = device.unescape(escaped)
        assert unescaped == original


class TestTelegramConstruction:
    """Tests for construct_telegram function."""

    def test_basic_telegram(self):
        """Test constructing a basic telegram."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b'\xfb'
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x5a'

        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)

        # Should be: header + escaped(checksum + addr_bytes) + footer
        # 0x5a and 0xfb don't need escaping
        assert telegram == b'\x01\x00\x5a\xfb\x10\x03'

    def test_telegram_with_escaping(self):
        """Test telegram construction with bytes that need escaping."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b'\x10'  # Needs escaping
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x20'

        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)

        # checksum + addr_bytes = b'\x20\x10'
        # After escaping: b'\x20\x10\x10'
        assert telegram == b'\x01\x00\x20\x10\x10\x10\x03'

    def test_telegram_with_0x2b(self):
        """Test telegram construction with 0x2B that needs escaping."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b'\x2b'  # Needs escaping to 0x2B 0x18
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x30'

        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)

        # checksum + addr_bytes = b'\x30\x2b'
        # After escaping: b'\x30\x2b\x18'
        assert telegram == b'\x01\x00\x30\x2b\x18\x10\x03'


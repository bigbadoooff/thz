"""Additional comprehensive protocol and device tests."""

import pytest

from custom_components.thz.thz_device import THZDevice


class TestTHZDeviceProtocolExtended:
    """Extended protocol tests for THZ device."""

    def test_checksum_all_zeros(self):
        """Test checksum with all zero bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x00\x00\x00\x00\x00\x00'
        checksum = device.thz_checksum(data)
        assert checksum == b'\x00'

    def test_checksum_all_ones(self):
        """Test checksum with all 0xFF bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        # All 0xFF except index 2
        data = b'\xff\xff\x00\xff\xff'
        checksum = device.thz_checksum(data)
        # Sum: 0xff * 4 = 0x3fc, mod 256 = 0xfc
        assert checksum == b'\xfc'

    def test_checksum_single_byte(self):
        """Test checksum with single byte."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x42'
        checksum = device.thz_checksum(data)
        # Only one byte, index 0, no index 2 to skip
        assert checksum == b'\x42'

    def test_checksum_two_bytes(self):
        """Test checksum with two bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x42\x10'
        checksum = device.thz_checksum(data)
        # Sum: 0x42 + 0x10 = 0x52
        assert checksum == b'\x52'

    def test_checksum_index_2_really_skipped(self):
        """Verify index 2 is completely ignored in checksum."""
        device = THZDevice(connection="usb", port="/dev/null")

        # Two arrays identical except at index 2
        data1 = b'\x01\x02\x00\x04\x05'
        data2 = b'\x01\x02\xff\x04\x05'

        checksum1 = device.thz_checksum(data1)
        checksum2 = device.thz_checksum(data2)

        # Should produce same checksum
        assert checksum1 == checksum2
        # Verify calculation: 0x01 + 0x02 + 0x04 + 0x05 = 0x0c
        assert checksum1 == b'\x0c'

    def test_escape_no_special_bytes(self):
        """Test escape with no special bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x02\x03\x04\x05'
        escaped = device.escape(data)
        assert escaped == data

    def test_escape_empty_bytes(self):
        """Test escape with empty bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b''
        escaped = device.escape(data)
        assert escaped == b''

    def test_escape_only_0x10(self):
        """Test escape with only 0x10 bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10\x10\x10'
        escaped = device.escape(data)
        # Each 0x10 becomes 0x10 0x10
        assert escaped == b'\x10\x10\x10\x10\x10\x10'

    def test_escape_only_0x2b(self):
        """Test escape with only 0x2B bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x2b\x2b\x2b'
        escaped = device.escape(data)
        # Each 0x2B becomes 0x2B 0x18
        assert escaped == b'\x2b\x18\x2b\x18\x2b\x18'

    def test_escape_mixed_special_bytes(self):
        """Test escape with mixed 0x10 and 0x2B."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10\x2b\x10\x2b'
        escaped = device.escape(data)
        assert escaped == b'\x10\x10\x2b\x18\x10\x10\x2b\x18'

    def test_unescape_empty_bytes(self):
        """Test unescape with empty bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b''
        unescaped = device.unescape(data)
        assert unescaped == b''

    def test_unescape_no_escape_sequences(self):
        """Test unescape with no escape sequences."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x02\x03\x04'
        unescaped = device.unescape(data)
        assert unescaped == data

    def test_unescape_multiple_0x10_sequences(self):
        """Test unescape with multiple 0x10 0x10 sequences."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10\x10\x01\x10\x10\x02\x10\x10'
        unescaped = device.unescape(data)
        assert unescaped == b'\x10\x01\x10\x02\x10'

    def test_unescape_multiple_0x2b_sequences(self):
        """Test unescape with multiple 0x2B 0x18 sequences."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x2b\x18\x01\x2b\x18\x02\x2b\x18'
        unescaped = device.unescape(data)
        assert unescaped == b'\x2b\x01\x2b\x02\x2b'

    def test_construct_telegram_empty_addr(self):
        """Test telegram construction with empty address bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b''
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x5a'

        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)
        assert telegram == b'\x01\x00\x5a\x10\x03'

    def test_construct_telegram_multiple_addr_bytes(self):
        """Test telegram with multiple address bytes."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b'\xfb\xfc\xfd'
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x5a'

        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)
        # checksum + addr_bytes = b'\x5a\xfb\xfc\xfd', no escaping needed
        assert telegram == b'\x01\x00\x5a\xfb\xfc\xfd\x10\x03'

    def test_construct_telegram_all_need_escaping(self):
        """Test telegram where both checksum and addr need escaping."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b'\x10\x2b'  # Both need escaping
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x10'  # Also needs escaping

        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)
        # checksum + addr = b'\x10\x10\x2b'
        # After escape: b'\x10\x10\x10\x10\x2b\x18'
        assert telegram == b'\x01\x00\x10\x10\x10\x10\x2b\x18\x10\x03'


class TestTHZDeviceConfiguration:
    """Test device configuration options."""

    def test_usb_with_custom_baudrate(self):
        """Test USB device with custom baudrate."""
        device = THZDevice(
            connection="usb",
            port="/dev/ttyUSB0",
            baudrate=57600,
        )
        assert device.baudrate == 57600

    def test_usb_with_custom_timeout(self):
        """Test USB device with custom timeout."""
        device = THZDevice(
            connection="usb",
            port="/dev/ttyUSB0",
            read_timeout=5.0,
        )
        assert device.read_timeout == 5.0

    def test_ip_with_custom_port(self):
        """Test IP device with custom port."""
        device = THZDevice(
            connection="ip",
            host="192.168.1.100",
            tcp_port=5555,
        )
        assert device.tcp_port == 5555

    def test_device_min_interval(self):
        """Test minimum interval between reads."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device._min_interval == 0.1

    def test_device_last_access_initialized(self):
        """Test that last access time is initialized."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device._last_access == 0


class TestTHZDeviceProperties:
    """Test device properties and attributes."""

    def test_firmware_version_property_set(self):
        """Test firmware_version property when set."""
        device = THZDevice(connection="usb", port="/dev/null")
        device._firmware_version = "214"
        assert device.firmware_version == "214"

    def test_firmware_version_property_error(self):
        """Test firmware_version property raises error when not set."""
        device = THZDevice(connection="usb", port="/dev/null")
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = device.firmware_version

    def test_initialized_flag_default(self):
        """Test that initialized flag defaults to False."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device._initialized is False

    def test_connection_type_stored(self):
        """Test that connection type is stored correctly."""
        usb_device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        assert usb_device.connection == "usb"

        ip_device = THZDevice(connection="ip", host="192.168.1.1", tcp_port=2000)
        assert ip_device.connection == "ip"

    def test_port_stored(self):
        """Test that port information is stored."""
        usb_device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        assert usb_device.port == "/dev/ttyUSB0"

        ip_device = THZDevice(connection="ip", host="192.168.1.1", tcp_port=2323)
        assert ip_device.host == "192.168.1.1"
        assert ip_device.tcp_port == 2323

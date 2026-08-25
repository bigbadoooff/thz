"""Tests for THZ device initialization and utility functions."""

import pytest

from custom_components.thz.thz_device import THZDevice, THZRegisterNotSupportedError


class TestTHZDeviceInitialization:
    """Tests for THZDevice initialization."""

    def test_usb_initialization(self):
        """Test USB device initialization without connection."""
        device = THZDevice(
            connection="usb",
            port="/dev/ttyUSB0",
            baudrate=115200,
        )
        
        assert device.connection == "usb"
        assert device.port == "/dev/ttyUSB0"
        assert device.baudrate == 115200
        assert not device._initialized
        assert device.ser is None

    def test_ip_initialization(self):
        """Test IP/network device initialization without connection."""
        device = THZDevice(
            connection="ip",
            host="192.168.1.100",
            tcp_port=2000,
        )
        
        assert device.connection == "ip"
        assert device.host == "192.168.1.100"
        assert device.tcp_port == 2000
        assert not device._initialized
        assert device.ser is None

    def test_default_baudrate(self):
        """Test default baudrate is applied."""
        from custom_components.thz.const import DEFAULT_BAUDRATE
        
        device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        
        assert device.baudrate == DEFAULT_BAUDRATE

    def test_default_timeout(self):
        """Test default timeout is applied."""
        from custom_components.thz.const import TIMEOUT
        
        device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        
        assert device.read_timeout == TIMEOUT

    def test_custom_timeout(self):
        """Test custom timeout is applied."""
        device = THZDevice(
            connection="usb",
            port="/dev/ttyUSB0",
            read_timeout=2.5,
        )
        
        assert device.read_timeout == 2.5

    def test_firmware_version_unset(self):
        """Test that firmware version is None before initialization."""
        device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        
        assert device._firmware_version is None

    def test_register_managers_unset(self):
        """Test that register managers are None before initialization."""
        device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        
        assert device.register_map_manager is None
        assert device.write_register_map_manager is None

    def test_lock_initialization(self):
        """Test that async lock is initialized."""
        import asyncio
        
        device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        
        assert isinstance(device.lock, asyncio.Lock)

    def test_min_interval_default(self):
        """Test default minimum interval between reads."""
        device = THZDevice(connection="usb", port="/dev/ttyUSB0")
        
        assert device._min_interval == 0.1


class TestTHZDeviceProtocol:
    """Tests for protocol utility functions."""

    def test_checksum_calculation(self):
        """Test checksum calculation."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x00\x00\xfb'
        
        checksum = device.thz_checksum(data)
        
        # Sum: 0x01 + 0x00 + 0xfb (skip index 2) = 0xfc
        assert checksum == b'\xfc'

    def test_checksum_with_overflow(self):
        """Test checksum with modulo 256."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\xff\xff\x00\xff'
        
        checksum = device.thz_checksum(data)
        
        # Sum: 0xff + 0xff + 0xff = 0x2fd, mod 256 = 0xfd
        assert checksum == b'\xfd'

    def test_escape_0x10(self):
        """Test escaping 0x10 byte."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10'
        
        escaped = device.escape(data)
        
        assert escaped == b'\x10\x10'

    def test_escape_0x2b(self):
        """Test escaping 0x2B byte."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x2b'
        
        escaped = device.escape(data)
        
        assert escaped == b'\x2b\x18'

    def test_escape_mixed_data(self):
        """Test escaping mixed data."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x01\x10\x2b\x03'
        
        escaped = device.escape(data)
        
        assert escaped == b'\x01\x10\x10\x2b\x18\x03'

    def test_unescape_0x10(self):
        """Test unescaping 0x10 sequence."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x10\x10'
        
        unescaped = device.unescape(data)
        
        assert unescaped == b'\x10'

    def test_unescape_0x2b(self):
        """Test unescaping 0x2B sequence."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b'\x2b\x18'
        
        unescaped = device.unescape(data)
        
        assert unescaped == b'\x2b'

    def test_round_trip_escape_unescape(self):
        """Test escape and unescape are inverse operations."""
        device = THZDevice(connection="usb", port="/dev/null")
        original = b'\x01\x10\x2b\x03'
        
        escaped = device.escape(original)
        unescaped = device.unescape(escaped)
        
        assert unescaped == original

    def test_construct_telegram_basic(self):
        """Test constructing a basic telegram."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b'\xfb'
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x5a'
        
        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)
        
        # Should be: header + escaped(checksum + addr_bytes) + footer
        assert telegram == b'\x01\x00\x5a\xfb\x10\x03'

    def test_construct_telegram_with_escaping(self):
        """Test telegram construction with escaping."""
        device = THZDevice(connection="usb", port="/dev/null")
        addr_bytes = b'\x10'  # Needs escaping
        header = b'\x01\x00'
        footer = b'\x10\x03'
        checksum = b'\x20'
        
        telegram = device.construct_telegram(addr_bytes, header, footer, checksum)
        
        # checksum + addr_bytes = b'\x20\x10'
        # After escaping: b'\x20\x10\x10'
        assert telegram == b'\x01\x00\x20\x10\x10\x10\x03'


class TestFirmwareVersion:
    """Tests for firmware version property."""

    def test_firmware_version_property(self):
        """Test firmware_version property."""
        device = THZDevice(connection="usb", port="/dev/null")
        device._firmware_version = "206"
        
        assert device.firmware_version == "206"

    def test_firmware_version_none(self):
        """Test firmware_version raises error when not initialized."""
        device = THZDevice(connection="usb", port="/dev/null")

        with pytest.raises(RuntimeError, match="Device not initialized"):
            _ = device.firmware_version


class TestDecodeResponse:
    """Tests for decode_response()'s protocol-error handling.

    Regression coverage for a bug where a clean "01 04" (register not
    supported) response was deliberately raised as
    THZRegisterNotSupportedError, but then immediately swallowed by this
    same method's own blanket ``except Exception`` and downgraded to a
    plain ``None`` — indistinguishable from a genuine decode failure. That
    caused registers the device doesn't support (e.g. 5.39-only registers
    on 4.3x firmware) to crash the whole config entry's first refresh
    instead of being skipped gracefully, one block at a time.
    """

    def test_register_not_supported_raises(self):
        """Test that a "01 04" response raises THZRegisterNotSupportedError."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = b"\x01\x04\x00\x00\x10\x03"

        with pytest.raises(THZRegisterNotSupportedError):
            device.decode_response(data)

    def test_short_response_returns_none(self):
        """Test that a too-short response returns None, not an exception."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device.decode_response(b"\x01\x00") is None

    def test_timing_issue_returns_none(self):
        """Test that a "01 01" (timing issue) response returns None."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device.decode_response(b"\x01\x01\x00\x00\x10\x03") is None

    def test_crc_error_in_request_returns_none(self):
        """Test that a "01 02" (CRC error in request) response returns None."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device.decode_response(b"\x01\x02\x00\x00\x10\x03") is None

    def test_unknown_command_returns_none(self):
        """Test that a "01 03" (unknown command) response returns None."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device.decode_response(b"\x01\x03\x00\x00\x10\x03") is None

    def test_unknown_response_header_returns_none(self):
        """Test that a completely unrecognized header returns None."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device.decode_response(b"\xff\xff\x00\x00\x10\x03") is None

    def test_bad_checksum_returns_none(self):
        """Test that a normal-header response with a wrong CRC returns None."""
        device = THZDevice(connection="usb", port="/dev/null")
        # header 01 00, wrong crc byte (0x00), payload \xaa\xbb, footer 10 03
        assert device.decode_response(b"\x01\x00\x00\xaa\xbb\x10\x03") is None

    def test_valid_response_decodes_payload(self):
        """Test that a well-formed, correctly-checksummed response decodes."""
        device = THZDevice(connection="usb", port="/dev/null")
        # header 01 00, correct crc (0x66) for payload \xaa\xbb, footer 10 03
        result = device.decode_response(b"\x01\x00\x66\xaa\xbb\x10\x03")
        assert result == b"\x66\xaa\xbb"

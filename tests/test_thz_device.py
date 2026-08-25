"""Tests for THZ device initialization and utility functions."""

import pytest

from custom_components.thz.thz_device import THZDevice


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


class TestFirmwareOverride:
    """Tests for the firmware_override config option and its resolution.

    _resolve_effective_firmware() decides which firmware string actually
    drives register-map selection: the auto-detected value, unless an
    override was configured to force a specific FHEM-style profile (e.g.
    "439technician") regardless of what the device reports.
    """

    def test_firmware_override_defaults_to_none(self):
        """Test that no override is applied unless explicitly configured."""
        device = THZDevice(connection="usb", port="/dev/null")
        assert device._firmware_override is None

    def test_firmware_override_stored(self):
        """Test that a configured override is stored on the device."""
        device = THZDevice(
            connection="usb", port="/dev/null", firmware_override="539"
        )
        assert device._firmware_override == "539"

    def test_no_override_uses_detected_firmware(self):
        """Test that effective firmware falls back to the detected value."""
        device = THZDevice(connection="usb", port="/dev/null")
        device._firmware_version = "438"
        assert device._resolve_effective_firmware() == "438"

    def test_auto_override_uses_detected_firmware(self):
        """Test that an explicit "auto" override behaves like no override."""
        device = THZDevice(
            connection="usb", port="/dev/null", firmware_override="auto"
        )
        device._firmware_version = "438"
        assert device._resolve_effective_firmware() == "438"

    def test_explicit_override_wins_over_detected_firmware(self):
        """Test that a non-"auto" override takes precedence for map selection."""
        device = THZDevice(
            connection="usb", port="/dev/null", firmware_override="439technician"
        )
        device._firmware_version = "438"
        assert device._resolve_effective_firmware() == "439technician"

    def test_override_does_not_change_reported_firmware_version(self):
        """Test that firmware_version still reflects the real detected value.

        The override only affects which register maps get loaded; the
        displayed/diagnostic firmware_version should stay truthful about
        what the device actually reported.
        """
        device = THZDevice(
            connection="usb", port="/dev/null", firmware_override="439technician"
        )
        device._firmware_version = "438"
        assert device._resolve_effective_firmware() == "439technician"
        assert device.firmware_version == "438"

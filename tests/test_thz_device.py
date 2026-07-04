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


class TestWriteBlockValue:
    """Tests for write_block_value method (2xx firmware read-modify-write)."""

    def _make_device_with_block(self, block_data: bytes):
        """Create a THZDevice mock with read_write_register returning block_data."""

        device = THZDevice(connection="usb", port="/dev/null")

        # Simulate decode_response output: [CRC] + PAYLOAD_BYTES
        # block_data represents the raw PAYLOAD_BYTES (without CRC prefix).
        simulated_response = b"\xAB" + block_data  # CRC=0xAB, payload=block_data

        call_log = []

        def fake_read_write_register(addr, mode, payload=b""):
            call_log.append((addr, mode, payload))
            if mode == "get":
                return simulated_response
            return b""  # "set" returns empty bytes

        device.read_write_register = fake_read_write_register
        return device, call_log

    def test_write_block_value_modifies_correct_bytes(self):
        """Test that write_block_value replaces only the target bytes.

        p01RoomTempDay: nibble offset=4 in FHEM/register_map → byte offset=2 in full
        response (CRC at byte 0).  write_block_value strips the CRC byte so the payload
        index is offset-1 = 1.  The value is 2 bytes wide (nibble length 4 → byte 2).
        """
        block_payload = bytes(range(20))  # [0,1,2,...,19]
        device, call_log = self._make_device_with_block(block_payload)

        new_value = b"\xAA\xBB"
        # offset=2 is the byte offset in the full response (CRC at 0); payload index=1.
        device.write_block_value(b"\x17", offset=2, length=2, value=new_value)

        assert len(call_log) == 2
        assert call_log[0] == (b"\x17", "get", b"")
        addr, mode, written_payload = call_log[1]
        assert addr == b"\x17"
        assert mode == "set"
        expected = bytearray(block_payload)
        expected[1:3] = new_value  # payload_offset = offset-1 = 1
        assert written_payload == bytes(expected)

    def test_write_block_value_preserves_other_bytes(self):
        """Test that write_block_value does not disturb other bytes in the block."""
        block_payload = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A"
        device, call_log = self._make_device_with_block(block_payload)

        # Write 2 bytes at offset 6 (payload index 5)
        new_value = b"\xFF\xFE"
        device.write_block_value(b"\x06", offset=6, length=2, value=new_value)

        _, _, written = call_log[1]
        assert written[0:5] == block_payload[0:5]   # bytes before target unchanged
        assert written[5:7] == b"\xFF\xFE"           # target bytes replaced
        assert written[7:] == block_payload[7:]       # bytes after target unchanged

    def test_write_block_value_wrong_length_raises(self):
        """Test that passing a value of wrong length raises ValueError."""
        block_payload = bytes(10)
        device, _ = self._make_device_with_block(block_payload)

        with pytest.raises(ValueError, match="value length"):
            device.write_block_value(
                b"\x17", offset=2, length=2, value=b"\xAA"  # 1 byte, expected 2
            )

    def test_write_block_value_out_of_range_raises(self):
        """Test that an out-of-range offset raises ValueError."""
        block_payload = bytes(5)
        device, _ = self._make_device_with_block(block_payload)

        with pytest.raises(ValueError, match="out of range"):
            # offset=5 → payload_offset=4, length=2 → needs payload[4:6] but len=5
            device.write_block_value(
                b"\x17",
                offset=5,
                length=2,
                value=b"\xAA\xBB",
            )

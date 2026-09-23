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

    def _make_device_with_block(self, block_addr: bytes, block_data: bytes):
        """Create a THZDevice whose read_write_register returns block_data.

        Simulates decode_response output for a real 2xx block read:
        [CRC] + [address echo] + [data].
        """
        device = THZDevice(connection="usb", port="/dev/null")
        simulated_response = b"\xAB" + block_addr + block_data

        call_log = []

        def fake_read_write_register(addr, mode, payload=b""):
            call_log.append((addr, mode, payload))
            if mode == "get":
                return simulated_response
            return b""  # "set" returns empty bytes

        device.read_write_register = fake_read_write_register
        return device, call_log

    def test_write_block_value_modifies_correct_bytes(self):
        """Only the target bytes change, and the address is not sent twice.

        p01RoomTempDay: nibble offset=4 in FHEM/register_map -> byte offset=2 in
        the decoded response (CRC at 0, address echo at 1) -> data index 0.
        """
        block_data = bytes(range(20))
        device, call_log = self._make_device_with_block(b"\x17", block_data)

        device.write_block_value(b"\x17", offset=2, length=2, value=b"\xAA\xBB")

        assert len(call_log) == 2
        assert call_log[0] == (b"\x17", "get", b"")
        addr, mode, written_payload = call_log[1]
        assert addr == b"\x17"
        assert mode == "set"
        expected = bytearray(block_data)
        expected[0:2] = b"\xAA\xBB"
        assert written_payload == bytes(expected)

    def test_write_block_value_preserves_other_bytes(self):
        """Test that write_block_value does not disturb other bytes in the block."""
        block_data = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A"
        device, call_log = self._make_device_with_block(b"\x06", block_data)

        # offset 6 in the decoded response -> data index 4
        device.write_block_value(b"\x06", offset=6, length=2, value=b"\xFF\xFE")

        _, _, written = call_log[1]
        assert written[0:4] == block_data[0:4]
        assert written[4:6] == b"\xFF\xFE"
        assert written[6:] == block_data[6:]

    def test_write_block_value_wrong_length_raises(self):
        """Test that passing a value of wrong length raises ValueError."""
        device, _ = self._make_device_with_block(b"\x17", bytes(10))

        with pytest.raises(ValueError, match="value length"):
            device.write_block_value(
                b"\x17", offset=2, length=2, value=b"\xAA"  # 1 byte, expected 2
            )

    def test_write_block_value_out_of_range_raises(self):
        """Test that an out-of-range offset raises ValueError."""
        device, _ = self._make_device_with_block(b"\x17", bytes(5))

        with pytest.raises(ValueError, match="out of range"):
            # offset=6 -> data index 4; length=2 needs data[4:6] but len is 5.
            device.write_block_value(b"\x17", offset=6, length=2, value=b"\xAA\xBB")

    def test_write_block_value_offset_inside_header_raises(self):
        """Offsets pointing at the CRC or address echo are rejected."""
        device, _ = self._make_device_with_block(b"\x17", bytes(10))

        with pytest.raises(ValueError, match="out of range"):
            device.write_block_value(b"\x17", offset=1, length=1, value=b"\x00")

    def test_write_block_value_wrong_echo_raises(self):
        """A read-back that echoes a different block is never written back."""
        device, call_log = self._make_device_with_block(b"\x05", bytes(10))

        with pytest.raises(RuntimeError, match="address echo"):
            device.write_block_value(b"\x17", offset=2, length=2, value=b"\x00\x01")
        assert all(mode == "get" for _, mode, _ in call_log)

    def test_write_block_value_sends_fhem_compatible_telegram(self):
        """Golden test on the wire: the SET telegram carries the address once."""
        device = THZDevice(connection="usb", port="/dev/null")
        data = bytes.fromhex("17" "00C8" "00AA" "0064")
        crc = device.thz_checksum(b"\x01\x00\x00" + data)
        reply = b"\x01\x00" + crc + data + b"\x10\x03"
        sent = []

        def fake_send_request(telegram, get_or_set):
            sent.append(telegram)
            return reply if get_or_set == "get" else b""

        device.send_request = fake_send_request
        device.write_block_value(b"\x17", offset=2, length=2, value=b"\x00\xD2")

        new_data = bytes.fromhex("17" "00D2" "00AA" "0064")
        new_crc = device.thz_checksum(b"\x01\x80\x00" + new_data)
        assert sent[1] == b"\x01\x80" + new_crc + new_data + b"\x10\x03"



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

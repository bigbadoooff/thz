"""Coverage-focused tests for THZDevice connection, protocol and I/O paths.

These tests complement test_thz_device.py / test_thz_device_extended.py /
test_protocol.py / test_connection_timeout_restoration.py by exercising the
connection setup, handshake, telegram exchange, low-level read/write helpers
and higher-level register access methods of THZDevice -- including both
success and failure paths.
"""

import itertools
import socket as socket_module
from unittest.mock import MagicMock, Mock, patch

import pytest

from custom_components.thz.thz_device import THZDevice, THZRegisterNotSupportedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeHass:
    """Minimal fake HomeAssistant object.

    async_add_executor_job simply invokes the callable synchronously and
    returns its result, mirroring what the real implementation does from the
    caller's perspective for these tests.
    """

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class ScriptedSerial:
    """Fake serial object that trickles pre-scripted response bytes.

    Mimics real hardware behaviour where only a small number of bytes are
    available per read() call, so the protocol's byte-by-byte / N-byte reads
    line up correctly against the scripted response stream.
    """

    def __init__(self, response_bytes: bytes):
        self._buf = bytearray(response_bytes)
        self.written = bytearray()
        self.reset_calls = 0
        self.closed = False

    def write(self, data):
        self.written.extend(data)

    def flush(self):
        pass

    @property
    def in_waiting(self):
        return 1 if self._buf else 0

    def read(self, n):
        take = min(n, 1, len(self._buf))
        data = bytes(self._buf[:take])
        del self._buf[:take]
        return data

    def reset_input_buffer(self):
        self.reset_calls += 1

    def close(self):
        self.closed = True


def _make_device(**kwargs):
    defaults = {"connection": "usb", "port": "/dev/null"}
    defaults.update(kwargs)
    return THZDevice(**defaults)


# ---------------------------------------------------------------------------
# _connect_serial / _connect_tcp
# ---------------------------------------------------------------------------


class TestConnectSerial:
    def test_connect_serial_success(self):
        device = _make_device(port="/dev/ttyUSB0", baudrate=9600, read_timeout=2.0)
        with patch("custom_components.thz.thz_device.serial.Serial") as mock_serial:
            mock_instance = MagicMock()
            mock_serial.return_value = mock_instance
            device._connect_serial()
            mock_serial.assert_called_once_with(
                "/dev/ttyUSB0", baudrate=9600, timeout=2.0
            )
            assert device.ser is mock_instance

    def test_connect_serial_propagates_error(self):
        device = _make_device(port="/dev/ttyUSB0")
        with patch(
            "custom_components.thz.thz_device.serial.Serial",
            side_effect=OSError("no such device"),
        ):
            with pytest.raises(OSError):
                device._connect_serial()


class TestConnectTcp:
    def test_connect_tcp_success(self):
        device = _make_device(
            connection="ip", host="192.168.1.50", tcp_port=2000, read_timeout=1.5
        )
        mock_sock = MagicMock()
        with patch(
            "custom_components.thz.thz_device.socket.socket", return_value=mock_sock
        ):
            device._connect_tcp()

        assert device.ser is mock_sock
        mock_sock.settimeout.assert_called_with(1.5)
        mock_sock.setsockopt.assert_any_call(
            socket_module.SOL_SOCKET, socket_module.SO_KEEPALIVE, 1
        )
        mock_sock.connect.assert_called_once_with(("192.168.1.50", 2000))

    def test_connect_tcp_keepalive_setsockopt_failure_is_tolerated(self):
        """A platform without keepalive tuning support should not raise."""
        device = _make_device(connection="ip", host="10.0.0.1", tcp_port=2323)
        mock_sock = MagicMock()

        def setsockopt_side_effect(level, optname, value):
            if level == socket_module.IPPROTO_TCP:
                raise OSError("not supported")
            return None

        mock_sock.setsockopt.side_effect = setsockopt_side_effect

        with patch(
            "custom_components.thz.thz_device.socket.socket", return_value=mock_sock
        ):
            device._connect_tcp()

        assert device.ser is mock_sock
        mock_sock.connect.assert_called_once_with(("10.0.0.1", 2323))


# ---------------------------------------------------------------------------
# _is_connection_alive
# ---------------------------------------------------------------------------


class TestIsConnectionAliveExtra:
    def test_none_connection_is_not_alive(self):
        device = _make_device()
        assert device.ser is None
        assert device._is_connection_alive() is False

    def test_invalid_socket_fileno_is_dead(self):
        device = _make_device(connection="ip", host="h", tcp_port=1)
        mock_sock = Mock()
        mock_sock.fileno.return_value = -1
        device.ser = mock_sock
        assert device._is_connection_alive() is False

    def test_socket_fileno_raises_is_dead(self):
        device = _make_device(connection="ip", host="h", tcp_port=1)
        mock_sock = Mock()
        mock_sock.fileno.side_effect = OSError("bad fd")
        device.ser = mock_sock
        assert device._is_connection_alive() is False

    def test_serial_is_open_true(self):
        device = _make_device()
        mock_serial = Mock(spec=["is_open"])
        mock_serial.is_open = True
        device.ser = mock_serial
        assert device._is_connection_alive() is True

    def test_serial_is_open_false(self):
        device = _make_device()
        mock_serial = Mock(spec=["is_open"])
        mock_serial.is_open = False
        device.ser = mock_serial
        assert device._is_connection_alive() is False

    def test_serial_is_open_attribute_error(self):
        device = _make_device()

        class Weird:
            @property
            def is_open(self):
                raise AttributeError("boom")

        device.ser = Weird()
        assert device._is_connection_alive() is False

    def test_unknown_connection_object_is_not_alive(self):
        device = _make_device()
        device.ser = Mock(spec=[])
        assert device._is_connection_alive() is False

    def test_serial_is_open_raises_attribute_error_on_access(self):
        """hasattr() succeeds but the actual .is_open access then fails."""
        device = _make_device()

        class FlakyIsOpen:
            def __init__(self):
                self.calls = 0

            @property
            def is_open(self):
                self.calls += 1
                if self.calls == 1:
                    return True
                raise AttributeError("gone")

        device.ser = FlakyIsOpen()
        assert device._is_connection_alive() is False


# ---------------------------------------------------------------------------
# _reconnect
# ---------------------------------------------------------------------------


class TestReconnect:
    def test_reconnect_usb_calls_connect_serial(self):
        device = _make_device(connection="usb")
        old_ser = MagicMock()
        device.ser = old_ser
        with patch.object(device, "_connect_serial") as mock_connect:
            device._reconnect()
        old_ser.close.assert_called_once()
        mock_connect.assert_called_once()

    def test_reconnect_ip_calls_connect_tcp(self):
        device = _make_device(connection="ip", host="h", tcp_port=1)
        device.ser = MagicMock()
        with patch.object(device, "_connect_tcp") as mock_connect:
            device._reconnect()
        mock_connect.assert_called_once()

    def test_reconnect_when_ser_is_none_skips_close(self):
        device = _make_device(connection="usb")
        assert device.ser is None
        with patch.object(device, "_connect_serial") as mock_connect:
            device._reconnect()
        mock_connect.assert_called_once()

    def test_reconnect_ignores_close_error(self):
        device = _make_device(connection="usb")
        old_ser = MagicMock()
        old_ser.close.side_effect = OSError("already closed")
        device.ser = old_ser
        with patch.object(device, "_connect_serial") as mock_connect:
            device._reconnect()
        mock_connect.assert_called_once()

    def test_reconnect_propagates_connect_error(self):
        device = _make_device(connection="usb")
        with patch.object(
            device, "_connect_serial", side_effect=OSError("no device")
        ):
            with pytest.raises(OSError):
                device._reconnect()


# ---------------------------------------------------------------------------
# _do_handshake_1
# ---------------------------------------------------------------------------


class TestHandshake1:
    def test_handshake1_success(self):
        device = _make_device()
        with patch.object(device, "_write_bytes") as mock_write, patch.object(
            device, "_read_exact", return_value=b"\x10"
        ) as mock_read:
            device._do_handshake_1(1.0)
        mock_write.assert_called_once_with(b"\x02")
        mock_read.assert_called_once_with(1, 1.0)

    def test_handshake1_wrong_byte_raises(self):
        device = _make_device()
        with patch.object(device, "_write_bytes"), patch.object(
            device, "_read_exact", return_value=b"\x05"
        ):
            with pytest.raises(RuntimeError, match="Handshake 1 failed"):
                device._do_handshake_1(1.0)

    def test_handshake1_no_data_raises(self):
        device = _make_device()
        with patch.object(device, "_write_bytes"), patch.object(
            device, "_read_exact", return_value=b""
        ):
            with pytest.raises(RuntimeError, match="no data"):
                device._do_handshake_1(1.0)


# ---------------------------------------------------------------------------
# _do_handshake_2
# ---------------------------------------------------------------------------


class TestHandshake2:
    def test_handshake2_combined_success(self):
        device = _make_device()
        with patch.object(device, "_read_exact", return_value=b"\x10\x02") as m:
            device._do_handshake_2(1.0)
        m.assert_called_once_with(2, 1.0)

    def test_handshake2_split_dle_then_stx(self):
        device = _make_device()
        with patch.object(
            device, "_read_exact", side_effect=[b"\x10", b"\x02"]
        ):
            device._do_handshake_2(1.0)

    def test_handshake2_split_dle_then_stx_with_fw2_delay(self):
        device = _make_device()
        device._firmware_version = "206"
        with patch.object(
            device, "_read_exact", side_effect=[b"\x10", b"\x02"]
        ), patch("custom_components.thz.thz_device.time.sleep") as mock_sleep:
            device._do_handshake_2(1.0)
        mock_sleep.assert_called_once_with(0.005)

    def test_handshake2_split_dle_then_wrong_byte_raises(self):
        device = _make_device()
        with patch.object(
            device, "_read_exact", side_effect=[b"\x10", b"\x99"]
        ):
            with pytest.raises(RuntimeError, match="Handshake 2 failed"):
                device._do_handshake_2(1.0)

    def test_handshake2_split_dle_then_no_data_raises(self):
        device = _make_device()
        with patch.object(device, "_read_exact", side_effect=[b"\x10", b""]):
            with pytest.raises(RuntimeError, match="no data"):
                device._do_handshake_2(1.0)

    def test_handshake2_only_stx_treated_as_success(self):
        device = _make_device()
        with patch.object(device, "_read_exact", return_value=b"\x02"):
            device._do_handshake_2(1.0)

    def test_handshake2_unrelated_bytes_raises(self):
        device = _make_device()
        with patch.object(device, "_read_exact", return_value=b"\xaa\xbb"):
            with pytest.raises(RuntimeError, match="Handshake 2 failed"):
                device._do_handshake_2(1.0)


# ---------------------------------------------------------------------------
# _receive_data_telegram
# ---------------------------------------------------------------------------


class TestReceiveDataTelegram:
    def test_receive_data_telegram_success(self):
        device = _make_device()
        telegram = b"\x01\x00\xce\x00\xc8\x05\x10\x03"
        with patch.object(device, "_write_bytes") as mock_write, patch.object(
            device, "_read_available", side_effect=[telegram]
        ):
            result = device._receive_data_telegram(1.0)
        mock_write.assert_called_once_with(b"\x10")
        assert result == telegram

    def test_receive_data_telegram_accumulates_chunks(self):
        device = _make_device()
        chunks = [b"\x01\x00\xce", b"\x00\xc8\x05", b"\x10\x03"]
        with patch.object(device, "_write_bytes"), patch.object(
            device, "_read_available", side_effect=chunks
        ):
            result = device._receive_data_telegram(1.0)
        assert result == b"\x01\x00\xce\x00\xc8\x05\x10\x03"

    def test_receive_data_telegram_timeout_raises(self):
        device = _make_device()
        with patch.object(device, "_write_bytes"), patch.object(
            device, "_read_available", return_value=b""
        ):
            with pytest.raises(RuntimeError, match="No valid response"):
                device._receive_data_telegram(0.03)

    def test_receive_data_telegram_incomplete_data_raises(self):
        device = _make_device()
        # Never reaches the 8-byte + DLE/ETX terminator condition.
        chunks = itertools.chain([b"\x01\x02"], itertools.repeat(b""))
        with patch.object(device, "_write_bytes"), patch.object(
            device, "_read_available", side_effect=chunks
        ):
            with pytest.raises(RuntimeError, match="No valid response"):
                device._receive_data_telegram(0.03)


# ---------------------------------------------------------------------------
# _exchange_once
# ---------------------------------------------------------------------------


class TestExchangeOnce:
    def _make_mocks(self, alive=True):
        return {
            "_is_connection_alive": MagicMock(return_value=alive),
            "_reconnect": MagicMock(),
            "_do_handshake_1": MagicMock(),
            "_reset_input_buffer": MagicMock(),
            "_write_bytes": MagicMock(),
            "_do_handshake_2": MagicMock(),
            "_receive_data_telegram": MagicMock(return_value=b"DATA"),
        }

    def test_exchange_once_reconnects_when_not_initialized_alive_skipped(self):
        device = _make_device()
        device._initialized = False
        mocks = self._make_mocks(alive=False)
        with patch.multiple(device, **mocks):
            device._exchange_once(b"telegram", "get", 0, 1)
        mocks["_reconnect"].assert_not_called()

    def test_exchange_once_reconnects_when_initialized_and_dead(self):
        device = _make_device()
        device._initialized = True
        mocks = self._make_mocks(alive=False)
        with patch.multiple(device, **mocks):
            device._exchange_once(b"telegram", "get", 0, 1)
        mocks["_reconnect"].assert_called_once()

    def test_exchange_once_get_reads_data(self):
        device = _make_device()
        device._initialized = True
        mocks = self._make_mocks(alive=True)
        with patch.multiple(device, **mocks):
            result = device._exchange_once(b"telegram", "get", 0, 1)
        mocks["_receive_data_telegram"].assert_called_once()
        assert result == b"DATA"

    def test_exchange_once_set_skips_data_read(self):
        device = _make_device()
        device._initialized = True
        mocks = self._make_mocks(alive=True)
        with patch.multiple(device, **mocks):
            result = device._exchange_once(b"telegram", "set", 0, 1)
        mocks["_receive_data_telegram"].assert_not_called()
        assert result == b""


# ---------------------------------------------------------------------------
# send_request
# ---------------------------------------------------------------------------


class TestSendRequest:
    def test_send_request_success_first_try(self):
        device = _make_device()
        with patch.object(
            device, "_exchange_once", return_value=b"ok"
        ) as mock_exchange:
            result = device.send_request(b"telegram", "get")
        assert result == b"ok"
        assert mock_exchange.call_count == 1

    def test_send_request_connection_error_then_success(self):
        device = _make_device()
        with patch.object(
            device,
            "_exchange_once",
            side_effect=[ConnectionError("dropped"), b"ok"],
        ), patch.object(device, "_reconnect") as mock_reconnect:
            result = device.send_request(b"telegram", "get")
        assert result == b"ok"
        mock_reconnect.assert_called_once()

    def test_send_request_connection_error_exhausts_retries(self):
        device = _make_device()
        with patch.object(
            device,
            "_exchange_once",
            side_effect=[ConnectionError("a"), ConnectionError("b")],
        ), patch.object(device, "_reconnect"):
            with pytest.raises(ConnectionError, match="Connection failed after 2"):
                device.send_request(b"telegram", "get")

    def test_send_request_connection_error_reconnect_fails(self):
        device = _make_device()
        with patch.object(
            device, "_exchange_once", side_effect=[ConnectionError("a")]
        ), patch.object(device, "_reconnect", side_effect=OSError("no port")):
            with pytest.raises(ConnectionError, match="Connection failed after 2"):
                device.send_request(b"telegram", "get")

    def test_send_request_runtime_error_then_success(self):
        device = _make_device()
        with patch.object(
            device,
            "_exchange_once",
            side_effect=[RuntimeError("proto"), b"ok2"],
        ), patch.object(device, "_reconnect") as mock_reconnect:
            result = device.send_request(b"telegram", "get")
        assert result == b"ok2"
        mock_reconnect.assert_called_once()

    def test_send_request_runtime_error_exhausts_retries(self):
        device = _make_device()
        with patch.object(
            device,
            "_exchange_once",
            side_effect=[RuntimeError("first"), RuntimeError("second")],
        ), patch.object(device, "_reconnect"):
            with pytest.raises(RuntimeError, match="second"):
                device.send_request(b"telegram", "get")

    def test_send_request_runtime_error_reconnect_also_fails(self):
        device = _make_device()
        with patch.object(
            device, "_exchange_once", side_effect=[RuntimeError("proto")]
        ), patch.object(device, "_reconnect", side_effect=OSError("no port")):
            with pytest.raises(RuntimeError, match="proto"):
                device.send_request(b"telegram", "get")

    def test_send_request_unexpected_exception_wrapped(self):
        device = _make_device()
        with patch.object(
            device, "_exchange_once", side_effect=[ValueError("oops")]
        ):
            with pytest.raises(RuntimeError, match="Device communication failed"):
                device.send_request(b"telegram", "get")


# ---------------------------------------------------------------------------
# _write_bytes
# ---------------------------------------------------------------------------


class TestWriteBytes:
    def test_write_bytes_socket_path(self):
        device = _make_device(connection="ip", host="h", tcp_port=1)
        mock_sock = Mock(spec=["send", "recv"])
        device.ser = mock_sock
        device._write_bytes(b"\x02")
        mock_sock.send.assert_called_once_with(b"\x02")

    def test_write_bytes_serial_path(self):
        device = _make_device()
        mock_serial = Mock(spec=["write", "flush"])
        device.ser = mock_serial
        device._write_bytes(b"\x02")
        mock_serial.write.assert_called_once_with(b"\x02")
        mock_serial.flush.assert_called_once()

    def test_write_bytes_unknown_type_raises(self):
        device = _make_device()
        device.ser = Mock(spec=[])
        with pytest.raises(ConnectionError, match="Unknown connection type"):
            device._write_bytes(b"\x02")

    def test_write_bytes_oserror_raises_connection_error(self):
        device = _make_device()
        mock_serial = Mock(spec=["write", "flush"])
        mock_serial.write.side_effect = OSError("broken")
        device.ser = mock_serial
        with pytest.raises(ConnectionError, match="Failed to write"):
            device._write_bytes(b"\x02")

    def test_write_bytes_broken_pipe_raises_connection_error(self):
        device = _make_device(connection="ip", host="h", tcp_port=1)
        mock_sock = Mock(spec=["send", "recv"])
        mock_sock.send.side_effect = BrokenPipeError("pipe gone")
        device.ser = mock_sock
        with pytest.raises(ConnectionError):
            device._write_bytes(b"\x02")


# ---------------------------------------------------------------------------
# _read_exact
# ---------------------------------------------------------------------------


class TestReadExact:
    def test_read_exact_accumulates_until_size(self):
        device = _make_device()
        with patch.object(
            device, "_read_available", side_effect=[b"\x01", b"\x02", b"\x03"]
        ):
            result = device._read_exact(3, 1.0)
        assert result == b"\x01\x02\x03"

    def test_read_exact_returns_partial_on_timeout(self):
        device = _make_device()
        chunks = itertools.chain([b"\x01"], itertools.repeat(b""))
        with patch.object(device, "_read_available", side_effect=chunks):
            result = device._read_exact(3, 0.03)
        assert result == b"\x01"


# ---------------------------------------------------------------------------
# _read_available (branches not covered by test_connection_timeout_restoration.py)
# ---------------------------------------------------------------------------


class TestReadAvailableExtra:
    def test_read_available_serial_with_data(self):
        device = _make_device()
        mock_serial = Mock(spec=["in_waiting", "read"])
        mock_serial.in_waiting = 3
        mock_serial.read.return_value = b"\xaa\xbb\xcc"
        device.ser = mock_serial
        result = device._read_available()
        assert result == b"\xaa\xbb\xcc"
        mock_serial.read.assert_called_once_with(3)

    def test_read_available_serial_no_data(self):
        device = _make_device()
        mock_serial = Mock(spec=["in_waiting", "read"])
        mock_serial.in_waiting = 0
        device.ser = mock_serial
        result = device._read_available()
        assert result == b""

    def test_read_available_unknown_type_returns_empty(self):
        device = _make_device()
        device.ser = Mock(spec=[])
        assert device._read_available() == b""

    def test_read_available_settimeout_restore_failure_is_ignored(self):
        """settimeout() failing in the finally block should not raise."""
        device = _make_device(connection="ip", host="h", tcp_port=1)
        mock_sock = Mock()
        mock_sock.gettimeout.return_value = 1.0
        mock_sock.recv.return_value = b"\x01\x02"
        mock_sock.fileno.return_value = 5
        mock_sock.settimeout.side_effect = OSError("bad socket state")
        device.ser = mock_sock
        result = device._read_available()
        assert result == b"\x01\x02"

    def test_read_available_socket_closed_raises(self):
        device = _make_device(connection="ip", host="h", tcp_port=1)
        mock_sock = Mock()
        mock_sock.gettimeout.return_value = 1.0
        mock_sock.recv.return_value = b""
        mock_sock.fileno.return_value = -1
        device.ser = mock_sock
        with pytest.raises(ConnectionError, match="TCP socket connection closed"):
            device._read_available()


# ---------------------------------------------------------------------------
# _reset_input_buffer
# ---------------------------------------------------------------------------


class TestResetInputBuffer:
    def test_reset_input_buffer_none_ser_noop(self):
        device = _make_device()
        device._reset_input_buffer()  # should not raise

    def test_reset_input_buffer_calls_underlying(self):
        device = _make_device()
        mock_serial = Mock(spec=["reset_input_buffer"])
        device.ser = mock_serial
        device._reset_input_buffer()
        mock_serial.reset_input_buffer.assert_called_once()

    def test_reset_input_buffer_swallows_attribute_error(self):
        device = _make_device()
        mock_serial = Mock(spec=["reset_input_buffer"])
        mock_serial.reset_input_buffer.side_effect = AttributeError("nope")
        device.ser = mock_serial
        device._reset_input_buffer()  # should not raise

    def test_reset_input_buffer_no_attribute_noop(self):
        device = _make_device()
        device.ser = Mock(spec=[])
        device._reset_input_buffer()  # should not raise / not call anything


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_calls_underlying_close(self):
        device = _make_device()
        mock_ser = MagicMock()
        device.ser = mock_ser
        device.close()
        mock_ser.close.assert_called_once()

    def test_close_with_no_connection_is_noop(self):
        device = _make_device()
        device.close()  # should not raise


# ---------------------------------------------------------------------------
# decode_response
# ---------------------------------------------------------------------------


class TestDecodeResponse:
    def _build_response(self, header: bytes, payload: bytes) -> bytes:
        device = _make_device()
        check_data = header + b"\x00" + payload
        crc = device.thz_checksum(check_data)
        return header + crc + payload + b"\x10\x03"

    def test_decode_response_get_success(self):
        device = _make_device()
        data = self._build_response(b"\x01\x00", b"\x00\xc8\x05")
        result = device.decode_response(data)
        assert result == b"\xce\x00\xc8\x05"

    def test_decode_response_set_success(self):
        device = _make_device()
        data = self._build_response(b"\x01\x80", b"\xab")
        result = device.decode_response(data)
        assert result is not None
        assert result[1:] == b"\xab"

    def test_decode_response_crc_mismatch_returns_none(self):
        device = _make_device()
        data = self._build_response(b"\x01\x00", b"\x00\xc8\x05")
        corrupted = bytearray(data)
        corrupted[2] ^= 0xFF  # flip the CRC byte
        assert device.decode_response(bytes(corrupted)) is None

    def test_decode_response_too_short_returns_none(self):
        device = _make_device()
        assert device.decode_response(b"\x01\x00\x00") is None

    def test_decode_response_timing_issue(self):
        device = _make_device()
        assert device.decode_response(b"\x01\x01\x00\x00\x00\x00") is None

    def test_decode_response_crc_error_in_request(self):
        device = _make_device()
        assert device.decode_response(b"\x01\x02\x00\x00\x00\x00") is None

    def test_decode_response_unknown_command(self):
        device = _make_device()
        assert device.decode_response(b"\x01\x03\x00\x00\x00\x00") is None

    def test_decode_response_register_not_supported_raises(self):
        device = _make_device()
        with pytest.raises(THZRegisterNotSupportedError):
            device.decode_response(b"\x01\x04\x00\x00\x00\x00")

    def test_decode_response_unknown_header_returns_none(self):
        device = _make_device()
        assert device.decode_response(b"\x09\x09\x00\x00\x00\x00") is None

    def test_decode_response_unexpected_exception_returns_none(self):
        device = _make_device()
        assert device.decode_response(None) is None


# ---------------------------------------------------------------------------
# read_write_register (unit-level, isolating send_request/decode_response)
# ---------------------------------------------------------------------------


class TestReadWriteRegisterUnit:
    def test_read_write_register_get_returns_decoded(self):
        device = _make_device()
        with patch.object(
            device, "send_request", return_value=b"raw"
        ) as mock_send, patch.object(
            device, "decode_response", return_value=b"decoded"
        ) as mock_decode:
            result = device.read_write_register(b"\xfb", "get")
        assert result == b"decoded"
        mock_send.assert_called_once()
        mock_decode.assert_called_once_with(b"raw")
        # get_or_set == "get" should use header 0x01 0x00
        telegram_sent = mock_send.call_args[0][0]
        assert telegram_sent.startswith(b"\x01\x00")

    def test_read_write_register_get_decode_failure_raises(self):
        device = _make_device()
        with patch.object(device, "send_request", return_value=b"raw"), patch.object(
            device, "decode_response", return_value=None
        ):
            with pytest.raises(RuntimeError, match="Failed to decode"):
                device.read_write_register(b"\xfb", "get")

    def test_read_write_register_set_returns_empty(self):
        device = _make_device()
        with patch.object(device, "send_request", return_value=b"ignored") as mock_send:
            result = device.read_write_register(b"\xfb", "set", b"\x01")
        assert result == b""
        telegram_sent = mock_send.call_args[0][0]
        assert telegram_sent.startswith(b"\x01\x80")


# ---------------------------------------------------------------------------
# read_firmware_version
# ---------------------------------------------------------------------------


class TestReadFirmwareVersion:
    def test_read_firmware_version_success(self):
        device = _make_device()
        with patch.object(device, "read_value", return_value=b"\x00\xce"):
            assert device.read_firmware_version() == "206"

    def test_read_firmware_version_none_response(self):
        device = _make_device()
        with patch.object(device, "read_value", return_value=None):
            assert device.read_firmware_version() == ""

    def test_read_firmware_version_oserror_returns_empty(self):
        device = _make_device()
        with patch.object(device, "read_value", side_effect=OSError("io")):
            assert device.read_firmware_version() == ""

    def test_read_firmware_version_runtimeerror_returns_empty(self):
        device = _make_device()
        with patch.object(device, "read_value", side_effect=RuntimeError("proto")):
            assert device.read_firmware_version() == ""


# ---------------------------------------------------------------------------
# read_value / write_value / read_block
# ---------------------------------------------------------------------------


class TestReadValueWriteValueReadBlock:
    def test_read_value_slices_response(self):
        device = _make_device()
        with patch.object(
            device, "read_write_register", return_value=b"\x00\x01\x02\x03\x04"
        ) as mock_rw:
            result = device.read_value(b"\xfb", "get", 2, 2)
        assert result == b"\x02\x03"
        mock_rw.assert_called_once_with(b"\xfb", "get")

    def test_write_value_calls_read_write_register(self):
        device = _make_device()
        with patch.object(device, "read_write_register") as mock_rw:
            device.write_value(b"\xfb", b"\x01\x02")
        mock_rw.assert_called_once_with(b"\xfb", "set", b"\x01\x02")

    def test_read_block_delegates(self):
        device = _make_device()
        with patch.object(
            device, "read_write_register", return_value=b"blockdata"
        ) as mock_rw:
            result = device.read_block(b"\x0a\x06\x48", "get")
        assert result == b"blockdata"
        mock_rw.assert_called_once_with(b"\x0a\x06\x48", "get")


# ---------------------------------------------------------------------------
# available_reading_blocks
# ---------------------------------------------------------------------------


class TestAvailableReadingBlocks:
    def test_available_reading_blocks_empty_when_no_manager(self):
        device = _make_device()
        assert device.available_reading_blocks == []

    def test_available_reading_blocks_lists_manager_keys(self):
        device = _make_device()
        mock_manager = MagicMock()
        mock_manager.get_all_registers.return_value = {"a": 1, "b": 2}
        device.register_map_manager = mock_manager
        assert sorted(device.available_reading_blocks) == ["a", "b"]


# ---------------------------------------------------------------------------
# async_initialize
# ---------------------------------------------------------------------------


class TestAsyncInitialize:
    @pytest.mark.asyncio
    async def test_async_initialize_unknown_connection_raises(self):
        device = _make_device(connection="bogus")
        with pytest.raises(ValueError, match="Unknown connection type"):
            await device.async_initialize(FakeHass())

    @pytest.mark.asyncio
    async def test_async_initialize_usb_low_firmware_no_cooling_probe(self):
        device = _make_device(connection="usb")
        with patch.object(device, "_connect_serial") as mock_connect, patch.object(
            device, "read_firmware_version", return_value="206"
        ), patch.object(device, "_probe_cooling_support") as mock_probe:
            await device.async_initialize(FakeHass())

        mock_connect.assert_called_once()
        mock_probe.assert_not_called()
        assert device._initialized is True
        assert device.firmware_version == "206"
        assert device.register_map_manager is not None
        assert device.write_register_map_manager is not None

    @pytest.mark.asyncio
    async def test_async_initialize_ip_high_firmware_runs_cooling_probe(self):
        device = _make_device(connection="ip", host="h", tcp_port=1)
        with patch.object(device, "_connect_tcp") as mock_connect, patch.object(
            device, "read_firmware_version", return_value="539"
        ), patch.object(
            device, "_probe_cooling_support", return_value=False
        ) as mock_probe:
            await device.async_initialize(FakeHass())

        mock_connect.assert_called_once()
        mock_probe.assert_called_once()
        assert device.has_cooling is False
        assert device._initialized is True

    @pytest.mark.asyncio
    async def test_async_initialize_high_firmware_with_cooling(self):
        device = _make_device(connection="usb")
        with patch.object(device, "_connect_serial"), patch.object(
            device, "read_firmware_version", return_value="539"
        ), patch.object(device, "_probe_cooling_support", return_value=True):
            await device.async_initialize(FakeHass())
        assert device.has_cooling is True

    @pytest.mark.asyncio
    async def test_async_initialize_none_firmware_raises(self):
        device = _make_device(connection="usb")
        with patch.object(device, "_connect_serial"), patch.object(
            device, "read_firmware_version", return_value=None
        ):
            with pytest.raises(RuntimeError, match="could not be determined"):
                await device.async_initialize(FakeHass())


# ---------------------------------------------------------------------------
# Full protocol round-trip integration tests (exercise the real stack
# end-to-end through a scripted fake serial device).
# ---------------------------------------------------------------------------


class TestFullRoundtripIntegration:
    def test_get_register_full_roundtrip(self):
        device = _make_device(read_timeout=1.0)
        # handshake1 response (0x10) + handshake2 response (0x10 0x02)
        # + data telegram (header 01 00, crc, payload, DLE ETX terminator)
        header = b"\x01\x00"
        payload = b"\x00\xc8\x05"
        crc = device.thz_checksum(header + b"\x00" + payload)
        telegram_response = header + crc + payload + b"\x10\x03"
        response_stream = b"\x10" + b"\x10\x02" + telegram_response

        fake_serial = ScriptedSerial(response_stream)
        device.ser = fake_serial

        decoded = device.read_write_register(b"\xfb", "get")

        assert decoded == crc + payload
        # Verify the full write sequence happened: STX (handshake1),
        # telegram, DLE (request data), STX (close).
        assert fake_serial.written.startswith(b"\x02")
        # One reset to flush stale bytes before handshake, one after handshake1.
        assert fake_serial.reset_calls == 2

    def test_set_register_full_roundtrip(self):
        device = _make_device(read_timeout=1.0)
        # Only handshake1 + handshake2 responses are needed for a "set".
        response_stream = b"\x10" + b"\x10\x02"
        fake_serial = ScriptedSerial(response_stream)
        device.ser = fake_serial

        result = device.write_value(b"\xfb", b"\x01\x02")

        assert result is None
        assert fake_serial.written.startswith(b"\x02")

    def test_get_register_handshake_failure_raises_after_retries(self):
        device = _make_device(read_timeout=0.05)
        # Handshake1 gets a wrong byte both times; reconnect uses the
        # (mocked) serial module, so _connect_serial succeeds but the new
        # connection also never produces a valid handshake byte.
        fake_serial = ScriptedSerial(b"\x99")
        device.ser = fake_serial

        with patch.object(device, "_reconnect"):
            with pytest.raises(RuntimeError, match="Handshake 1 failed"):
                device.send_request(b"telegram", "get")

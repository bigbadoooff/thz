"""Tests for connection timeout restoration fix.

This module tests that socket timeouts are properly restored after
_is_connection_alive() and _read_available() methods, preventing
the connection loss issue after ~20 hours.
"""

import socket
from unittest.mock import Mock

import pytest

from custom_components.thz.thz_device import THZDevice


class TestConnectionTimeoutRestoration:
    """Tests for socket timeout restoration in THZDevice."""

    def test_is_connection_alive_restores_timeout(self):
        """Test that _is_connection_alive restores socket timeout after check.

        This test verifies the fix for the issue where the socket timeout
        was not restored after calling _is_connection_alive(), which would
        cause connection problems after ~20 hours.
        """
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket
        mock_socket = Mock()
        mock_socket.fileno.return_value = 5  # Valid file descriptor
        mock_socket.gettimeout.return_value = 1.0  # Original timeout
        mock_socket.recv.side_effect = BlockingIOError  # No data available

        device.ser = mock_socket

        # Call _is_connection_alive
        result = device._is_connection_alive()

        # Verify connection is considered alive
        assert result is True

        # Verify timeout was restored
        # gettimeout should have been called once to save the timeout
        mock_socket.gettimeout.assert_called()
        # setblocking(False) should have been called
        mock_socket.setblocking.assert_called_with(False)
        # settimeout should have been called to restore the original timeout
        mock_socket.settimeout.assert_called_with(1.0)

    def test_is_connection_alive_restores_timeout_on_error(self):
        """Test that timeout is restored even when connection check fails.

        When the connection is detected as broken (recv raises OSError),
        the timeout should still be restored before returning False.
        """
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket
        mock_socket = Mock()
        mock_socket.fileno.return_value = 5  # Valid file descriptor
        mock_socket.gettimeout.return_value = 2.5  # Original timeout
        mock_socket.recv.side_effect = OSError("Connection reset")

        device.ser = mock_socket

        # Call _is_connection_alive
        result = device._is_connection_alive()

        # Verify connection is considered dead
        assert result is False

        # Verify timeout was still restored
        mock_socket.settimeout.assert_called_with(2.5)

    def test_read_available_restores_timeout(self):
        """Test that _read_available restores socket timeout after reading.

        This test verifies the fix where socket timeout was not restored
        after calling _read_available(), which could cause communication
        issues over time.
        """
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket
        mock_socket = Mock()
        mock_socket.gettimeout.return_value = 1.0  # Original timeout
        mock_socket.recv.return_value = b'\x10\x02'  # Some data
        mock_socket.fileno.return_value = 5  # Valid file descriptor

        device.ser = mock_socket

        # Call _read_available
        result = device._read_available()

        # Verify data was returned
        assert result == b'\x10\x02'

        # Verify timeout was saved and restored
        mock_socket.gettimeout.assert_called()
        mock_socket.setblocking.assert_called_with(False)
        mock_socket.settimeout.assert_called_with(1.0)

    def test_read_available_restores_timeout_on_blocking_io_error(self):
        """Test timeout is restored when BlockingIOError occurs.

        When no data is available (BlockingIOError), the timeout should
        still be restored.
        """
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket
        mock_socket = Mock()
        mock_socket.gettimeout.return_value = 3.0  # Original timeout
        mock_socket.recv.side_effect = BlockingIOError
        mock_socket.fileno.return_value = 5  # Valid file descriptor

        device.ser = mock_socket

        # Call _read_available
        result = device._read_available()

        # Should return empty bytes
        assert result == b""

        # Verify timeout was restored
        mock_socket.settimeout.assert_called_with(3.0)

    def test_read_available_restores_timeout_on_connection_error(self):
        """Test timeout restoration attempt on connection error.

        Even when a connection error occurs, we try to restore the timeout
        (though it may fail if socket is in bad state).
        """
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket
        mock_socket = Mock()
        mock_socket.gettimeout.return_value = 1.0  # Original timeout
        mock_socket.recv.side_effect = socket.error("Connection reset")
        mock_socket.fileno.return_value = 5  # Valid file descriptor

        device.ser = mock_socket

        # Call _read_available - should raise ConnectionError
        with pytest.raises(ConnectionError):
            device._read_available()

        # Verify timeout restoration was attempted
        mock_socket.settimeout.assert_called_with(1.0)

    def test_serial_connection_not_affected(self):
        """Test that serial connections are not affected by timeout changes.

        Serial connections don't use setblocking/settimeout, so we verify
        they still work correctly.
        """
        device = THZDevice(connection="usb", port="/dev/ttyUSB0")

        # Create a mock serial object with only serial-like attributes
        # Using spec to limit available attributes
        mock_serial = Mock(spec=['is_open', 'in_waiting', 'read', 'write', 'flush', 'close'])
        mock_serial.is_open = True
        mock_serial.in_waiting = 5
        mock_serial.read.return_value = b'\xaa\xbb\xcc\xdd\xee'

        device.ser = mock_serial

        # _is_connection_alive should work
        assert device._is_connection_alive() is True

        # _read_available should work
        result = device._read_available()
        assert result == b'\xaa\xbb\xcc\xdd\xee'
        mock_serial.read.assert_called_with(5)


class TestConnectionTimeoutEdgeCases:
    """Edge case tests for socket timeout handling."""

    def test_none_timeout_is_restored(self):
        """Test that None timeout (blocking mode) is properly restored."""
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket with None timeout (blocking)
        mock_socket = Mock()
        mock_socket.fileno.return_value = 5
        mock_socket.gettimeout.return_value = None  # Blocking mode
        mock_socket.recv.side_effect = BlockingIOError

        device.ser = mock_socket

        # Call _is_connection_alive
        result = device._is_connection_alive()

        # Verify timeout was restored to None
        mock_socket.settimeout.assert_called_with(None)

    def test_zero_timeout_is_restored(self):
        """Test that zero timeout (non-blocking mode) is properly restored."""
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket with zero timeout (non-blocking)
        mock_socket = Mock()
        mock_socket.fileno.return_value = 5
        mock_socket.gettimeout.return_value = 0.0  # Non-blocking mode
        mock_socket.recv.side_effect = BlockingIOError

        device.ser = mock_socket

        # Call _is_connection_alive
        device._is_connection_alive()

        # Verify timeout was restored to 0.0
        mock_socket.settimeout.assert_called_with(0.0)

    def test_settimeout_failure_is_ignored(self):
        """Test that settimeout failure is handled gracefully.

        If the socket is in a bad state and settimeout fails, we should
        not crash but continue operation.
        """
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        # Create a mock socket where settimeout fails
        mock_socket = Mock()
        mock_socket.fileno.return_value = 5
        mock_socket.gettimeout.return_value = 1.0
        mock_socket.recv.side_effect = BlockingIOError
        mock_socket.settimeout.side_effect = OSError("Bad socket state")

        device.ser = mock_socket

        # Call _is_connection_alive - should not raise
        result = device._is_connection_alive()

        # Should still return True (connection seemed alive)
        assert result is True


class TestReconnectOnProtocolErrors:
    """Tests reconnection behavior for protocol-level runtime errors."""

    def test_send_request_retries_after_runtime_error(self, monkeypatch):
        """RuntimeError should trigger reconnect and one retry."""
        device = THZDevice(connection="ip", host="192.168.1.100", tcp_port=2000)

        reconnect_mock = Mock()
        exchange_mock = Mock(
            side_effect=[RuntimeError("No valid response received"), b"\x01\x00"]
        )

        monkeypatch.setattr(device, "_reconnect", reconnect_mock)
        monkeypatch.setattr(device, "_exchange_once", exchange_mock)

        result = device.send_request(b"\x01\x00\x00\xfb\x10\x03", "get")

        assert result == b"\x01\x00"
        assert exchange_mock.call_count == 2
        reconnect_mock.assert_called_once()

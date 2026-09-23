"""Byte transports to the heat pump: a serial port or a ser2net TCP socket.

Blocking I/O; THZDevice runs it in the executor. A transport only moves
bytes. Framing, handshakes, timeouts and retries are the client's job
(thz_device).
"""

from __future__ import annotations

import contextlib
import logging
import socket
from typing import Any

import serial

from .exceptions import THZConnectionError

_LOGGER = logging.getLogger(__name__)


class THZTransport:
    """Common part of the serial and TCP transports."""

    def __init__(self) -> None:
        """Create the transport; ``connect`` opens it."""
        # The open serial port or socket; None while closed.
        self.ser: Any = None

    def connect(self, timeout: float) -> None:
        """Open the connection with ``timeout`` as its read timeout."""
        raise NotImplementedError

    def is_alive(self) -> bool:
        """Return True if the connection looks usable."""
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        """Send all of ``data``."""
        raise NotImplementedError

    def read_available(self) -> bytes:
        """Return the bytes available now, possibly none."""
        raise NotImplementedError

    def reset_input_buffer(self) -> None:
        """Drop unread input; only serial ports have an input buffer."""
        if self.ser is not None and hasattr(self.ser, "reset_input_buffer"):
            with contextlib.suppress(AttributeError):
                self.ser.reset_input_buffer()

    def close(self) -> None:
        """Close without raising; the next use has to connect again."""
        if self.ser is not None:
            with contextlib.suppress(Exception):
                self.ser.close()
            self.ser = None


class SerialTransport(THZTransport):
    """USB or serial port."""

    def __init__(self, port: str | None, baudrate: int) -> None:
        """Remember the port settings."""
        super().__init__()
        self.port = port
        self.baudrate = baudrate

    def connect(self, timeout: float) -> None:
        """Open the serial port."""
        _LOGGER.debug(
            "Opening serial connection: %s @ %s baud", self.port, self.baudrate
        )
        self.ser = serial.Serial(self.port, baudrate=self.baudrate, timeout=timeout)

    def is_alive(self) -> bool:
        """Return whether the port is open."""
        if self.ser is None:
            return False
        try:
            return self.ser.is_open  # type: ignore[no-any-return]
        except AttributeError:
            return False

    def write(self, data: bytes) -> None:
        """Write and flush ``data``."""
        try:
            self.ser.write(data)
            self.ser.flush()
        except OSError as e:
            _LOGGER.debug("Connection error during write: %s", e)
            raise THZConnectionError(f"Failed to write to connection: {e}") from e
        except (ValueError, AttributeError) as e:
            # pyserial's select.select() raises ValueError once close() has
            # set the fd to None; AttributeError if the port was closed
            # (ser = None) in the meantime.
            raise THZConnectionError(f"Connection closed during write: {e}") from e

    def read_available(self) -> bytes:
        """Return the bytes waiting in the port's buffer."""
        if self.ser is None:
            return b""
        try:
            waiting = getattr(self.ser, "in_waiting", 0)
            if waiting > 0:
                return self.ser.read(waiting)  # type: ignore[no-any-return]
            return b""
        except (OSError, serial.SerialException) as e:
            raise THZConnectionError(f"Serial read error: {e}") from e
        except (ValueError, AttributeError) as e:
            raise THZConnectionError(
                f"Connection closed during serial read: {e}"
            ) from e


class TcpTransport(THZTransport):
    """ser2net TCP socket."""

    def __init__(self, host: str | None, port: int | None) -> None:
        """Remember the address."""
        super().__init__()
        self.host = host
        self.port = port

    def connect(self, timeout: float) -> None:
        """Connect with TCP keepalive enabled.

        ser2net connections are idle between polls; keepalive keeps them
        from timing out.
        """
        _LOGGER.debug("Opening TCP connection: %s:%s", self.host, self.port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ser = sock
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # Linux-specific tuning; probe after 60 s idle, every 10 s, 6 times.
        try:
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
            _LOGGER.debug("TCP keepalive enabled with idle=60s, interval=10s, count=6")
        except (OSError, AttributeError) as e:
            _LOGGER.warning("Could not set TCP keepalive parameters: %s", e)

        sock.connect((self.host, self.port))
        _LOGGER.info("TCP connection established with keepalive enabled")

    def is_alive(self) -> bool:
        """Return False if the socket is closed or the peer hung up.

        A non-blocking MSG_PEEK returns b"" after the peer closed the
        connection and raises BlockingIOError while it is open but idle.
        """
        if self.ser is None:
            return False
        try:
            if self.ser.fileno() == -1:
                return False
            original_timeout = self.ser.gettimeout()
            self.ser.setblocking(False)
            try:
                if self.ser.recv(1, socket.MSG_PEEK) == b"":
                    return False
            except BlockingIOError:
                pass
            except OSError:
                return False
            finally:
                with contextlib.suppress(OSError):
                    self.ser.settimeout(original_timeout)
            return True
        except (OSError, AttributeError):
            return False

    def write(self, data: bytes) -> None:
        """Send all of ``data`` (sendall never sends a partial telegram)."""
        try:
            self.ser.sendall(data)
        except OSError as e:
            _LOGGER.debug("Connection error during write: %s", e)
            raise THZConnectionError(f"Failed to write to connection: {e}") from e
        except (ValueError, AttributeError) as e:
            raise THZConnectionError(f"Connection closed during write: {e}") from e

    def read_available(self) -> bytes:
        """Return what a non-blocking recv delivers."""
        if self.ser is None:
            return b""
        try:
            original_timeout = self.ser.gettimeout()
            self.ser.setblocking(False)
            data = self.ser.recv(1024)
        except BlockingIOError:
            return b""
        except OSError as e:
            _LOGGER.debug("TCP socket error during read: %s", e)
            raise THZConnectionError(f"TCP connection error: {e}") from e
        except (ValueError, AttributeError) as e:
            raise THZConnectionError(f"Connection closed during read: {e}") from e
        finally:
            # UnboundLocalError: gettimeout() itself raised above.
            with contextlib.suppress(OSError, AttributeError, UnboundLocalError):
                self.ser.settimeout(original_timeout)
        if not data:
            # A non-blocking recv() only returns b"" at end of stream: the
            # peer (e.g. a restarted ser2net) closed the connection.
            raise THZConnectionError("TCP socket connection closed by peer")
        return bytes(data)

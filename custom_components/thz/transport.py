"""Byte transports to the heat pump: a serial port or a ser2net TCP socket.

Both run on the event loop (asyncio); nothing blocks. A transport only
moves bytes. Framing, handshakes, timeouts and retries are the client's job
(thz_device).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import Any

import serial_asyncio_fast

from .exceptions import THZConnectionError

_LOGGER = logging.getLogger(__name__)

# ser2net connections are idle between polls; keepalive keeps them from
# timing out. Probe after 60 s idle, every 10 s, 6 times (Linux options).
_KEEPALIVE_OPTIONS = (
    ("TCP_KEEPIDLE", 60),
    ("TCP_KEEPINTVL", 10),
    ("TCP_KEEPCNT", 6),
)


class _ByteBuffer(asyncio.Protocol):
    """Collects received bytes until the client reads them."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.data_arrived = asyncio.Event()
        self.lost = False

    def data_received(self, data: bytes) -> None:
        self.buffer.extend(data)
        self.data_arrived.set()

    def eof_received(self) -> bool | None:
        # The peer (e.g. a restarted ser2net) closed the connection.
        self.lost = True
        self.data_arrived.set()
        return None

    def connection_lost(self, exc: Exception | None) -> None:
        self.lost = True
        self.data_arrived.set()


class THZTransport:
    """Common part of the serial and TCP transports."""

    def __init__(self) -> None:
        """Create the transport; ``connect`` opens it."""
        self._transport: asyncio.Transport | None = None
        self._protocol: _ByteBuffer | None = None

    async def connect(self) -> None:
        """Open the connection."""
        self.close()
        protocol = _ByteBuffer()
        try:
            self._transport = await self._open(protocol)
        except (OSError, TimeoutError) as e:
            raise THZConnectionError(f"Could not connect: {e}") from e
        self._protocol = protocol

    async def _open(self, protocol: _ByteBuffer) -> asyncio.Transport:
        raise NotImplementedError

    def is_alive(self) -> bool:
        """Return True while the connection is open and the peer is there."""
        return (
            self._transport is not None
            and self._protocol is not None
            and not self._transport.is_closing()
            and not self._protocol.lost
        )

    async def write(self, data: bytes) -> None:
        """Send all of ``data``."""
        transport = self._transport
        if transport is None or not self.is_alive():
            raise THZConnectionError("Connection closed during write")
        try:
            transport.write(data)
        except (OSError, RuntimeError) as e:
            _LOGGER.debug("Connection error during write: %s", e)
            raise THZConnectionError(f"Failed to write to connection: {e}") from e

    async def read(self, max_wait: float) -> bytes:
        """Return the received bytes, waiting up to ``max_wait`` s for the first.

        Returns b"" if nothing arrived in time.
        """
        protocol = self._protocol
        if protocol is None:
            raise THZConnectionError("Connection closed during read")
        if not protocol.buffer and not protocol.lost:
            protocol.data_arrived.clear()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(max(max_wait, 0)):
                    await protocol.data_arrived.wait()
        if protocol.buffer:
            data = bytes(protocol.buffer)
            protocol.buffer.clear()
            return data
        if protocol.lost:
            raise THZConnectionError("Connection closed by peer")
        return b""

    async def reset_input_buffer(self) -> None:
        """Drop unread input, including bytes the loop has not delivered yet."""
        # Let the event loop deliver what is already readable.
        await asyncio.sleep(0)
        if self._protocol is not None:
            self._protocol.buffer.clear()

    def close(self) -> None:
        """Close without raising; the next use has to connect again."""
        if self._transport is not None:
            with contextlib.suppress(OSError, RuntimeError):
                self._transport.close()
        self._transport = None
        self._protocol = None


class SerialTransport(THZTransport):
    """USB or serial port."""

    def __init__(self, port: str | None, baudrate: int) -> None:
        """Remember the port settings."""
        super().__init__()
        self.port = port
        self.baudrate = baudrate

    async def _open(self, protocol: _ByteBuffer) -> asyncio.Transport:
        if self.port is None:
            raise THZConnectionError("No serial port configured")
        _LOGGER.debug(
            "Opening serial connection: %s @ %s baud", self.port, self.baudrate
        )
        transport, _ = await serial_asyncio_fast.create_serial_connection(
            asyncio.get_running_loop(),
            lambda: protocol,
            self.port,
            baudrate=self.baudrate,
        )
        return transport

    async def reset_input_buffer(self) -> None:
        """Drop unread input, also the bytes still in the port's buffer."""
        port: Any = getattr(self._transport, "serial", None)
        if port is not None:
            with contextlib.suppress(OSError, ValueError, AttributeError):
                port.reset_input_buffer()
        await super().reset_input_buffer()


class TcpTransport(THZTransport):
    """ser2net TCP socket."""

    def __init__(
        self, host: str | None, port: int | None, connect_timeout: float
    ) -> None:
        """Remember the address and how long a connect may take."""
        super().__init__()
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout

    async def _open(self, protocol: _ByteBuffer) -> asyncio.Transport:
        if self.host is None or self.port is None:
            raise THZConnectionError("No host or port configured")
        _LOGGER.debug("Opening TCP connection: %s:%s", self.host, self.port)
        async with asyncio.timeout(self.connect_timeout):
            transport, _ = await asyncio.get_running_loop().create_connection(
                lambda: protocol, self.host, self.port
            )
        _enable_keepalive(transport.get_extra_info("socket"))
        _LOGGER.debug("TCP connection established")
        return transport


def _enable_keepalive(sock: Any) -> None:
    """Enable TCP keepalive on ``sock``; missing options are skipped."""
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for name, value in _KEEPALIVE_OPTIONS:
            if hasattr(socket, name):
                sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)
    except OSError as e:
        _LOGGER.warning("Could not set TCP keepalive parameters: %s", e)

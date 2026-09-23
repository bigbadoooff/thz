"""Tests for transport.py: the asyncio serial and TCP transports.

TCP runs against a real local asyncio server; the serial port is replaced at
serial_asyncio_fast.create_serial_connection.
"""

import asyncio
import contextlib
import socket
from unittest.mock import MagicMock, patch

import pytest

from custom_components.thz import transport as transport_module
from custom_components.thz.exceptions import THZConnectionError
from custom_components.thz.thz_device import THZDevice
from custom_components.thz.transport import SerialTransport, TcpTransport


@contextlib.asynccontextmanager
async def _server(handler):
    """Run a local TCP server; yields its port."""
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


async def _read_until(transport, size, max_wait=1.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait
    data = b""
    while len(data) < size and loop.time() < deadline:
        data += await transport.read(deadline - loop.time())
    return data


# ---------------------------------------------------------------------------
# TCP
# ---------------------------------------------------------------------------


class TestTcpTransport:
    @pytest.mark.asyncio
    async def test_bytes_go_both_ways(self):
        async def echo(reader, writer):
            writer.write(await reader.read(10))
            await writer.drain()

        async with _server(echo) as port:
            tcp = TcpTransport("127.0.0.1", port, connect_timeout=1.0)
            await tcp.connect()
            assert tcp.is_alive()
            await tcp.write(b"\x02\x10")
            assert await _read_until(tcp, 2) == b"\x02\x10"
            tcp.close()
        assert not tcp.is_alive()

    @pytest.mark.asyncio
    async def test_keepalive_is_enabled(self):
        async def idle(reader, writer):
            await reader.read()

        async with _server(idle) as port:
            tcp = TcpTransport("127.0.0.1", port, connect_timeout=1.0)
            await tcp.connect()
            sock = tcp._transport.get_extra_info("socket")
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
            if hasattr(socket, "TCP_KEEPIDLE"):
                assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == 60
            tcp.close()

    def test_keepalive_failure_is_tolerated(self):
        sock = MagicMock()
        sock.setsockopt.side_effect = OSError("not supported")
        transport_module._enable_keepalive(sock)
        transport_module._enable_keepalive(None)

    @pytest.mark.asyncio
    async def test_read_returns_nothing_when_no_data_arrives(self):
        async def idle(reader, writer):
            await reader.read()

        async with _server(idle) as port:
            tcp = TcpTransport("127.0.0.1", port, connect_timeout=1.0)
            await tcp.connect()
            assert await tcp.read(0.02) == b""
            assert tcp.is_alive()
            tcp.close()

    @pytest.mark.asyncio
    async def test_peer_close_is_detected(self):
        async def hang_up(reader, writer):
            writer.close()

        async with _server(hang_up) as port:
            tcp = TcpTransport("127.0.0.1", port, connect_timeout=1.0)
            await tcp.connect()
            with pytest.raises(THZConnectionError, match="closed by peer"):
                await tcp.read(1.0)
            assert not tcp.is_alive()
            with pytest.raises(THZConnectionError, match="closed"):
                await tcp.write(b"\x02")
            tcp.close()

    @pytest.mark.asyncio
    async def test_data_before_the_peer_close_is_still_read(self):
        async def answer_and_hang_up(reader, writer):
            writer.write(b"\x10")
            await writer.drain()
            writer.close()

        async with _server(answer_and_hang_up) as port:
            tcp = TcpTransport("127.0.0.1", port, connect_timeout=1.0)
            await tcp.connect()
            await asyncio.sleep(0.05)
            assert await tcp.read(1.0) == b"\x10"
            with pytest.raises(THZConnectionError):
                await tcp.read(1.0)
            tcp.close()

    @pytest.mark.asyncio
    async def test_reset_input_buffer_drops_unread_bytes(self):
        async def chatter(reader, writer):
            writer.write(b"stale")
            await writer.drain()
            await reader.read()

        async with _server(chatter) as port:
            tcp = TcpTransport("127.0.0.1", port, connect_timeout=1.0)
            await tcp.connect()
            await asyncio.sleep(0.05)
            await tcp.reset_input_buffer()
            assert await tcp.read(0.02) == b""
            tcp.close()

    @pytest.mark.asyncio
    async def test_refused_connection_raises(self):
        async with _server(lambda r, w: None) as port:
            pass  # closed again: nothing listens on the port any more
        tcp = TcpTransport("127.0.0.1", port, connect_timeout=1.0)
        with pytest.raises(THZConnectionError, match="Could not connect"):
            await tcp.connect()
        assert not tcp.is_alive()

    @pytest.mark.asyncio
    async def test_connect_timeout_raises(self):
        async def never(*args, **kwargs):
            await asyncio.sleep(10)

        tcp = TcpTransport("192.0.2.1", 2323, connect_timeout=0.01)
        loop = asyncio.get_running_loop()
        with (
            patch.object(loop, "create_connection", never),
            pytest.raises(THZConnectionError, match="Could not connect"),
        ):
            await tcp.connect()

    @pytest.mark.asyncio
    async def test_missing_address_raises(self):
        with pytest.raises(THZConnectionError, match="No host"):
            await TcpTransport(None, None, connect_timeout=1.0).connect()

    @pytest.mark.asyncio
    async def test_use_before_connect_raises(self):
        tcp = TcpTransport("127.0.0.1", 1, connect_timeout=1.0)
        assert not tcp.is_alive()
        with pytest.raises(THZConnectionError):
            await tcp.write(b"\x02")
        with pytest.raises(THZConnectionError):
            await tcp.read(0.01)
        await tcp.reset_input_buffer()
        tcp.close()


# ---------------------------------------------------------------------------
# Serial
# ---------------------------------------------------------------------------


class FakeSerialTransport(asyncio.Transport):
    """What serial_asyncio_fast returns: an asyncio transport with .serial."""

    def __init__(self):
        super().__init__()
        self.serial = MagicMock()
        self.written = []
        self.closing = False

    def write(self, data):
        self.written.append(bytes(data))

    def is_closing(self):
        return self.closing

    def close(self):
        self.closing = True


class TestSerialTransport:
    @staticmethod
    def _open(fake):
        async def create(loop, protocol_factory, url, **kwargs):
            protocol = protocol_factory()
            protocol.connection_made(fake)
            create.protocol = protocol
            create.url = url
            create.kwargs = kwargs
            return fake, protocol

        return create

    @pytest.mark.asyncio
    async def test_opens_the_port_and_moves_bytes(self):
        fake = FakeSerialTransport()
        create = self._open(fake)
        with patch.object(
            transport_module.serial_asyncio_fast, "create_serial_connection", create
        ):
            port = SerialTransport("/dev/ttyUSB0", 115200)
            await port.connect()

        assert create.url == "/dev/ttyUSB0"
        assert create.kwargs == {"baudrate": 115200}
        await port.write(b"\x02")
        assert fake.written == [b"\x02"]
        create.protocol.data_received(b"\x10")
        assert await port.read(0.01) == b"\x10"

    @pytest.mark.asyncio
    async def test_reset_input_buffer_also_flushes_the_port(self):
        fake = FakeSerialTransport()
        create = self._open(fake)
        with patch.object(
            transport_module.serial_asyncio_fast, "create_serial_connection", create
        ):
            port = SerialTransport("/dev/ttyUSB0", 115200)
            await port.connect()
        create.protocol.data_received(b"stale")
        await port.reset_input_buffer()
        fake.serial.reset_input_buffer.assert_called_once()
        assert await port.read(0.01) == b""

    @pytest.mark.asyncio
    async def test_lost_port_is_detected(self):
        fake = FakeSerialTransport()
        create = self._open(fake)
        with patch.object(
            transport_module.serial_asyncio_fast, "create_serial_connection", create
        ):
            port = SerialTransport("/dev/ttyUSB0", 115200)
            await port.connect()
        create.protocol.connection_lost(OSError("unplugged"))
        assert not port.is_alive()
        with pytest.raises(THZConnectionError):
            await port.read(1.0)

    @pytest.mark.asyncio
    async def test_open_failure_raises(self):
        async def fail(*args, **kwargs):
            raise OSError("no such port")

        with patch.object(
            transport_module.serial_asyncio_fast, "create_serial_connection", fail
        ):
            with pytest.raises(THZConnectionError, match="no such port"):
                await SerialTransport("/dev/ttyUSB9", 115200).connect()

    @pytest.mark.asyncio
    async def test_missing_port_raises(self):
        with pytest.raises(THZConnectionError, match="No serial port"):
            await SerialTransport(None, 115200).connect()

    @pytest.mark.asyncio
    async def test_write_errors_become_connection_errors(self):
        fake = FakeSerialTransport()
        fake.write = MagicMock(side_effect=OSError("I/O error"))
        with patch.object(
            transport_module.serial_asyncio_fast,
            "create_serial_connection",
            self._open(fake),
        ):
            port = SerialTransport("/dev/ttyUSB0", 115200)
            await port.connect()
        with pytest.raises(THZConnectionError, match="Failed to write"):
            await port.write(b"\x02")

    @pytest.mark.asyncio
    async def test_close_tolerates_errors_and_repeats(self):
        fake = FakeSerialTransport()
        fake.close = MagicMock(side_effect=OSError("already gone"))
        with patch.object(
            transport_module.serial_asyncio_fast,
            "create_serial_connection",
            self._open(fake),
        ):
            port = SerialTransport("/dev/ttyUSB0", 115200)
            await port.connect()
        port.close()
        port.close()
        assert not port.is_alive()


# ---------------------------------------------------------------------------
# The client over a real TCP connection
# ---------------------------------------------------------------------------


class TestClientOverTcp:
    @pytest.mark.asyncio
    async def test_register_read_and_write_over_a_socket(self):
        """A fake heat pump behind a socket answers a GET and a SET."""
        payload = b"\xfb\x00\xc8\x05"
        crc = THZDevice.thz_checksum(b"\x01\x00\x00" + payload)
        get_answer = b"\x01\x00" + crc + payload + b"\x10\x03"
        requests = []

        async def heat_pump(reader, writer):
            while True:
                data = await reader.read(1)
                if not data:
                    return
                if data == b"\x02" and (not requests or requests[-1] == "done"):
                    requests.append("start")
                    writer.write(b"\x10")
                elif data == b"\x01":
                    rest = await reader.readuntil(b"\x10\x03")
                    requests.append(data + rest)
                    writer.write(b"\x10\x02")
                elif data == b"\x10":
                    set_request = requests[-1][:2] == b"\x01\x80"
                    writer.write(b"\x01\x80\x81\x10\x03" if set_request else get_answer)
                elif data == b"\x02":
                    requests.append("done")
                await writer.drain()

        async with _server(heat_pump) as port:
            device = THZDevice(
                connection="ip", host="127.0.0.1", tcp_port=port, read_timeout=1.0
            )
            await device._connect()
            assert await device.read_block(b"\xfb", "get") == crc + payload
            await device.write_value(b"\x0a\x01\x12", b"\x00\x01")
            device.close()

        telegrams = [r for r in requests if isinstance(r, bytes)]
        assert [t[:2] for t in telegrams] == [b"\x01\x00", b"\x01\x80"]

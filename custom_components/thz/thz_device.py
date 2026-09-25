"""THZ device communication module.

This module provides the THZDevice class, the client that talks to
Stiebel Eltron LWZ / Tecalor THZ heat pumps over a serial port or ser2net.
All I/O runs on the event loop.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import logging
from typing import Any, TypeVar

from . import const, protocol
from .exceptions import (
    DEVICE_ERRORS,
    THZConnectionError,
    THZGarbledAnswerError,
    THZNotInitializedError,
    THZNotSupportedError,
    THZProtocolError,
    THZWriteRejectedError,
)
from .register_maps.register_map_manager import (
    RegisterMapManager,
    RegisterMapManagerWrite,
)
from .transport import SerialTransport, TcpTransport, THZTransport

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

# How long async_execute waits for the device lock before giving up, so
# coordinators cannot queue up indefinitely when many blocks fire at once.
_LOCK_WAIT_TIMEOUT = 20.0
# Tries of a GET whose answer arrives damaged (THZGarbledAnswerError).
_DECODE_ATTEMPTS = 2
# Hard limit for async_initialize: connecting, the firmware read and the
# cooling probe, each read with its one retry.
_INITIALIZE_TIMEOUT = 30.0


class THZDevice:
    """Represents the connection to the THZ heat pump."""

    def __init__(
        self,
        connection: str = "usb",
        port: str | None = None,
        host: str | None = None,
        tcp_port: int | None = None,
        baudrate: int = const.DEFAULT_BAUDRATE,
        read_timeout: float = const.TIMEOUT,
        firmware_override: str | None = None,
    ) -> None:
        """Initialize basic configuration - no communication yet."""
        self.connection = connection
        self.port = port
        self.host = host
        self.tcp_port = tcp_port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self._firmware_override = firmware_override
        self._initialized = False
        # Whether the last device call got through; a change is logged once
        # (warning when the connection is lost, info when it is back).
        self._link_ok = True

        self._transport: THZTransport = (
            TcpTransport(host, tcp_port, connect_timeout=read_timeout)
            if connection == "ip"
            else SerialTransport(port, baudrate)
        )
        # Placeholders
        self._firmware_version: str | None = None
        self.has_cooling: bool = True
        self.register_map_manager: RegisterMapManager | None = None
        self.write_register_map_manager: RegisterMapManagerWrite | None = None

        # Serialises device access across coroutines (see async_execute).
        self.lock = asyncio.Lock()
        # Whether the current exchange already sent its telegram.
        self._request_sent = False
        # Set by close(): a call still running must not open a new connection.
        self._closed = False

    # --- Protocol (protocol.py), kept as attributes for callers and tests
    # that use them through the device.

    thz_checksum = staticmethod(protocol.checksum)
    escape = staticmethod(protocol.escape)
    unescape = staticmethod(protocol.unescape)
    construct_telegram = staticmethod(protocol.construct_telegram)
    decode_response = staticmethod(protocol.decode_response)
    _frame_complete = staticmethod(protocol.frame_complete)
    _check_set_answer = staticmethod(protocol.check_set_answer)

    async def _connect(self) -> None:
        """Open the serial port or the ser2net TCP connection."""
        await self._transport.connect()

    def _force_close(self) -> None:
        """Close without raising; the next call reconnects."""
        self._transport.close()

    async def async_initialize(self) -> None:
        """Connect, read the firmware version and load its register maps.

        Runs under the device lock and a hard timeout like every device
        call. A failure closes the connection; it is not logged as a lost
        connection, because none was established yet (setup reports it).
        """
        _LOGGER.debug("Initializing THZ device (%s)", self.connection)
        if self.connection not in ("usb", "ip"):
            raise ValueError(f"Unknown connection type: {self.connection}")

        self._closed = False
        await self._async_call(
            self._initialize, (), _INITIALIZE_TIMEOUT, note_link=False
        )

    async def _initialize(self) -> None:
        """Do the work of async_initialize; the caller holds the lock."""
        await self._connect()
        self._firmware_version = await self.read_firmware_version()
        if not self._firmware_version:
            # Never guess a profile: an unanswered FD request would
            # otherwise fall through to the 4.39 default maps, including
            # their write commands.
            raise THZConnectionError("Firmware version could not be read")
        _LOGGER.debug("Firmware version detected: %s", self._firmware_version)

        effective_firmware = self._resolve_effective_firmware()
        if effective_firmware != self._firmware_version:
            _LOGGER.debug(
                "Firmware profile overridden: detected %s, forcing %s",
                self._firmware_version,
                effective_firmware,
            )

        # Probe for cooling support on 539-like firmware (v5.00+).
        # Devices like the LWZ404 run 539 firmware but lack cooling hardware;
        # they reply to cooling registers with an all-zero payload.
        # If detected, exclude the 539 cooling maps to avoid spurious entities.
        # This is keyed off the *effective* (possibly overridden) firmware,
        # since that's what actually determines whether 539 cooling maps load.
        fw_int = int(effective_firmware) if effective_firmware.isdigit() else 0
        if fw_int >= 500:
            self.has_cooling = await self._probe_cooling_support()
            if not self.has_cooling:
                _LOGGER.debug(
                    "Cooling not supported on this device; 539 cooling maps excluded"
                )

        self.register_map_manager = RegisterMapManager(
            effective_firmware, has_cooling=self.has_cooling
        )
        self.write_register_map_manager = RegisterMapManagerWrite(
            effective_firmware, has_cooling=self.has_cooling
        )

        self._initialized = True

    def _resolve_effective_firmware(self) -> str:
        """Return the firmware string to use for register-map selection.

        Normally this is whatever the device itself reported
        (``self._firmware_version``, kept as-is for display/diagnostics).
        If a ``firmware_override`` was configured to anything other than
        "auto", that value is used for register-map selection instead —
        e.g. forcing "439technician" independent of the raw detected
        value, or working around an auto-detected string with no dedicated
        entry in ``FIRMWARE_MAPS``.
        """
        if (
            self._firmware_override
            and self._firmware_override != const.FIRMWARE_OVERRIDE_AUTO
        ):
            return self._firmware_override
        if self._firmware_version is None:
            raise THZNotInitializedError(
                "Device not initialized or firmware version unknown"
            )
        return self._firmware_version

    async def _reconnect(self) -> None:
        """Close the connection and open it again (not after close())."""
        if self._closed:
            raise THZConnectionError("Device closed")
        _LOGGER.debug("Reconnecting")
        self._force_close()
        try:
            await self._connect()
        except THZConnectionError as e:
            _LOGGER.debug("Reconnection failed: %s", e)
            raise
        _LOGGER.debug("Reconnected")

    async def _do_handshake_1(self) -> None:
        """Perform handshake step 1: send 0x02 and expect 0x10.

        Raises:
            THZProtocolError: If the device response is not 0x10.
        """
        await self._transport.write(const.STARTOFTEXT)
        response = await self._read_exact(1, self.read_timeout)
        if response != const.DATALINKESCAPE:
            resp_hex = response.hex() if response else "no data"
            error_msg = f"Handshake 1 failed, received: {resp_hex}"
            _LOGGER.debug(error_msg)
            raise THZProtocolError(error_msg)

    async def _do_handshake_2(self) -> None:
        """Perform handshake step 2: read and validate 0x10 0x02.

        Handles the firmware quirk where the device may send 0x10 and 0x02
        separately (with a short delay for firmware 2.x).

        Raises:
            THZProtocolError: If the combined two-byte response is not 0x10 0x02.
        """
        response = await self._read_exact(2, self.read_timeout)

        if response == const.DATALINKESCAPE:
            # Device sent only 0x10 so far; wait for the trailing 0x02
            _LOGGER.debug("Received 0x10, waiting for 0x02...")
            fw_ver = self._firmware_version
            if fw_ver and fw_ver.startswith("2"):
                # Add delay for firmware 2.x as per Perl module
                await asyncio.sleep(0.005)
            second_byte = await self._read_exact(1, self.read_timeout)
            if second_byte == const.STARTOFTEXT:
                response = const.DATALINKESCAPE + const.STARTOFTEXT
            else:
                byte_hex = second_byte.hex() if second_byte else "no data"
                error_msg = f"Handshake 2 failed: received 0x10 then {byte_hex}"
                _LOGGER.debug(error_msg)
                raise THZProtocolError(error_msg)
        elif response == const.STARTOFTEXT:
            # Sometimes device sends just 0x02 (as per Perl code line 1525)
            _LOGGER.debug("Received only 0x02 as response")
            response = const.DATALINKESCAPE + const.STARTOFTEXT

        if response != const.DATALINKESCAPE + const.STARTOFTEXT:
            resp_hex = response.hex() if response else "no data"
            error_msg = f"Handshake 2 failed, received: {resp_hex}"
            _LOGGER.debug(error_msg)
            raise THZProtocolError(error_msg)

    async def _receive_data_telegram(self) -> bytes:
        """Send confirmation and read the answer until its 0x10 0x03 terminator.

        Returns:
            The raw data telegram bytes (including the 0x10 0x03 terminator),
            or a single NAK byte.

        Raises:
            THZProtocolError: If no valid data telegram is received within timeout.
        """
        await self._transport.write(const.DATALINKESCAPE)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.read_timeout
        data = bytearray()
        while not (self._frame_complete(data) or data == const.NAK):
            remaining = deadline - loop.time()
            if remaining <= 0:
                error_msg = (
                    "No valid response received after data request - "
                    "timeout or incomplete data"
                )
                _LOGGER.debug(error_msg)
                raise THZProtocolError(error_msg)
            data.extend(await self._transport.read(remaining))

        return bytes(data)

    async def _exchange_once(
        self, telegram: bytes, get_or_set: str, attempt: int, max_retries: int
    ) -> bytes:
        """Perform one complete protocol exchange attempt.

        Checks connection health, runs both handshake steps, reads the
        device's answer, and sends the closing byte.

        Args:
            telegram: Encoded telegram bytes to send.
            get_or_set: "get" to receive data; any other value for set-only.
            attempt: Current attempt index (0-based), used for log messages.
            max_retries: Total retries allowed, used for log messages.

        Returns:
            Response bytes (empty for set operations).

        Raises:
            THZConnectionError: If the underlying connection is broken.
            THZProtocolError: If a protocol/handshake error occurs.
        """
        if self._initialized and not self._transport.is_alive():
            _LOGGER.debug(
                "Connection not alive, reconnecting (attempt %d/%d)",
                attempt + 1,
                max_retries + 1,
            )
            await self._reconnect()

        # Flush stale bytes before handshake — boot-up sequences from the
        # heatpump or leftover bytes from a previous failed attempt would
        # otherwise be read as the 0x10 response to our 0x02 STX byte.
        await self._transport.reset_input_buffer()

        await self._do_handshake_1()

        await self._transport.reset_input_buffer()
        await self._transport.write(telegram)
        self._request_sent = True

        await self._do_handshake_2()

        if get_or_set == "get":
            data = await self._receive_data_telegram()
            if data == const.NAK:
                raise THZProtocolError("Device answered the request with NAK")
        else:
            # Like FHEM's THZ_Get_Comunication, read the device's answer to a
            # SET too and require its acknowledgement (see _check_set_answer).
            answer = await self._receive_data_telegram()
            self._check_set_answer(answer)
            data = b""

        await self._transport.write(const.STARTOFTEXT)
        return data

    async def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        """Send a request and receive the response, reconnecting once if needed.

        Raises:
            THZConnectionError: If connection fails and reconnection is unsuccessful.
            THZProtocolError: If device communication fails (handshake, timeout,
                invalid response).
        """
        max_retries = 1  # Allow one retry on connection error

        for attempt in range(max_retries + 1):
            self._request_sent = False
            try:
                return await self._exchange_once(
                    telegram, get_or_set, attempt, max_retries
                )

            except (THZNotSupportedError, THZWriteRejectedError):
                raise  # legitimate device response — no reconnect, no retry

            except (THZConnectionError, THZProtocolError) as e:
                _LOGGER.debug(
                    "%s in send_request (attempt %d/%d): %s",
                    type(e).__name__,
                    attempt + 1,
                    max_retries + 1,
                    e,
                )
                if attempt < max_retries and self._may_retry(get_or_set):
                    try:
                        await self._reconnect()
                        continue
                    except THZConnectionError as reconnect_error:
                        _LOGGER.debug("Reconnect failed: %s", reconnect_error)
                if isinstance(e, THZConnectionError):
                    raise THZConnectionError(
                        f"Connection failed after {attempt + 1} attempts: {e}"
                    ) from e
                raise

        # Every iteration returns, raises or retries; the last never retries.
        raise THZProtocolError("send_request failed without specific error")

    def _may_retry(self, get_or_set: str) -> bool:
        """Return True if a failed exchange may be repeated.

        A GET is always safe to repeat. A SET is only repeated if it failed
        before the telegram went out; once sent, the device may already have
        applied it, and callers such as the D1 fault-memory clear rely on a
        write being sent at most once.
        """
        if get_or_set == "get" or not self._request_sent:
            return True
        _LOGGER.warning(
            "Not repeating a SET that was already sent; the device may or "
            "may not have applied it"
        )
        return False

    async def _read_exact(self, size: int, max_wait: float) -> bytes:
        """Read ``size`` bytes, or fewer if ``max_wait`` seconds run out first."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait
        buf = bytearray()
        while len(buf) < size:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            buf.extend(await self._transport.read(remaining))
        return bytes(buf)

    async def async_execute(
        self,
        fn: Callable[..., Awaitable[_T]],
        *args: Any,
        timeout: float = 8.0,  # noqa: ASYNC109 - bounds the whole device call
    ) -> _T:
        """Run the device call ``fn(*args)`` with the lock held and a hard timeout.

        Every device access goes through here, so only one exchange is on
        the line at a time. The lock wait is capped at 20 seconds; on
        timeout the call is cancelled and ``THZConnectionError`` raised.

        On any failure except a "register not supported" answer the
        connection is closed, so the next call starts on a fresh one.
        """
        return await self._async_call(fn, args, timeout, note_link=True)

    async def _async_call(
        self,
        fn: Callable[..., Awaitable[_T]],
        args: tuple[Any, ...],
        timeout: float,  # noqa: ASYNC109 - bounds the whole device call
        *,
        note_link: bool,
    ) -> _T:
        """Run ``fn(*args)`` as async_execute describes.

        ``note_link`` records whether the heat pump answered (see
        _note_link); async_initialize skips that.
        """
        note = self._note_link if note_link else _ignore_link
        try:
            async with asyncio.timeout(_LOCK_WAIT_TIMEOUT):
                await self.lock.acquire()
        except TimeoutError:
            raise THZConnectionError(
                f"Device busy: could not acquire lock within {_LOCK_WAIT_TIMEOUT:.0f}s"
            ) from None

        try:
            async with asyncio.timeout(timeout):
                result = await fn(*args)
        except TimeoutError:
            self._force_close()
            err = THZConnectionError(f"Device communication timed out after {timeout}s")
            note(err)
            raise err from None
        except THZNotSupportedError:
            # The device said "not supported": the connection is fine, keep it.
            note(None)
            raise
        except BaseException as err:
            self._force_close()
            if isinstance(err, THZWriteRejectedError):
                note(None)  # rejected, but the device answered
            elif isinstance(err, DEVICE_ERRORS):
                note(err)
            raise
        finally:
            self.lock.release()
        note(None)
        return result

    @property
    def link_ok(self) -> bool:
        """Return whether the last device call got through."""
        return self._link_ok

    def _note_link(self, err: BaseException | None) -> None:
        """Log a lost or restored connection once per change."""
        if err is None:
            if not self._link_ok:
                self._link_ok = True
                _LOGGER.info("The heat pump answers again")
            return
        if self._link_ok:
            self._link_ok = False
            _LOGGER.warning("The heat pump does not answer: %s", err)
        else:
            _LOGGER.debug("Heat pump still unreachable: %s", err)

    def close(self) -> None:
        """Close the connection for good; safe to call repeatedly, never raises.

        A call still running (e.g. a coordinator refresh during unload) then
        fails instead of reconnecting, so the closed device cannot hold the
        port or the ser2net connection a reloaded entry needs.
        """
        self._closed = True
        self._force_close()

    async def read_write_register(
        self,
        addr_bytes: bytes,
        get_or_set: str = "get",
        payload_to_deliver: bytes = b"",
    ) -> bytes:
        """Reads or writes a register from/to the THZ device.

        Raises:
            THZConnectionError: If connection fails
            THZProtocolError: If device communication fails
            THZNotSupportedError: If the device reports the register is
                not supported
        """
        telegram = protocol.build_telegram(get_or_set, addr_bytes + payload_to_deliver)
        if get_or_set != "get":
            await self.send_request(telegram, get_or_set)
            return b""
        # A damaged answer (THZGarbledAnswerError) is a transient line
        # problem: a GET is asked once more. The exchange itself completed,
        # so the line is in step for the next one.
        attempt = 1
        while True:
            raw_response = await self.send_request(telegram, get_or_set)
            try:
                return protocol.decode_answer(raw_response)
            except THZGarbledAnswerError as err:
                if attempt >= _DECODE_ATTEMPTS:
                    raise
                _LOGGER.debug("Asking %s again: %s", addr_bytes.hex(), err)
                attempt += 1

    async def read_firmware_version(self) -> str:
        """Reads the firmware version from the THZ device.

        - Address (Register): 0xFD
        - Offset: 2
        - Length: 2 bytes
        - Interpreted as: unsigned big-endian integer
        """
        try:
            value_raw = await self.read_value(b"\xfd", "get", 2, 2)
            if value_raw is None:
                _LOGGER.error("Could not read firmware version: no response")
                return ""
            firmware_version = int.from_bytes(value_raw, byteorder="big", signed=False)
            _LOGGER.debug("Firmware version read: %s", firmware_version)
            return str(firmware_version)
        except DEVICE_ERRORS as e:
            _LOGGER.warning("Could not read firmware version: %s", e)
            return ""

    async def _probe_cooling_support(self) -> bool:
        """Probe whether the device supports cooling hardware.

        Reads the cooling HC total energy register (command 0A0648).
        Devices without cooling hardware (e.g. LWZ404) return an all-zero
        payload for this register, which is the detection pattern described
        in the issue report.

        Returns:
            True if cooling is supported, False if the payload is all zeros.
        """
        try:
            result = await self.read_block(bytes.fromhex("0A0648"), "get")
            # Response layout: [checksum, addr0, addr1, addr2, val0, val1, ...]
            # Bytes 4-5 hold the register value; all zeros = no cooling hardware.
            if len(result) >= 6 and result[4:6] == b"\x00\x00":
                _LOGGER.debug(
                    "Cooling probe: register 0A0648 returned zero payload - no cooling"
                )
                return False
            return True
        except DEVICE_ERRORS as e:
            _LOGGER.warning(
                "Cooling probe failed, assuming cooling is supported: %s", e
            )
            return True

    async def read_value(
        self, addr_bytes: bytes, get_or_set: str, offset: int, length: int
    ) -> bytes:
        r"""Read a value from the THZ device.

        Args:
            addr_bytes: Register address bytes (e.g. b'\xfb').
            get_or_set: Operation type, "get" or "set".
            offset: Byte offset in the response to read from.
            length: Number of bytes to read from the response.

        Returns:
            The requested bytes from the device response.
        """
        response = await self.read_write_register(addr_bytes, get_or_set)
        return response[offset : offset + length]

    async def write_value(self, addr_bytes: bytes, value: bytes) -> None:
        r"""Write a value to the THZ device.

        Args:
            addr_bytes: Register address bytes (e.g. b'\xfb').
            value: Bytes to write to the device.
        """
        await self.read_write_register(addr_bytes, "set", value)
        _LOGGER.debug("Value %s written to address %s", value, addr_bytes.hex())

    async def update_value(
        self,
        addr_bytes: bytes,
        offset: int,
        length: int,
        updates: Mapping[int, int],
    ) -> None:
        """Replace single bytes of a register value, keeping the others.

        Reads ``length`` bytes at ``offset``, sets the byte at each index of
        ``updates`` and writes the value back. Run through async_execute,
        so no other request reaches the line between the read and the write.

        Raises:
            THZProtocolError: If the device answers fewer than ``length``
                bytes; writing a padded value would overwrite the rest.
        """
        current = bytearray(await self.read_value(addr_bytes, "get", offset, length))
        if len(current) < length:
            raise THZProtocolError(
                f"update_value: register {addr_bytes.hex()} answered "
                f"{len(current)} of {length} bytes"
            )
        for index, value in updates.items():
            current[index] = value
        await self.write_value(addr_bytes, bytes(current))

    async def write_block_value(
        self,
        block_addr: bytes,
        offset: int,
        length: int,
        value: bytes,
        mask: int | None = None,
    ) -> None:
        r"""Write a value inside a register block using read-modify-write (2xx).

        2xx firmware devices do not support writing individual parameters directly.
        Instead the entire block must be read first, the target bytes modified, and
        the complete block written back.

        The ``offset`` and ``length`` parameters use the same coordinate system as the
        register map tuples in ``register_map_206`` (i.e. relative to the full decoded
        response which starts with the CRC byte at index 0).

        Args:
            block_addr: Single-byte block address (e.g. b'\x17' for block "pxx17").
            offset: Byte offset of the parameter within the decoded block response,
                    which starts with the CRC byte at index 0 followed by the
                    echoed block address.
            length: Number of bytes occupied by the parameter value.
            value: Encoded bytes to write (must be exactly ``length`` bytes).
            mask: Optional bit mask applied to every target byte; only the
                masked bits are taken from ``value``, the others are kept
                (used for single-bit flags that share a byte).

        Raises:
            ValueError: If ``value`` is not ``length`` bytes, or if the offset/length
                        is out of range for the block.
            THZProtocolError: If the device read or write fails, or the read-back
                block does not echo ``block_addr``.
        """
        if len(value) != length:
            raise ValueError(
                f"write_block_value: value length {len(value)} != expected {length}"
            )

        # Read the current block. decode_response returns
        # [CRC] + [address echo] + [data]; only the data is sent back, since
        # read_write_register prepends block_addr itself (FHEM's THZ_Set
        # likewise re-encodes the read-back message with the address once).
        response = await self.read_write_register(block_addr, "get")
        header_len = 1 + len(block_addr)
        echo = response[1:header_len]
        if echo != block_addr:
            raise THZProtocolError(
                f"write_block_value: unexpected address echo {echo.hex()} "
                f"for block {block_addr.hex()}"
            )
        payload = bytearray(response[header_len:])

        # Register map offsets are relative to the full decoded response (CRC
        # at 0, address echo after it), so shift them into the data slice.
        payload_offset = offset - header_len
        if payload_offset < 0 or payload_offset + length > len(payload):
            raise ValueError(
                f"write_block_value: offset={offset}/length={length} out of range "
                f"for block {block_addr.hex()} (payload size {len(payload)})"
            )

        if mask is None:
            payload[payload_offset : payload_offset + length] = value
        else:
            for i, byte in enumerate(value):
                old = payload[payload_offset + i]
                payload[payload_offset + i] = (old & ~mask & 0xFF) | (byte & mask)

        # Write the modified payload back to the device.
        await self.read_write_register(block_addr, "set", bytes(payload))
        _LOGGER.debug(
            "Block value written: block=%s offset=%d length=%d value=%s",
            block_addr.hex(),
            offset,
            length,
            value.hex(),
        )

    async def read_block(self, addr_bytes: bytes, get_or_set: str) -> bytes:
        r"""Read a block from the THZ device.

        Args:
            addr_bytes: bytes (e.g. b'\xfb')
            get_or_set: "get" or "set"

        Returns:
            block read from the device
        """
        return await self.read_write_register(addr_bytes, get_or_set)

    @property
    def firmware_version(self) -> str:
        """Return the firmware version of the device."""
        if self._firmware_version is None:
            raise THZNotInitializedError(
                "Device not initialized or firmware version unknown"
            )
        return self._firmware_version

    @property
    def firmware_profile(self) -> str:
        """Return the firmware profile the register maps were chosen for.

        The forced override if one is configured, else the reported firmware.
        """
        return self._resolve_effective_firmware()

    @property
    def available_reading_blocks(self) -> list[str]:
        """Return the available reading blocks of the device."""
        if self.register_map_manager:
            return list(self.register_map_manager.get_all_registers().keys())
        return []


def _ignore_link(err: BaseException | None) -> None:
    """Stand in for THZDevice._note_link where the link is not tracked."""

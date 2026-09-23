"""THZ device communication module.

This module provides the THZDevice class which handles serial and TCP
communication with Stiebel Eltron LWZ / Tecalor THZ heat pumps.
"""

import asyncio
from collections.abc import Callable
import contextlib
import logging
import threading
import time
from typing import Any

from homeassistant.core import HomeAssistant

from . import const, protocol
from .exceptions import (
    DEVICE_ERRORS,
    THZConnectionError,
    THZNotInitializedError,
    THZNotSupportedError,
    THZProtocolError,
)
from .register_maps.register_map_manager import (
    RegisterMapManager,
    RegisterMapManagerWrite,
)
from .transport import SerialTransport, TcpTransport, THZTransport

_LOGGER = logging.getLogger(__name__)


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

        self._transport: THZTransport = (
            TcpTransport(host, tcp_port)
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
        # Per-thread abandon signal of the async_execute call being served.
        self._call_state = threading.local()
        # Whether the current exchange already sent its telegram.
        self._request_sent = False

        # ---------------------------------------------------------------------

    # --- Transport (transport.py); thin wrappers so the exchange code and
    # its tests address one object.

    @property
    def ser(self) -> Any:
        """The open serial port or socket of the transport; None if closed."""
        return self._transport.ser

    @ser.setter
    def ser(self, value: Any) -> None:
        self._transport.ser = value

    def _connect_serial(self) -> None:
        """Open the serial port."""
        self._transport.connect(self.read_timeout)

    def _connect_tcp(self) -> None:
        """Open the ser2net TCP connection."""
        self._transport.connect(self.read_timeout)

    def _is_connection_alive(self) -> bool:
        return self._transport.is_alive()

    def _write_bytes(self, data: bytes) -> None:
        self._transport.write(data)

    def _read_available(self) -> bytes:
        return self._transport.read_available()

    def _reset_input_buffer(self) -> None:
        self._transport.reset_input_buffer()

    def _force_close(self) -> None:
        """Close without raising; the next call reconnects."""
        self._transport.close()

    # --- Protocol (protocol.py), kept as attributes for callers and tests
    # that use them through the device.

    thz_checksum = staticmethod(protocol.checksum)
    escape = staticmethod(protocol.escape)
    unescape = staticmethod(protocol.unescape)
    construct_telegram = staticmethod(protocol.construct_telegram)
    decode_response = staticmethod(protocol.decode_response)
    _frame_complete = staticmethod(protocol.frame_complete)
    _check_set_answer = staticmethod(protocol.check_set_answer)

    async def async_initialize(self, hass: HomeAssistant) -> None:
        """Open connection and initialize firmware-dependent data structures."""
        _LOGGER.debug("Initializing THZ device (%s)", self.connection)

        if self.connection == "usb":
            connect = self._connect_serial
        elif self.connection == "ip":
            connect = self._connect_tcp
        else:
            raise ValueError(f"Unknown connection type: {self.connection}")

        try:
            # Opening the port / TCP connect blocks, so keep it off the loop.
            await hass.async_add_executor_job(connect)
            self._firmware_version = await hass.async_add_executor_job(
                self.read_firmware_version
            )
            if not self._firmware_version:
                # Never guess a profile: an unanswered FD request would
                # otherwise fall through to the 4.39 default maps, including
                # their write commands.
                raise THZConnectionError("Firmware version could not be read")
        except BaseException:
            self._force_close()
            raise
        _LOGGER.info("Firmware version detected: %s", self._firmware_version)

        effective_firmware = self._resolve_effective_firmware()
        if effective_firmware != self._firmware_version:
            _LOGGER.info(
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
            self.has_cooling = await hass.async_add_executor_job(
                self._probe_cooling_support
            )
            if not self.has_cooling:
                _LOGGER.info(
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

    def _raise_if_abandoned(self) -> None:
        """Stop a worker thread whose async_execute call already gave up.

        Once async_execute has timed out it may hand the device to the next
        caller, so the old thread must neither reconnect nor send anything.
        """
        abandoned: threading.Event | None = getattr(self._call_state, "abandoned", None)
        if abandoned is not None and abandoned.is_set():
            raise THZConnectionError("Device call abandoned after its timeout")

    def _run_abandonable(
        self, abandoned: threading.Event, fn: Callable[..., Any], *args: Any
    ) -> Any:
        """Run ``fn`` in this worker thread with its abandon signal attached."""
        self._call_state.abandoned = abandoned
        try:
            return fn(*args)
        finally:
            self._call_state.abandoned = None

    def _reconnect(self):
        """Attempt to reconnect if connection was lost."""
        self._raise_if_abandoned()
        _LOGGER.warning("Attempting to reconnect...")
        try:
            if self.ser is not None:
                with contextlib.suppress(OSError):
                    self.ser.close()

            if self.connection == "usb":
                self._connect_serial()
            elif self.connection == "ip":
                self._connect_tcp()

            _LOGGER.info("Reconnection successful")
        except OSError as e:
            _LOGGER.debug("Reconnection failed: %s", e)
            raise

    def _do_handshake_1(self, timeout: float) -> None:
        """Perform handshake step 1: send 0x02 and expect 0x10.

        Args:
            timeout: Read timeout in seconds.

        Raises:
            THZProtocolError: If the device response is not 0x10.
        """
        self._write_bytes(const.STARTOFTEXT)
        response = self._read_exact(1, timeout)
        if response != const.DATALINKESCAPE:
            resp_hex = response.hex() if response else "no data"
            error_msg = f"Handshake 1 failed, received: {resp_hex}"
            _LOGGER.debug(error_msg)
            raise THZProtocolError(error_msg)

    def _do_handshake_2(self, timeout: float) -> None:
        """Perform handshake step 2: read and validate 0x10 0x02.

        Handles the firmware quirk where the device may send 0x10 and 0x02
        separately (with a short delay for firmware 2.x).

        Args:
            timeout: Read timeout in seconds.

        Raises:
            THZProtocolError: If the combined two-byte response is not 0x10 0x02.
        """
        response = self._read_exact(2, timeout)

        if response == const.DATALINKESCAPE:
            # Device sent only 0x10 so far; wait for the trailing 0x02
            _LOGGER.debug("Received 0x10, waiting for 0x02...")
            fw_ver = self._firmware_version
            if fw_ver and fw_ver.startswith("2"):
                # Add delay for firmware 2.x as per Perl module
                # time.sleep() is used because this runs in executor (blocking)
                time.sleep(0.005)
            second_byte = self._read_exact(1, timeout)
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

    def _receive_data_telegram(
        self, timeout: float, min_length: int = protocol.DATA_TELEGRAM_MIN
    ) -> bytes:
        """Send confirmation and read data telegram until 0x10 0x03 terminator.

        Args:
            timeout: Read timeout in seconds.
            min_length: Shortest frame accepted, see _frame_complete.

        Returns:
            The raw data telegram bytes (including the 0x10 0x03 terminator),
            or a single NAK byte.

        Raises:
            THZProtocolError: If no valid data telegram is received within timeout.
        """
        self._write_bytes(const.DATALINKESCAPE)

        data = bytearray()
        start_time = time.time()
        while time.time() - start_time < timeout:
            chunk = self._read_available()
            if chunk:
                data.extend(chunk)
                if self._frame_complete(data, min_length) or data == const.NAK:
                    break
            else:
                # Avoid busy-waiting when no data is currently available
                time.sleep(0.01)

        if not self._frame_complete(data, min_length) and data != const.NAK:
            error_msg = (
                "No valid response received after data request - "
                "timeout or incomplete data"
            )
            _LOGGER.debug(error_msg)
            raise THZProtocolError(error_msg)

        return bytes(data)

    def _exchange_once(
        self, telegram: bytes, get_or_set: str, attempt: int, max_retries: int
    ) -> bytes:
        """Perform one complete protocol exchange attempt.

        Checks connection health, runs both handshake steps, optionally reads
        the data telegram, and sends the closing byte.

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
        timeout = self.read_timeout
        self._raise_if_abandoned()

        if self._initialized and not self._is_connection_alive():
            _LOGGER.warning(
                "Connection not alive, attempting reconnect (attempt %d/%d)",
                attempt + 1,
                max_retries + 1,
            )
            self._reconnect()

        # Flush stale bytes before handshake — boot-up sequences from the
        # heatpump or leftover bytes from a previous failed attempt would
        # otherwise be read as the 0x10 response to our 0x02 STX byte.
        self._reset_input_buffer()

        self._do_handshake_1(timeout)

        self._reset_input_buffer()
        self._write_bytes(telegram)
        self._request_sent = True

        self._do_handshake_2(timeout)

        if get_or_set == "get":
            data = self._receive_data_telegram(timeout)
            if data == const.NAK:
                raise THZProtocolError("Device answered the request with NAK")
        else:
            # Like FHEM's THZ_Get_Comunication, read the device's answer to a
            # SET too and require its acknowledgement (see _check_set_answer).
            answer = self._receive_data_telegram(
                timeout, min_length=protocol.SET_ANSWER_MIN
            )
            self._check_set_answer(answer)
            data = b""

        self._write_bytes(const.STARTOFTEXT)
        return data

    def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        """Send request via USB or TCP, receive response.

        Automatically reconnects if connection is lost.

        Raises:
            THZConnectionError: If connection fails and reconnection is unsuccessful.
            THZProtocolError: If device communication fails (handshake, timeout,
                invalid response).
        """
        max_retries = 1  # Allow one retry on connection error

        for attempt in range(max_retries + 1):
            self._request_sent = False
            try:
                return self._exchange_once(telegram, get_or_set, attempt, max_retries)

            except ConnectionError as e:
                # Final failures are raised and reported once by the caller.
                _LOGGER.debug(
                    "Connection error in send_request (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries + 1,
                    e,
                )
                if attempt < max_retries and self._may_retry(get_or_set):
                    try:
                        self._reconnect()
                        continue
                    except OSError as reconnect_error:
                        _LOGGER.warning("Reconnect failed: %s", reconnect_error)
                raise THZConnectionError(
                    f"Connection failed after {max_retries + 1} attempts: {e}"
                ) from e

            except (THZNotSupportedError, THZWriteRejectedError):
                raise  # legitimate device response — no reconnect, no retry

            except THZProtocolError as e:
                _LOGGER.debug(
                    "Protocol error in send_request (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries + 1,
                    e,
                )
                if attempt < max_retries and self._may_retry(get_or_set):
                    try:
                        self._reconnect()
                        continue
                    except OSError as reconnect_error:
                        _LOGGER.warning("Reconnect failed: %s", reconnect_error)
                raise

            except Exception as e:
                _LOGGER.exception("Unexpected error in send_request: %s", e)
                raise THZProtocolError(f"Device communication failed: {e}") from e

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

    # Helper methods
    def _read_exact(self, size: int, timeout: float) -> bytes:
        """Read exactly n bytes, regardless of USB or TCP."""
        end_time = time.time() + timeout
        buf = bytearray()
        while len(buf) < size and time.time() < end_time:
            chunk = self._read_available()
            if chunk:
                buf.extend(chunk)
            else:
                time.sleep(0.005)
        return bytes(buf)

    async def async_execute(
        self,
        hass: HomeAssistant,
        fn: Callable[..., Any],
        *args: Any,
        timeout: float = 8.0,  # noqa: ASYNC109 - enforced on the executor job
    ) -> Any:
        """Execute a blocking device function with the lock held and a hard timeout.

        Acquires the device lock (with a 20-second cap so coordinators cannot
        queue up indefinitely when many blocks fire simultaneously), then runs
        ``fn(*args)`` in a thread-pool executor with a ``timeout``-second
        deadline.

        A running thread cannot be cancelled, so on timeout the call is marked
        abandoned (the thread then refuses to reconnect or send anything, see
        _raise_if_abandoned) and the connection is closed to interrupt its
        blocking I/O. The lock is only released once the thread has actually
        finished (or after a short grace period), so it never talks to the
        device concurrently with the next caller.

        On *any* failure ``_force_close`` is called so ``self.ser`` is
        ``None`` on exit, triggering a fresh ``_reconnect()`` on the next call.
        """
        # Prevent unbounded queuing: if the lock cannot be acquired within
        # 20 seconds the coordinator gives up and retries at its next interval.
        _LOCK_WAIT_TIMEOUT = 20.0
        try:
            await asyncio.wait_for(self.lock.acquire(), timeout=_LOCK_WAIT_TIMEOUT)
        except TimeoutError:
            raise THZConnectionError(
                f"Device busy: could not acquire lock within {_LOCK_WAIT_TIMEOUT:.0f}s"
            ) from None

        abandoned = threading.Event()
        future = hass.async_add_executor_job(
            self._run_abandonable, abandoned, fn, *args
        )
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError:
            _LOGGER.warning(
                "Device call timed out after %.1fs; closing connection", timeout
            )
            raise THZConnectionError(
                f"Device communication timed out after {timeout}s"
            ) from None
        except THZNotSupportedError:
            raise  # device said "not supported" — connection is fine, keep it
        except BaseException:
            self._force_close()
            raise
        finally:
            if not future.done():
                # Timed out or cancelled while the thread still runs.
                abandoned.set()
                self._force_close()
                await asyncio.wait({future}, timeout=self._abandon_grace)
                if not future.done():
                    _LOGGER.warning(
                        "Device worker did not finish within %.1fs after "
                        "being abandoned",
                        self._abandon_grace,
                    )
                else:
                    # Consume the thread's (expected) error so it is not
                    # reported as "exception was never retrieved".
                    future.exception()
            self.lock.release()

    @property
    def _abandon_grace(self) -> float:
        """Upper bound for an abandoned worker to notice the closed port."""
        return 2 * self.read_timeout + 1.0

    def close(self) -> None:
        """Close the connection; safe to call repeatedly and never raises."""
        self._force_close()

    def read_write_register(
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
        raw_response = self.send_request(telegram, get_or_set)
        if get_or_set == "get":
            decoded = self.decode_response(raw_response)
            if decoded is None:
                raise THZProtocolError("Failed to decode device response")
            return decoded

        return b""

    def read_firmware_version(self) -> str:
        """Reads the firmware version from the THZ device.

        - Address (Register): 0xFD
        - Offset: 2
        - Length: 2 bytes
        - Interpreted as: unsigned big-endian integer
        """
        try:
            value_raw = self.read_value(b"\xfd", "get", 2, 2)
            if value_raw is None:
                _LOGGER.error("Could not read firmware version: no response")
                return ""
            firmware_version = int.from_bytes(value_raw, byteorder="big", signed=False)
            _LOGGER.debug("Firmware version read: %s", firmware_version)
            return str(firmware_version)
        except DEVICE_ERRORS as e:
            _LOGGER.warning("Could not read firmware version: %s", e)
            return ""

    def _probe_cooling_support(self) -> bool:
        """Probe whether the device supports cooling hardware.

        Reads the cooling HC total energy register (command 0A0648).
        Devices without cooling hardware (e.g. LWZ404) return an all-zero
        payload for this register, which is the detection pattern described
        in the issue report.

        Returns:
            True if cooling is supported, False if the payload is all zeros.
        """
        try:
            result = self.read_block(bytes.fromhex("0A0648"), "get")
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

    def read_value(
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
        response = self.read_write_register(addr_bytes, get_or_set)
        return response[offset : offset + length]

    def write_value(self, addr_bytes: bytes, value: bytes) -> None:
        r"""Write a value to the THZ device.

        Args:
            addr_bytes: Register address bytes (e.g. b'\xfb').
            value: Bytes to write to the device.
        """
        self.read_write_register(addr_bytes, "set", value)
        _LOGGER.debug("Value %s written to address %s", value, addr_bytes.hex())

    def write_block_value(
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
        response = self.read_write_register(block_addr, "get")
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
        self.read_write_register(block_addr, "set", bytes(payload))
        _LOGGER.debug(
            "Block value written: block=%s offset=%d length=%d value=%s",
            block_addr.hex(),
            offset,
            length,
            value.hex(),
        )

    def read_block(self, addr_bytes: bytes, get_or_set: str) -> bytes:
        r"""Read a block from the THZ device.

        Args:
            addr_bytes: bytes (e.g. b'\xfb')
            get_or_set: "get" or "set"

        Returns:
            block read from the device
        """
        return self.read_write_register(addr_bytes, get_or_set)

    @property
    def firmware_version(self) -> str:
        """Return the firmware version of the device."""
        if self._firmware_version is None:
            raise THZNotInitializedError(
                "Device not initialized or firmware version unknown"
            )
        return self._firmware_version

    @property
    def available_reading_blocks(self) -> list[str]:
        """Return the available reading blocks of the device."""
        if self.register_map_manager:
            return list(self.register_map_manager.get_all_registers().keys())
        return []

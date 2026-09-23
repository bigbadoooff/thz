"""THZ device communication module.

This module provides the THZDevice class which handles serial and TCP
communication with Stiebel Eltron LWZ / Tecalor THZ heat pumps.
"""

import asyncio
from collections.abc import Callable
import logging
import socket
import threading
import time
from typing import Any

import serial

from homeassistant.core import HomeAssistant

from . import const
from .register_maps.register_map_manager import (
    RegisterMapManager,
    RegisterMapManagerWrite,
)

_LOGGER = logging.getLogger(__name__)


class THZRegisterNotSupportedError(RuntimeError):
    """Raised when the device reports a register is not supported (0x01 0x04 response).

    This is a permanent condition for a given register on a given device firmware,
    not a transient communication error. Callers should treat this as an unavailable
    value rather than retrying or failing setup.
    """


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
        """Initialize basic configuration – no communication yet."""
        self.connection = connection
        self.port = port
        self.host = host
        self.tcp_port = tcp_port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self._firmware_override = firmware_override
        self._initialized = False

        # Placeholders
        self.ser: serial.Serial | socket.socket | None = None
        self._firmware_version: str | None = None
        self.has_cooling: bool = True
        self.register_map_manager: RegisterMapManager | None = None
        self.write_register_map_manager: RegisterMapManagerWrite | None = None

        # Serialises device access across coroutines (see async_execute).
        self.lock = asyncio.Lock()
        self._last_access = 0
        self._min_interval = 0.1  # minimum time between reads in seconds
        # Per-thread abandon signal of the async_execute call being served.
        self._call_state = threading.local()

        # ---------------------------------------------------------------------

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
                raise ConnectionError("Firmware version could not be read")
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
            raise RuntimeError("Device not initialized or firmware version unknown")
        return self._firmware_version

    def _connect_serial(self):
        """Open the USB/Serial connection."""
        _LOGGER.debug(
            "Opening serial connection: %s @ %s baud", self.port, self.baudrate
        )
        self.ser = serial.Serial(
            self.port,
            baudrate=self.baudrate,
            timeout=self.read_timeout,
        )

    def _connect_tcp(self):
        """Connect to ser2net (TCP/IP) with keepalive enabled.

        Enables TCP keepalive to prevent connection timeouts when using ser2net.
        This is critical for long-running connections that may be idle between polls.
        """
        _LOGGER.debug("Opening TCP connection: %s:%s", self.host, self.tcp_port)
        self.ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ser.settimeout(self.read_timeout)

        # Enable TCP keepalive to prevent connection timeout
        # This is essential for ser2net connections that may timeout after inactivity
        self.ser.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        # Configure keepalive parameters (Linux-specific but safe on other platforms)
        # These settings ensure the connection stays alive even during long idle periods
        try:
            # Start sending keepalive probes after 60 seconds of inactivity
            if hasattr(socket, 'TCP_KEEPIDLE'):
                self.ser.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            # Send keepalive probes every 10 seconds
            if hasattr(socket, 'TCP_KEEPINTVL'):
                self.ser.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            # Close connection after 6 failed probes (60 seconds total)
            if hasattr(socket, 'TCP_KEEPCNT'):
                self.ser.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
            _LOGGER.debug("TCP keepalive enabled with idle=60s, interval=10s, count=6")
        except (OSError, AttributeError) as e:
            # Keepalive parameters may not be available on all platforms
            _LOGGER.warning("Could not set TCP keepalive parameters: %s", e)

        self.ser.connect((self.host, self.tcp_port))
        _LOGGER.info("TCP connection established with keepalive enabled")

    def _is_connection_alive(self) -> bool:
        """Check if the connection is still alive.

        Uses multiple methods to verify connection health:
        1. Check if socket/serial file descriptor is valid
        2. For TCP: Try MSG_PEEK to detect closed connections
        3. For serial: Check is_open status

        Returns:
            bool: True if connection is alive, False otherwise
        """
        if self.ser is None:
            return False

        if self.connection == "ip":
            try:
                # Check if socket is still valid
                if self.ser.fileno() == -1:
                    return False

                # Save original timeout to restore after the check.
                original_timeout = self.ser.gettimeout()  # type: ignore[union-attr]

                # Try a quick peek without blocking to detect closed connections
                # This is a best-effort check; MSG_PEEK may not work on all platforms
                self.ser.setblocking(False)  # type: ignore[union-attr]
                try:
                    # recv with MSG_PEEK doesn't remove data from buffer. A
                    # non-blocking socket without data raises BlockingIOError;
                    # an empty result means the peer closed the connection.
                    if self.ser.recv(1, socket.MSG_PEEK) == b"":  # type: ignore[union-attr]
                        return False
                except BlockingIOError:
                    # No data available but connection is alive
                    pass
                except (OSError, socket.error):
                    # Connection is broken
                    return False
                finally:
                    # Always restore the original timeout
                    try:
                        self.ser.settimeout(original_timeout)  # type: ignore[union-attr]
                    except (OSError, socket.error):
                        # Socket may be in bad state, ignore
                        pass

                return True
            except (OSError, socket.error, AttributeError):
                return False

        # Serial connection
        try:
            return self.ser.is_open  # type: ignore[union-attr]
        except AttributeError:
            return False

    def _raise_if_abandoned(self) -> None:
        """Stop a worker thread whose async_execute call already gave up.

        Once async_execute has timed out it may hand the device to the next
        caller, so the old thread must neither reconnect nor send anything.
        """
        abandoned: threading.Event | None = getattr(
            self._call_state, "abandoned", None
        )
        if abandoned is not None and abandoned.is_set():
            raise ConnectionError("Device call abandoned after its timeout")

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
                try:
                    self.ser.close()
                except OSError:
                    pass

            if self.connection == "usb":
                self._connect_serial()
            elif self.connection == "ip":
                self._connect_tcp()

            _LOGGER.info("Reconnection successful")
        except OSError as e:
            _LOGGER.exception("Reconnection failed: %s", e)
            raise

    def _do_handshake_1(self, timeout: float) -> None:
        """Perform handshake step 1: send 0x02 and expect 0x10.

        Args:
            timeout: Read timeout in seconds.

        Raises:
            RuntimeError: If the device response is not 0x10.
        """
        self._write_bytes(const.STARTOFTEXT)
        response = self._read_exact(1, timeout)
        if response != const.DATALINKESCAPE:
            resp_hex = response.hex() if response else "no data"
            error_msg = f"Handshake 1 failed, received: {resp_hex}"
            _LOGGER.error(error_msg)
            raise RuntimeError(error_msg)

    def _do_handshake_2(self, timeout: float) -> None:
        """Perform handshake step 2: read and validate 0x10 0x02.

        Handles the firmware quirk where the device may send 0x10 and 0x02
        separately (with a short delay for firmware 2.x).

        Args:
            timeout: Read timeout in seconds.

        Raises:
            RuntimeError: If the combined two-byte response is not 0x10 0x02.
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
                _LOGGER.error(error_msg)
                raise RuntimeError(error_msg)
        elif response == const.STARTOFTEXT:
            # Sometimes device sends just 0x02 (as per Perl code line 1525)
            _LOGGER.debug("Received only 0x02 as response")
            response = const.DATALINKESCAPE + const.STARTOFTEXT

        if response != const.DATALINKESCAPE + const.STARTOFTEXT:
            resp_hex = response.hex() if response else "no data"
            error_msg = f"Handshake 2 failed, received: {resp_hex}"
            _LOGGER.error(error_msg)
            raise RuntimeError(error_msg)

    def _receive_data_telegram(self, timeout: float) -> bytes:
        """Send confirmation and read data telegram until 0x10 0x03 terminator.

        Args:
            timeout: Read timeout in seconds.

        Returns:
            The raw data telegram bytes (including the 0x10 0x03 terminator).

        Raises:
            RuntimeError: If no valid data telegram is received within timeout.
        """
        self._write_bytes(const.DATALINKESCAPE)

        data = bytearray()
        start_time = time.time()
        while time.time() - start_time < timeout:
            chunk = self._read_available()
            if chunk:
                data.extend(chunk)
                if self._frame_complete(data):
                    break
            else:
                # Avoid busy-waiting when no data is currently available
                time.sleep(0.01)

        if not self._frame_complete(data):
            error_msg = (
                "No valid response received after data request - "
                "timeout or incomplete data"
            )
            _LOGGER.error(error_msg)
            raise RuntimeError(error_msg)

        return bytes(data)

    @staticmethod
    def _frame_complete(data: bytes | bytearray) -> bool:
        """Return True if ``data`` ends with an unescaped 0x10 0x03 terminator.

        A data byte 0x10 is sent escaped as 0x10 0x10, so ``... 10 10 03``
        is an escaped 0x10 followed by a data byte 0x03, not the end of the
        frame. The terminator's 0x10 is real only if the run of 0x10 bytes
        before the final 0x03 has odd length.
        """
        if len(data) < 8 or data[-1] != const.ENDOFTEXT[0]:
            return False
        run = 0
        for byte in reversed(data[:-1]):
            if byte != const.DATALINKESCAPE[0]:
                break
            run += 1
        return run % 2 == 1

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
            ConnectionError: If the underlying connection is broken.
            RuntimeError: If a protocol/handshake error occurs.
        """
        timeout = self.read_timeout
        self._raise_if_abandoned()

        if self._initialized and not self._is_connection_alive():
            _LOGGER.warning(
                "Connection not alive, attempting reconnect (attempt %d/%d)",
                attempt + 1, max_retries + 1,
            )
            self._reconnect()

        # Flush stale bytes before handshake — boot-up sequences from the
        # heatpump or leftover bytes from a previous failed attempt would
        # otherwise be read as the 0x10 response to our 0x02 STX byte.
        self._reset_input_buffer()

        self._do_handshake_1(timeout)

        self._reset_input_buffer()
        self._write_bytes(telegram)

        self._do_handshake_2(timeout)

        data = self._receive_data_telegram(timeout) if get_or_set == "get" else b""

        self._write_bytes(const.STARTOFTEXT)
        return data

    def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        """Send request via USB or TCP, receive response.

        Automatically reconnects if connection is lost.

        Raises:
            ConnectionError: If connection fails and reconnection is unsuccessful.
            RuntimeError: If device communication fails (handshake, timeout,
                invalid response).
        """
        max_retries = 1  # Allow one retry on connection error
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return self._exchange_once(telegram, get_or_set, attempt, max_retries)

            except ConnectionError as e:
                last_error = e
                _LOGGER.exception(
                    "Connection error in send_request (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, e,
                )
                if attempt < max_retries:
                    try:
                        self._reconnect()
                        continue
                    except OSError as reconnect_error:
                        _LOGGER.exception("Reconnect failed: %s", reconnect_error)
                raise ConnectionError(
                    f"Connection failed after {max_retries + 1} attempts: {e}"
                ) from e

            except THZRegisterNotSupportedError:
                raise  # legitimate device response — no reconnect

            except RuntimeError as e:
                last_error = e
                _LOGGER.exception("Protocol error in send_request: %s", e)
                if attempt < max_retries:
                    try:
                        self._reconnect()
                        continue
                    except OSError as reconnect_error:
                        _LOGGER.exception("Reconnect failed: %s", reconnect_error)
                raise

            except Exception as e:  # noqa: BLE001
                last_error = e
                _LOGGER.exception("Unexpected error in send_request: %s", e)
                raise RuntimeError(f"Device communication failed: {e}") from e

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise RuntimeError("send_request failed without specific error")

    # Helper methods
    def _write_bytes(self, data: bytes):
        """Send bytes depending on connection type.

        Raises:
            ConnectionError: If the connection is closed or broken
        """
        try:
            # self.connection is the authoritative discriminator (set once in
            # __init__ and never mutated); mypy can't narrow self.ser's union
            # type from it, so these accesses need an explicit ignore.
            # self.ser turning None mid-call is a real, accepted race handled
            # by the AttributeError clause below.
            if self.connection == "ip":
                self.ser.sendall(data)  # type: ignore[union-attr]
            else:
                self.ser.write(data)  # type: ignore[union-attr]
                self.ser.flush()  # type: ignore[union-attr]
        except (OSError, socket.error, BrokenPipeError) as e:
            # Connection reset, broken pipe, or other socket/serial errors
            _LOGGER.exception("Connection error during write: %s", e)
            raise ConnectionError(f"Failed to write to connection: {e}") from e
        except (ValueError, AttributeError) as e:
            # Raised by select.select() when the fd is closed mid-write (pyserial sets
            # fd=None on close, so fileno() returns None, which is not an int).
            # Also catches AttributeError if self.ser is set to None by _force_close()
            # between the check above and the actual send/write call.
            raise ConnectionError(f"Connection closed during write: {e}") from e

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

    def _read_available(self) -> bytes:
        """Read available bytes.

        Raises:
            ConnectionError: If the connection is closed or broken
        """
        # self.connection is the authoritative discriminator (set once in
        # __init__ and never mutated); mypy can't narrow self.ser's union
        # type from it, so these accesses need an explicit ignore.
        # self.ser turning None mid-call is a real, accepted race handled by
        # the AttributeError clauses below.
        if self.ser is None:
            return b""

        if self.connection == "ip":
            try:
                # Save original timeout to restore after reading
                original_timeout = self.ser.gettimeout()  # type: ignore[union-attr]
                self.ser.setblocking(False)  # type: ignore[union-attr]
                data = self.ser.recv(1024)  # type: ignore[union-attr]
            except BlockingIOError:
                return b""
            except (OSError, socket.error) as e:
                # Connection reset, broken pipe, or other socket errors
                _LOGGER.exception("TCP socket error during read: %s", e)
                raise ConnectionError(f"TCP connection error: {e}") from e
            except (ValueError, AttributeError) as e:
                # select.select() raises ValueError when the socket fd is closed
                # (fileno() returns None after close); AttributeError if self.ser
                # becomes None between the check above and the recv call.
                raise ConnectionError(f"Connection closed during read: {e}") from e
            finally:
                # Always restore the original timeout. UnboundLocalError covers
                # the case where gettimeout() itself raised above, so
                # original_timeout was never assigned.
                try:
                    self.ser.settimeout(original_timeout)  # type: ignore[union-attr]
                except (OSError, socket.error, AttributeError, UnboundLocalError):
                    # Socket may be in bad state or already None, ignore
                    pass
            if not data:
                # A non-blocking recv() only returns b"" at end of stream:
                # the peer (e.g. a restarted ser2net) closed the connection.
                raise ConnectionError("TCP socket connection closed by peer")
            return bytes(data)

        # Serial connection
        try:
            waiting = getattr(self.ser, "in_waiting", 0)
            if waiting > 0:
                return self.ser.read(waiting)  # type: ignore[union-attr]
            return b""
        except (OSError, serial.SerialException) as e:
            raise ConnectionError(f"Serial read error: {e}") from e
        except (ValueError, AttributeError) as e:
            # pyserial's select.select() raises ValueError when the port fd
            # is None (set by close()); AttributeError if self.ser is None.
            raise ConnectionError(
                f"Connection closed during serial read: {e}"
            ) from e

    def _reset_input_buffer(self):
        """Delete any existing input buffer.

        TCP sockets do not have an input buffer to reset, so this is only
        relevant for serial connections.
        """
        if self.ser is not None and hasattr(self.ser, "reset_input_buffer"):
            try:
                self.ser.reset_input_buffer()
            except AttributeError:
                pass

    async def async_execute(
        self,
        hass: HomeAssistant,
        fn: Callable[..., Any],
        *args: Any,
        timeout: float = 8.0,
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
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"Device busy: could not acquire lock within {_LOCK_WAIT_TIMEOUT:.0f}s"
            ) from None

        abandoned = threading.Event()
        future = hass.async_add_executor_job(
            self._run_abandonable, abandoned, fn, *args
        )
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Device call timed out after %.1fs; closing connection", timeout
            )
            raise ConnectionError(
                f"Device communication timed out after {timeout}s"
            ) from None
        except THZRegisterNotSupportedError:
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
                        "being abandoned", self._abandon_grace,
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

    def _force_close(self) -> None:
        """Close without raising; sets ser=None so the next call reconnects."""
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:  # noqa: BLE001
                pass
            self.ser = None

    def thz_checksum(self, data: bytes) -> bytes:
        """Calculate THZ checksum for given data."""
        checksum = sum(b for i, b in enumerate(data) if i != 2)
        checksum = checksum % 256
        return bytes([checksum])

    def unescape(self, data: bytes) -> bytes:
        """Remove escape sequences from data."""
        # 0x10 0x10 -> 0x10
        data = data.replace(
            const.DATALINKESCAPE + const.DATALINKESCAPE, const.DATALINKESCAPE
        )
        # 0x2B 0x18 -> 0x2B
        return data.replace(b"\x2b\x18", b"\x2b")

    def escape(self, data: bytes) -> bytes:
        """Add escape sequences to data before sending.

        According to the protocol (from FHEM THZ module):
        - Each 0x10 byte must be escaped as 0x10 0x10
        - Each 0x2B byte must be escaped as 0x2B 0x18

        The order of escaping (0x10 first, then 0x2B) matches the FHEM implementation
        and is safe because these escape sequences don't interfere with each other.

        Args:
            data: Raw bytes to escape

        Returns:
            Escaped bytes ready to send
        """
        # 0x10 -> 0x10 0x10 (matches Perl line 1764)
        escape = const.DATALINKESCAPE
        data = data.replace(escape, escape + escape)
        # 0x2B -> 0x2B 0x18 (matches Perl line 1768)
        return data.replace(b"\x2b", b"\x2b\x18")

    def decode_response(self, data: bytes) -> bytes | None:
        """Decode the response from the THZ device.

        Checks header, CRC, and performs unescaping.
        """
        try:
            if len(data) < 6:
                _LOGGER.error("Response too short: %s", data.hex())
                return None

            data = self.unescape(data)

            # Header is the first 2 bytes
            header = data[0:2]
            if header in (b"\x01\x80", b"\x01\x00"):
                # Normal response b'\x01\x80' for "set" commands, b'\x01\x00' for "get"
                # CRC is byte 2 (index 2)
                crc = data[2]
                # Payload = between byte 3 and last 2 bytes (ETX)
                payload = data[3:-2]
                # Check CRC
                # For CRC calculation: everything except CRC and ETX (last 2 bytes)
                # Assemble hex string for checking
                check_data = data[:2] + b"\x00" + payload
                checksum_bytes = self.thz_checksum(check_data)
                calc_crc = checksum_bytes[0]
                if calc_crc != crc:
                    _LOGGER.error(
                        "CRC error in response. Expected %02X, calculated %02X",
                        crc,
                        calc_crc,
                    )
                    return None

                return checksum_bytes + payload

            if header == b"\x01\x01":
                _LOGGER.error("Timing issue from device")
                return None
            if header == b"\x01\x02":
                _LOGGER.error("CRC error in request")
                return None
            if header == b"\x01\x03":
                _LOGGER.error("Unknown command")
                return None
            if header == b"\x01\x04":
                raise THZRegisterNotSupportedError(
                    "Register not supported by device firmware"
                )
            _LOGGER.error("Unknown response: %s", data.hex())
            return None
        except THZRegisterNotSupportedError:
            raise  # propagate — not a decode error, not a connection failure
        except Exception as e:  # noqa: BLE001
            _LOGGER.exception("Error decoding response: %s", e)
            return None

    def read_write_register(
        self,
        addr_bytes: bytes,
        get_or_set: str = "get",
        payload_to_deliver: bytes = b"",
    ) -> bytes:
        """Reads or writes a register from/to the THZ device.

        Raises:
            ConnectionError: If connection fails
            RuntimeError: If device communication fails
            THZRegisterNotSupportedError: If the device reports the register is
                not supported
        """
        header = b"\x01\x00" if get_or_set == "get" else b"\x01\x80"
        # Standard Header für "get" und "set"
        footer = const.DATALINKESCAPE + const.ENDOFTEXT  # Standard Footer

        checksum = self.thz_checksum(header + b"\x00" + addr_bytes + payload_to_deliver)
        # b'\x00' = Platzhalter für die Checksumme
        telegram = self.construct_telegram(
            addr_bytes + payload_to_deliver, header, footer, checksum
        )
        raw_response = self.send_request(telegram, get_or_set)
        if get_or_set == "get":
            decoded = self.decode_response(raw_response)
            if decoded is None:
                raise RuntimeError("Failed to decode device response")
            return decoded

        return b""

    def construct_telegram(
        self, addr_bytes: bytes, header: bytes, footer: bytes, checksum: bytes
    ) -> bytes:
        r"""Constructs a telegram for the THZ device based on the given address bytes.

        Args:
            addr_bytes: Address bytes including command and optional payload
                (e.g. b'\xfb' or b'\x0a\x01\x1f')
            header: Header bytes (e.g. b'\x01\x00' or b'\x01\x80')
            footer: Footer bytes (e.g. b'\x10\x03')
            checksum: Checksum bytes (e.g. b'\x5a')

        Returns:
            telegram ready to send.
        """
        # Escape the checksum + command (+ payload) bytes according to the protocol
        # (0x10 -> 0x10 0x10, 0x2B -> 0x2B 0x18)
        # This matches the FHEM THZ module's THZ_encodecommand() function behavior
        escaped_data = self.escape(checksum + addr_bytes)
        return header + escaped_data + footer

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
                _LOGGER.error(
                    "Firmware-Version konnte nicht gelesen werden: Keine Antwort"
                )
                return ""
            firmware_version = int.from_bytes(value_raw, byteorder="big", signed=False)
            _LOGGER.debug("Firmware-Version gelesen: %s", firmware_version)
            return str(firmware_version)
        except (OSError, RuntimeError) as e:
            _LOGGER.exception("Firmware-Version konnte nicht gelesen werden: %s", e)
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
                    "Cooling probe: register 0A0648 returned zero payload – no cooling"
                )
                return False
            return True
        except (RuntimeError, ConnectionError, OSError) as e:
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
            RuntimeError: If the device read or write fails, or the read-back
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
            raise RuntimeError(
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
            block_addr.hex(), offset, length, value.hex(),
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
            raise RuntimeError("Device not initialized or firmware version unknown")
        return self._firmware_version

    @property
    def available_reading_blocks(self) -> list[str]:
        """Return the available reading blocks of the device."""
        if self.register_map_manager:
            return list(self.register_map_manager.get_all_registers().keys())
        return []

import asyncio  # noqa: D100
import logging
import socket
import time

import serial

from homeassistant.core import HomeAssistant

from . import const
from .register_maps.register_map_manager import (
    RegisterMapManager,
    RegisterMapManagerWrite,
)

_LOGGER = logging.getLogger(__name__)


class THZDevice:
    """Repräsentiert die Verbindung zur THZ-Wärmepumpe."""

    def __init__(
        self,
        connection: str = "usb",
        port: str | None = None,
        host: str | None = None,
        tcp_port: int | None = None,
        baudrate: int = const.DEFAULT_BAUDRATE,
        read_timeout: float = const.TIMEOUT,
    ) -> None:
        """Nur Grundkonfiguration – noch keine Kommunikation."""
        self.connection = connection
        self.port = port
        self.host = host
        self.tcp_port = tcp_port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self._initialzed = False

        # Platzhalter
        self.ser: serial.Serial | socket.socket | None = None
        self._firmware_version: str | None = None
        self.register_map_manager: RegisterMapManager | None = None
        self.write_register_map_manager: RegisterMapManagerWrite | None = None
        self._cache = {}
        self._cache_duration = 60

        # Thread-Lock für parallele Zugriffe
        self.lock = asyncio.Lock()
        self._last_access = 0
        self._min_interval = 0.1  # minimale Zeit zwischen zwei Reads in Sekunden

        # ---------------------------------------------------------------------

    async def async_initialize(self, hass: HomeAssistant) -> None:
        """Öffnet Verbindung und initialisiert Firmware-abhängige Datenstrukturen."""
        _LOGGER.debug("Initialisiere THZ-Device (%s)", self.connection)

        # Verbindung öffnen
        if self.connection == "usb":
            self._connect_serial()
        elif self.connection == "ip":
            self._connect_tcp()
        else:
            raise ValueError(f"Unbekannter Verbindungstyp: {self.connection}")

        # Firmware lesen (läuft synchron im Executor)
        self._firmware_version = await hass.async_add_executor_job(
            self.read_firmware_version
        )
        _LOGGER.info("Firmware-Version erkannt: %s", self._firmware_version)

        # Firmware-spezifische Register-Maps laden
        if self._firmware_version is None:
            raise RuntimeError("Firmware version could not be determined")
        self.register_map_manager = RegisterMapManager(self._firmware_version)
        self.write_register_map_manager = RegisterMapManagerWrite(
            self._firmware_version
        )

        self._cache = {}  # { block_name: (timestamp, payload) }
        self._cache_duration = 60  # seconds

        self._initialzed = True

    def _connect_serial(self):
        """Öffnet die USB/Serielle Verbindung."""
        _LOGGER.debug(
            "Öffne serielle Verbindung: %s @ %s baud", self.port, self.baudrate
        )
        self.ser = serial.Serial(
            self.port,
            baudrate=self.baudrate,
            timeout=self.read_timeout,
        )

    def _connect_tcp(self):
        """Verbindet sich mit ser.net (TCP/IP)."""
        _LOGGER.debug("Öffne TCP-Verbindung: %s:%s", self.host, self.tcp_port)
        self.ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ser.settimeout(self.read_timeout)
        self.ser.connect((self.host, self.tcp_port))

    def read_block_cached(self, block: bytes, cache_duration: float = 60) -> bytes:
        """Read a block of data with caching support.

        Args:
            block (bytes): The block identifier to read.
            cache_duration (float): The duration in seconds to cache the data.
            Defaults to 60 seconds.

        Returns:
            bytes: The block data. Returns cached data if available and not expired,
            otherwise fetches fresh data.
        """
        now = time.time()
        if block in self._cache:
            ts, data = self._cache[block]
            if now - ts < cache_duration:
                return data

        data = self.read_block(block, "get")
        self._cache[block] = (now, data)
        return data

    def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        """Sende Anfrage über USB oder TCP, empfange Antwort."""
        timeout = self.read_timeout
        data = bytearray()

        try:
            # 1. Greeting senden (0x02)
            self._write_bytes(const.STARTOFTEXT)
            # _LOGGER.info("Greeting gesendet (0x02)")

            # 2. 0x10 Antwort erwarten
            response = self._read_exact(1, timeout)
            if response != const.DATALINKESCAPE:
                _LOGGER.error(f"Handshake 1 fehlgeschlagen, erhalten: {response.hex()}")
                return b""

            # 3. Telegram senden
            self._reset_input_buffer()
            self._write_bytes(telegram)
            # _LOGGER.info(f"Request gesendet: {telegram.hex()}")

            # 4. 0x10 0x02 Antwort erwarten
            response = self._read_exact(2, timeout)
            if response != const.DATALINKESCAPE + const.STARTOFTEXT:
                _LOGGER.error(f"Handshake 2 fehlgeschlagen, erhalten: {response.hex()}")
                return b""

            if get_or_set == "get":
                # 5. Bestätigung senden (0x10)
                self._write_bytes(const.DATALINKESCAPE)

                # 6. Daten-Telegramm empfangen bis 0x10 0x03
                start_time = time.time()
                while time.time() - start_time < timeout:
                    chunk = self._read_available()
                    if chunk:
                        data.extend(chunk)
                        if (
                            len(data) >= 8
                            and data[-2:] == const.DATALINKESCAPE + const.ENDOFTEXT
                        ):
                            break

                # _LOGGER.info(f"Empfangene Rohdaten: {data.hex()}")

                if not (
                    len(data) >= 8 and data[-2:] == const.DATALINKESCAPE + const.ENDOFTEXT
                ):
                    _LOGGER.error("Keine gültige Antwort nach Datenanfrage erhalten")
                    return b""

            # 7. Ende der Kommunikation
            self._write_bytes(const.STARTOFTEXT)
            return bytes(data)
        except Exception as e:
            _LOGGER.error(f"Fehler bei send_request: {e}")
            return b""

    # Hilfsmethoden ergänzen
    def _write_bytes(self, data: bytes):
        """Sendet Bytes je nach Verbindungstyp."""
        if isinstance(self.ser, socket.socket):  # TCP Socket
            self.ser.send(data)
        elif isinstance(self.ser, serial.Serial):  # Serial
            self.ser.write(data)
            self.ser.flush()

    def _read_exact(self, size: int, timeout: float) -> bytes:
        """Liest exakt n Bytes, egal ob USB oder TCP."""
        end_time = time.time() + timeout
        buf = bytearray()
        while len(buf) < size and time.time() < end_time:
            chunk = self._read_available()
            if chunk:
                buf.extend(chunk)
            #else: 
                #time.sleep(0.01) time.sleep(0.01) causes blocking in async context, let's see if it works without
        return bytes(buf)

    def _read_available(self) -> bytes:
        """Liest verfügbare Bytes."""
        if isinstance(self.ser, socket.socket) and hasattr(
            self.ser, "recv"
        ):  # TCP Socket
            try:
                self.ser.setblocking(False)
                return self.ser.recv(1024)
            except BlockingIOError:
                return b""
        elif isinstance(self.ser, serial.Serial):  # Serial
            waiting = getattr(self.ser, "in_waiting", 0)
            if waiting > 0:
                return self.ser.read(waiting)
            return b""
        else:
            return b""

    def _reset_input_buffer(self):
        """Delete any existing input buffer.

        TCP sockets do not have an input buffer to reset, so this is only
        relevant for serial connections.
        """
        if self.ser is not None and isinstance(self.ser, serial.Serial):
            if hasattr(self.ser, "reset_input_buffer"):
                self.ser.reset_input_buffer()

    def close(self):
        """Close the connection."""
        if self.ser is not None:
            self.ser.close()

    def thz_checksum(self, data: bytes) -> bytes:
        """Calculate THZ checksum for given data."""
        checksum = sum(b for i, b in enumerate(data) if i != 2)
        checksum = checksum % 256
        return bytes([checksum])

    # def send_request(self, telegram: bytes) -> bytes:
    #     # 1. Send greeting
    #     self.ser.write(const.STARTOFTEXT)
    #     self.ser.flush()
    #     #_LOGGER.debug("Greeting gesendet: 02")

    #     # 2. Wait for 0x10 response
    #     response = self.ser.read(1)
    #     #_LOGGER.debug(f"Greeting Antwort: {response.hex()}")
    #     if response != const.DATALINKESCAPE:
    #         raise ValueError("Handshake Schritt 1 fehlgeschlagen: keine 0x10 Antwort")

    #     # 3. Send request telegram
    #     # telegram = self.build_request(telegram)
    #     self.ser.reset_input_buffer()
    #     self.ser.write(telegram)
    #     self.ser.flush()
    #     _LOGGER.debug("Request gesendet: %s", telegram.hex())

    #     # 4. Wait for 0x10 0x02 response
    #     response = self.ser.read(2)
    #     #_LOGGER.debug(f"Antwort nach Request: {response.hex()}")
    #     if response != const.DATALINKESCAPE + const.STARTOFTEXT:
    #         raise ValueError("Handshake Schritt 2 fehlgeschlagen: keine 0x10 0x02 Antwort")

    #     # 5. Send confirmation 0x10
    #     self.ser.write(const.DATALINKESCAPE)
    #     self.ser.flush()
    #     #_LOGGER.debug("Bestätigung gesendet: 10")

    #     # 6. Read data telegram (ends with 0x10 0x03)
    #     data = bytearray()
    #     start_time = time.time()
    #     max_wait = self.read_timeout
    #     while time.time() - start_time < max_wait:
    #         if self.ser.in_waiting > 0:
    #             chunk = self.ser.read(self.ser.in_waiting)
    #             data.extend(chunk)
    #             # Check for footer (0x10 0x03) and minimum length
    #             if len(data) >= 8 and data[-2:] == const.DATALINKESCAPE + const.ENDOFTEXT:
    #                 break
    #         else:
    #            asyncio.sleep(0.01)
    #     _LOGGER.debug(f"Empfangene Rohdaten: {data.hex()}")

    #     if not (len(data) >= 8 and data[-2:] == const.DATALINKESCAPE + const.ENDOFTEXT):
    #         raise ValueError("Keine gültige Antwort nach Datenanfrage erhalten")

    #     # 7. End of communication
    #     self.ser.write(const.STARTOFTEXT)
    #     self.ser.flush()
    #     #_LOGGER.debug("Greeting gesendet: 02")

    #     # Unescaping is already handled in decode_response
    #     return bytes(data)

    def unescape(self, data: bytes) -> bytes:
        """Remove escape sequences from data."""
        # 0x10 0x10 -> 0x10
        data = data.replace(
            const.DATALINKESCAPE + const.DATALINKESCAPE, const.DATALINKESCAPE
        )
        # 0x2B 0x18 -> 0x2B
        return data.replace(b"\x2b\x18", b"\x2b")

    def decode_response(self, data: bytes):
        """Decode the response from the THZ device, checking header, CRC, and unescaping."""
        try:
            if len(data) < 6:
                _LOGGER.error(f"Antwort zu kurz: {data.hex()}")
                return None

            data = self.unescape(data)

            # Header sind die ersten 2 Bytes
            header = data[0:2]
            if header in (b"\x01\x80", b"\x01\x00"):
                # normale Antwort b'\x01\x80' for "set" commands, b'\x01\x00' for "get"
                # CRC ist Byte 2 (index 2)
                crc = data[2]
                # Payload = zwischen Byte 3 und vorletzte 2 Bytes (ETX)
                payload = data[3:-2]
                # Prüfe CRC
                # Für CRC berechnung: alles außer CRC und ETX (letzte 2 Bytes)
                # hexstring zum Prüfen zusammensetzen
                check_data = data[:2] + b"\x00" + payload
                # _LOGGER.debug(f"Payload: {payload.hex()},
                # Checksumme: {crc:02X}, Checkdaten: {check_data.hex()}")
                checksum_bytes = self.thz_checksum(check_data)
                calc_crc = checksum_bytes[0]
                if calc_crc != crc:
                    _LOGGER.error(
                        f"CRC Fehler in Antwort. Erwartet {crc:02X}, berechnet {calc_crc:02X}"
                    )
                    return None

                return checksum_bytes + payload

            if header == b"\x01\x01":
                _LOGGER.error("Timing Issue from device")
                return None
            if header == b"\x01\x02":
                _LOGGER.error("CRC Error in request")
                return None
            if header == b"\x01\x03":
                _LOGGER.error("Unknown Command")
                return None
            if header == b"\x01\x04":
                _LOGGER.error("Unknown Register Request")
                return None
            _LOGGER.error(f"Unknown Response: {data.hex()}")
            return None
        except Exception as e:
            _LOGGER.error(f"Fehler beim Dekodieren der Antwort: {e}")
            return None

    def read_write_register(
        self,
        addr_bytes: bytes,
        get_or_set: str = "get",
        payload_to_deliver: bytes = b"",
    ) -> bytes:
        """Reads or writes a register from/to the THZ device."""
        header = b"\x01\x00" if get_or_set == "get" else b"\x01\x80"
        # Standard Header für "get" und "set"
        footer = const.DATALINKESCAPE + const.ENDOFTEXT  # Standard Footer

        checksum = self.thz_checksum(header + b"\x00" + addr_bytes + payload_to_deliver)
        # b'\x00' = Platzhalter für die Checksumme
        # _LOGGER.debug(f"Berechnete Checksumme: {checksum.hex()} für Adresse {addr_bytes.hex()}
        # mit Payload {payload_to_deliver.hex()}")
        telegram = self.construct_telegram(
            addr_bytes + payload_to_deliver, header, footer, checksum
        )
        # _LOGGER.debug(f"Konstruiertes Telegramm: {telegram.hex()}")
        raw_response = self.send_request(telegram, get_or_set)
        # _LOGGER.debug(f"Rohantwort erhalten: {raw_response.hex()}")
        # _LOGGER.debug("Payload dekodiert: %s", payload.hex())
        if get_or_set == "get":
            decoded = self.decode_response(raw_response)
            return decoded if decoded is not None else b""

        return b""

    def construct_telegram(
        self, addr_bytes: bytes, header: bytes, footer: bytes, checksum: bytes
    ) -> bytes:
        r"""Constructs a telegram for the THZ device based on the given address bytes.

        Args:
            addr_bytes: Address bytes (e.g. b'\xfb')
            header: Header bytes (e.g. b'\x01\x00' or b'\x01\x80')
            footer: Footer bytes (e.g. b'\x10\x03')
            checksum: Checksum bytes (e.g. b'\x5a')

        Returns:
            telegram ready to send.
        """
        return header + checksum + addr_bytes + footer

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
                _LOGGER.error("Firmware-Version konnte nicht gelesen werden: Keine Antwort")
                return ""
            # _LOGGER.debug("Rohdaten Firmware-Version: %s", value_raw.hex())
            firmware_version = int.from_bytes(value_raw, byteorder="big", signed=False)
            _LOGGER.debug("Firmware-Version gelesen: %s", firmware_version)
            return str(firmware_version)
        except Exception as e:
            _LOGGER.error(f"Firmware-Version konnte nicht gelesen werden: {e}")
            return ""

    def read_value(
        self, addr_bytes: bytes, get_or_set: str, offset: int, length: int
    ) -> bytes:
        r"""Reads a value from the THZ device.

        Args:
            addr_bytes: bytes (e.g. b'\xfb')
            get_or_set: "get" or "set"

        Returns:
            byte value read from the device
        """
        response = self.read_write_register(addr_bytes, get_or_set)
        # _LOGGER.info("Antwort von Wärmepumpe: %s", response.hex())
        # _LOGGER.info("Gelesener Wert (Offset %s, Length %s): %s", offset, length, value_raw.hex())
        return response[offset : offset + length]

    def write_value(self, addr_bytes: bytes, value: bytes) -> None:
        r"""Writes a value to the THZ device.

        Args:
            addr_bytes: bytes (e.g. b'\xfb')
            value: integer value to write
        """
        self.read_write_register(addr_bytes, "set", value)
        _LOGGER.debug("Wert %s an Adresse %s geschrieben", value, addr_bytes.hex())

    def read_block(self, addr_bytes: bytes, get_or_set: str) -> bytes:
        r"""Reads a value from the THZ device.

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


# from homeassistant.helpers.update_coordinator import DataUpdateCoordinator # pyright: ignore[reportMissingImports, reportMissingModuleSource]
# class THZCoordinator(DataUpdateCoordinator):
#     def __init__(self, hass, device, refresh_interval: int):
#         super().__init__(
#             hass,
#             _LOGGER,
#             name="THZ Coordinator",
#             update_interval= time.timedelta(seconds=refresh_interval),
#         )
#         self.device = device

#     async def _async_update_data(self):
#         return await self.device.read_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    dev = THZDevice("/dev/ttyUSB0")

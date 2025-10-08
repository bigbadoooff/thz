import serial # pyright: ignore[reportMissingImports, reportMissingModuleSource]
import socket 
import time
import asyncio
import logging
from . import const
from .register_maps.register_map_manager import RegisterMapManager, RegisterMapManager_Write

_LOGGER = logging.getLogger(__name__)

class THZDevice:
    def __init__(        self,
        connection: str = "usb",
        port: str = const.SERIAL_PORT,
        host: str | None = None,
        tcp_port: int | None = None,
        baudrate: int = const.BAUDRATE,
        read_timeout: float = const.TIMEOUT,
        ):

        self._connection = connection
        self._port = port
        self._host = host
        self._tcp_port = tcp_port
        self._baudrate = baudrate
        self.read_timeout = read_timeout

        # Verbindung herstellen
        if connection == "usb":
            self._connect_serial()
        elif connection == "ip":
            self._connect_tcp()
        else:
            raise ValueError(f"Unbekannter Verbindungstyp: {connection}")

        # Firmware lesen
        self._firmware_version = None
        self._firmware_version = self.read_firmware_version()
        # RegisterMapManager anhand der Firmware laden
        self.register_map_manager = RegisterMapManager(self.firmware_version)
        self.write_register_map_manager = RegisterMapManager_Write(self.firmware_version)
        self._cache = {}  # { block_name: (timestamp, payload) }
        self._cache_duration = 60  # seconds

    def _connect_serial(self):
        """Öffnet die USB/Serielle Verbindung."""
        _LOGGER.debug(f"Öffne serielle Verbindung: {self._port} @ {self._baudrate} baud")
        self.ser = serial.Serial(
            self._port,
            baudrate=self._baudrate,
            timeout=self.read_timeout,
        )

    def _connect_tcp(self):
        """Verbindet sich mit ser.net (TCP/IP)."""
        _LOGGER.debug(f"Öffne TCP-Verbindung: {self._host}:{self._tcp_port}")
        self.ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ser.settimeout(self.read_timeout)
        self.ser.connect((self._host, self._tcp_port))

    def read_block_cached(self, block: str) -> bytes:
        now = time.time()
        if block in self._cache:
            ts, data = self._cache[block]
            if now - ts < self._cache_duration:
                return data

        data = self.read_block(block, "get")
        self._cache[block] = (now, data)
        return data

    def send_request(self, telegram: bytes) -> bytes:
        """Sende Anfrage über USB oder TCP, empfange Antwort."""
        is_socket = hasattr(self.ser, "recv")  # TCP Socket
        timeout = self.read_timeout
        data = bytearray()

        # 1. Greeting senden (0x02)
        self._write_bytes(const.STARTOFTEXT)
        _LOGGER.debug("Greeting gesendet (0x02)")

        # 2. 0x10 Antwort erwarten
        response = self._read_exact(1, timeout)
        if response != const.DATALINKESCAPE:
            raise ValueError(f"Handshake 1 fehlgeschlagen, erhalten: {response.hex()}")

        # 3. Telegram senden
        self._reset_input_buffer()
        self._write_bytes(telegram)
        _LOGGER.debug(f"Request gesendet: {telegram.hex()}")

        # 4. 0x10 0x02 Antwort erwarten
        response = self._read_exact(2, timeout)
        if response != const.DATALINKESCAPE + const.STARTOFTEXT:
            raise ValueError(f"Handshake 2 fehlgeschlagen, erhalten: {response.hex()}")

        # 5. Bestätigung senden (0x10)
        self._write_bytes(const.DATALINKESCAPE)

        # 6. Daten-Telegramm empfangen bis 0x10 0x03
        start_time = time.time()
        while time.time() - start_time < timeout:
            chunk = self._read_available()
            if chunk:
                data.extend(chunk)
                if len(data) >= 8 and data[-2:] == const.DATALINKESCAPE + const.ENDOFTEXT:
                    break
            else:
                time.sleep(0.01)

        _LOGGER.debug(f"Empfangene Rohdaten: {data.hex()}")

        if not (len(data) >= 8 and data[-2:] == const.DATALINKESCAPE + const.ENDOFTEXT):
            raise ValueError("Keine gültige Antwort nach Datenanfrage erhalten")

        # 7. Ende der Kommunikation
        self._write_bytes(const.STARTOFTEXT)
        return bytes(data)


    # Hilfsmethoden ergänzen
    def _write_bytes(self, data: bytes):
        """Sendet Bytes je nach Verbindungstyp."""
        if hasattr(self.ser, "send"):  # TCP Socket
            self.ser.send(data)
        else:  # Serial
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
            else:
                time.sleep(0.01)
        return bytes(buf)


    def _read_available(self) -> bytes:
        """Liest verfügbare Bytes."""
        if hasattr(self.ser, "recv"):  # TCP Socket
            try:
                self.ser.setblocking(False)
                return self.ser.recv(1024)
            except BlockingIOError:
                return b""
        else:
            waiting = getattr(self.ser, "in_waiting", 0)
            if waiting > 0:
                return self.ser.read(waiting)
            return b""


    def _reset_input_buffer(self):
        """Buffer löschen, falls möglich."""
        if hasattr(self.ser, "reset_input_buffer"):
            self.ser.reset_input_buffer()


    # TCP hat keinen Input Buffer, daher kein Reset nötig
    # def close(self):
    #     self.ser.close()

    # def thz_checksum(self, data: bytes) -> bytes:
    #     checksum = sum(b for i, b in enumerate(data) if i != 2)
    #     checksum = checksum % 256
    #     return bytes([checksum])

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
        # 0x10 0x10 -> 0x10
        data = data.replace(const.DATALINKESCAPE+const.DATALINKESCAPE, const.DATALINKESCAPE)
        # 0x2B 0x18 -> 0x2B
        data = data.replace(b'\x2B\x18', b'\x2B')
        return data

    def decode_response(self, data: bytes):
        if len(data) < 6:
            raise ValueError(f"Antwort zu kurz: {data.hex()}")

        data = self.unescape(data)

        # Header sind die ersten 2 Bytes
        header = data[0:2]
        if header == b'\x01\x80' or header == b'\x01\x00':  # normale Antwort b'\x01\x80' for "set" commands, b'\x01\x00' for "get"
            # CRC ist Byte 2 (index 2)
            crc = data[2]
            # Payload = zwischen Byte 3 und vorletzte 2 Bytes (ETX)
            payload = data[3:-2]
            # Prüfe CRC
            # Für CRC berechnung: alles außer CRC und ETX (letzte 2 Bytes)
            # hexstring zum Prüfen zusammensetzen
            check_data = data[:2] + b'\x00' + payload
            #_LOGGER.debug(f"Payload: {payload.hex()}, Checksumme: {crc:02X}, Checkdaten: {check_data.hex()}")
            checksum_bytes = self.thz_checksum(check_data)
            calc_crc = checksum_bytes[0]
            if calc_crc != crc:
                raise ValueError(f"CRC Fehler in Antwort. Erwartet {crc:02X}, berechnet {calc_crc:02X}")

            return checksum_bytes + payload
        elif header == b'\x01\x01':
            raise ValueError("Timing Issue vom Gerät")
        elif header == b'\x01\x02':
            raise ValueError("CRC Fehler in Anfrage")
        elif header == b'\x01\x03':
            raise ValueError("Befehl nicht bekannt")
        elif header == b'\x01\x04':
            raise ValueError("Unbekannte Register Anfrage")
        else:
            raise ValueError(f"Unbekannte Antwort: {data.hex()}")

    def read_write_register(self, addr_bytes: bytes, get_or_set: str = "get") -> bytes:
        """Register lesen, z.B. "\xFB" für global status."""
        header = b'\x01\x00' if get_or_set == "get" else b'\x01\x80'  # Standard Header für "get" und "set"
        footer = const.DATALINKESCAPE+const.ENDOFTEXT  # Standard Footer

        checksum = self.thz_checksum(header + b'\x00' + addr_bytes)  # xx = Platzhalter für die Checksumme
        telegram = self.construct_telegram(addr_bytes, header, footer, checksum)
        raw_response = self.send_request(telegram)
        payload = self.decode_response(raw_response)
        #_LOGGER.debug("Payload dekodiert: %s", payload.hex())
        return payload
    
    def construct_telegram(self, addr_bytes: bytes, header: bytes, footer: bytes, checksum: bytes) -> bytes:
        """
        Constructs a telegram for the THZ device based on the given address bytes.
        Returns: telegram ready to send
        """
        telegram = header + checksum + addr_bytes + footer
        return telegram
    

    def read_firmware_version(self) -> str:
        """
        Reads the firmware version from the THZ device.

        - Address (Register): 0xFD
        - Offset: 0
        - Length: 4 bytes
        - Interpreted as: unsigned big-endian integer
        """
        try:
            value_raw = self.read_value(b'\xFD', "get", 2, 2)            
            #_LOGGER.debug(f"Rohdaten Firmware-Version: {value_raw.hex()}")
            firmware_version = int.from_bytes(value_raw, byteorder='big', signed=False)
            _LOGGER.debug(f"Firmware-Version gelesen: {firmware_version}")
            return str(firmware_version)
        except Exception as e:
            # Fehlerbehandlung oder Logging, falls z. B. keine Verbindung oder ungültige Antwort
            raise RuntimeError(f"Firmware-Version konnte nicht gelesen werden: {e}")
        

    def read_value(self, addr_bytes: bytes, get_or_set: str, offset: int, length: int) -> bytes:
        """
        Reads a value from the THZ device.
        addr_bytes: bytes (e.g. b'\xFB')
        get_or_set: "get" or "set"
        Returns: byte value read from the device
        """
        response = self.read_write_register(addr_bytes, get_or_set)
        #_LOGGER.debug(f"Antwort von Wärmepumpe: {response.hex()}")
        value_raw = response[offset: offset + length]
        #_LOGGER.debug(f"Gelesener Wert (Offset {offset}, Length {length}): {value_raw.hex()}")
        return value_raw
    
    def read_block(self, addr_bytes: bytes, get_or_set: str) -> bytes:
        """
        Reads a value from the THZ device.
        addr_bytes: bytes (e.g. "\xFB")
        get_or_set: "get" or "set"
        Returns: block read from the device
        """
        response = self.read_write_register(addr_bytes, get_or_set)
        return response

    @property
    def firmware_version(self):
        return self._firmware_version

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    dev = THZDevice('/dev/ttyUSB0')


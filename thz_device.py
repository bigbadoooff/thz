import serial
import time
import logging
from . import const
from .register_maps.register_map_manager import RegisterMapManager, RegisterMapManager_Write

_LOGGER = logging.getLogger(__name__)

class THZDevice:
    def __init__(self, port=const.SERIAL_PORT, baudrate=const.BAUDRATE, read_timeout=const.TIMEOUT):
        self._port = port
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=read_timeout)
        self.read_timeout = read_timeout

        # Firmware lesen
        self._firmware_version = None
        self._firmware_version = self.read_firmware_version()
        # RegisterMapManager anhand der Firmware laden
        self.register_map_manager = RegisterMapManager(self.firmware_version)
        self.write_register_map_manager = RegisterMapManager_Write(self.firmware_version)
        self._cache = {}  # { block_name: (timestamp, payload) }
        self._cache_duration = 60  # seconds

    def read_block_cached(self, block: str) -> bytes:
        now = time.time()
        if block in self._cache:
            ts, data = self._cache[block]
            if now - ts < self._cache_duration:
                return data

        data = self.read_block(block, "get")
        self._cache[block] = (now, data)
        return data


    def close(self):
        self.ser.close()

    def thz_checksum(self, data: bytes) -> bytes:
        checksum = sum(b for i, b in enumerate(data) if i != 2)
        checksum = checksum % 256
        return bytes([checksum])

    def send_request(self, telegram: bytes) -> bytes:
        # 1. Send greeting
        self.ser.write(const.STX)
        self.ser.flush()
        _LOGGER.debug("Greeting gesendet: 02")

        # 2. Wait for 0x10 response
        response = self.ser.read(1)
        _LOGGER.debug(f"Greeting Antwort: {response.hex()}")
        if response != const.DLE:
            raise ValueError("Handshake Schritt 1 fehlgeschlagen: keine 0x10 Antwort")

        # 3. Send request telegram
        # telegram = self.build_request(telegram)
        self.ser.reset_input_buffer()
        self.ser.write(telegram)
        self.ser.flush()
        _LOGGER.debug("Request gesendet: %s", telegram.hex())

        # 4. Wait for 0x10 0x02 response
        response = self.ser.read(2)
        _LOGGER.debug(f"Antwort nach Request: {response.hex()}")
        if response != const.DLE + const.STX:
            raise ValueError("Handshake Schritt 2 fehlgeschlagen: keine 0x10 0x02 Antwort")

        # 5. Send confirmation 0x10
        self.ser.write(const.DLE)
        self.ser.flush()
        _LOGGER.debug("Bestätigung gesendet: 10")

        # 6. Read data telegram (ends with 0x10 0x03)
        data = bytearray()
        start_time = time.time()
        max_wait = self.read_timeout
        while time.time() - start_time < max_wait:
            if self.ser.in_waiting > 0:
                chunk = self.ser.read(self.ser.in_waiting)
                data.extend(chunk)
                # Check for footer (0x10 0x03) and minimum length
                if len(data) >= 8 and data[-2:] == const.DLE + const.ETX:
                    break
            else:
                time.sleep(0.01)
        _LOGGER.debug(f"Empfangene Rohdaten: {data.hex()}")

        if not (len(data) >= 8 and data[-2:] == const.DLE + const.ETX):
            raise ValueError("Keine gültige Antwort nach Datenanfrage erhalten")
        
        # 7. End of communication
        self.ser.write(const.STX)
        self.ser.flush()
        _LOGGER.debug("Greeting gesendet: 02")


        # Unescaping is already handled in decode_response
        return bytes(data)

    def unescape(self, data: bytes) -> bytes:
        # 0x10 0x10 -> 0x10
        data = data.replace(const.DLE+const.DLE, const.DLE)
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
        footer = const.DLE+const.ETX  # Standard Footer

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
        _LOGGER.debug(f"Antwort von Wärmepumpe: {response.hex()}")
        value_raw = response[offset: offset + length]
        _LOGGER.debug(f"Gelesener Wert (Offset {offset}, Length {length}): {value_raw.hex()}")
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


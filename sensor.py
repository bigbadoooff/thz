# custom_components/thz/sensor.py
import logging
from homeassistant.helpers.entity import Entity # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from .thz_device import THZDevice
from .register_maps.register_map_manager import RegisterMapManager, RegisterMapManager_Write
from .sensor_meta import SENSOR_META
import asyncio

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):

    # 4. Mapping setzen
    register_manager: RegisterMapManager = hass.data["thz"]["register_manager"]
    write_manager: RegisterMapManager_Write = hass.data["thz"]["write_manager"]
    device: THZDevice = hass.data["thz"]["device"]

    # 5. Sensoren anlegen
    sensors = []
    all_registers = register_manager.get_all_registers()
    for block, entries in all_registers.items():
        block = block.strip("pxx")  # Entferne "pxx" Präfix
        block_bytes = bytes.fromhex(block)
        for name, offset, length, decode_type, factor in entries:
            meta = SENSOR_META.get(name.strip(), {})
            entry = {
                "name": name.strip(),
                "offset": offset//2, # Register-Offset in Bytes
                "length": (length + 1) //2, # Register-Länge in Bytes; +1 um immer mindestens 1 Byte zu haben
                "decode": decode_type,
                "factor": factor,
                "unit": meta.get("unit"),
                "device_class": meta.get("device_class"),
                "icon": meta.get("icon"),
                "translation_key": meta.get("translation_key"),
            }
            sensors.append(THZGenericSensor(entry=entry, block=block_bytes, device=device)
                           )         
    async_add_entities(sensors, True)


def decode_value(raw: bytes, decode_type: str, factor: float = 1.0):
    if decode_type == "hex2int":
        #raw = raw[:2]  # Nur 2 Byte nutzen, Register meint mit 4 Anzahl Zeichen im Hex-String
        return int.from_bytes(raw, byteorder="big", signed=True) / factor
    elif decode_type == "hex":
        #raw = raw[:2]  # Nur 2 Byte nutzen, Register meint mit 4 Anzahl Zeichen im Hex-String
        return int.from_bytes(raw, byteorder="big")
    elif decode_type.startswith("bit"):
        bitnum = int(decode_type[3:])
        # _LOGGER.debug(f"Decode bit {bitnum} from raw {raw.hex()}")
        return (raw[0] >> bitnum) & 0x01
    elif decode_type.startswith("nbit"):
        bitnum = int(decode_type[4:])
        # _LOGGER.debug(f"Decode bit {bitnum} from raw {raw.hex()}")
        return not ((raw[0] >> bitnum) & 0x01)
    elif decode_type == "esp_mant":
        # Dummy Beispiel für spezielle Darstellung
        mant = int.from_bytes(raw[:4], byteorder="big")
        exp = int.from_bytes(raw[4:], byteorder="big")
        return mant * (2 ** exp)
    else:
        return raw.hex()
    
def normalize_entry(entry): #um nach und nach Mapping zu erweitern
    if isinstance(entry, tuple):
        name, offset, length, decode, factor = entry
        return {
            "name": name.strip(),
            "offset": offset,
            "length": length,
            "decode": decode,
            "factor": factor,
            "unit": None,
            "device_class": None,
            "icon": None,
            "translation_key": None
        }
    elif isinstance(entry, dict):
        return entry
    else:
        raise ValueError("Unsupported sensor entry format.")

class THZGenericSensor(Entity):
    def __init__(self, entry, block, device):
        e = normalize_entry(entry)
        self._name = e["name"]
        self._block = block
        self._offset = e["offset"]
        self._length = e["length"]
        self._decode_type = e["decode"]
        self._factor = e["factor"]
        self._unit = e.get("unit")
        self._device_class = e.get("device_class")
        self._icon = e.get("icon")
        self._translation_key = e.get("translation_key")
        self._device = device
        self._state = None

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state
    
    @property
    def native_unit_of_measurement(self):
        return self._unit

    @property
    def device_class(self):
        return self._device_class

    @property
    def icon(self):
        return self._icon

    @property
    def translation_key(self):
        return self._translation_key
    
    @property
    def unique_id(self):
        return f"thz_{self._block}_{self._offset}_{self._name.lower().replace(' ', '_')}"


    async def async_update(self):
        async with self._device.lock:
            payload = await self.hass.async_add_executor_job(self._device.read_block_cached, self._block)
            await asyncio.sleep(0.01)  # Kurze Pause, um sicherzustellen, dass das Gerät bereit ist   
        #_LOGGER.debug(f"Updating sensor {self._name} with payload: {payload.hex()}, offset: {self._offset}, length: {self._length}")
        raw_bytes = payload[self._offset:self._offset + self._length]
        self._state = decode_value(raw_bytes, self._decode_type, self._factor)
        #_LOGGER.debug(f"Sensor {self._name} updated with state: {self._state}")
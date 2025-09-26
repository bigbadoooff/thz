# custom_components/thz/sensor.py
import logging
from homeassistant.helpers.entity import Entity
from .thz_device import THZDevice
from .register_maps.register_map_manager import RegisterMapManager, RegisterMapManager_Write
from .sensor_meta import SENSOR_META
from .number import THZNumber
from .switch import THZSwitch
from .select import THZSelect
from .const import SERIAL_PORT

_LOGGER = logging.getLogger(__name__)


def setup_platform(hass, config, add_entities, discovery_info=None):
    # 1. Device "roh" initialisieren
    device = THZDevice(SERIAL_PORT)

    # 2. Firmware abfragen
    firmware_version = device.firmware_version  # z.B. "206"

    # 3. Mapping laden
    register_manager = RegisterMapManager(firmware_version)
    write_manager = RegisterMapManager_Write(firmware_version)

    # 4. Mapping setzen
    device.register_map_manager=register_manager
    device.write_register_map_manager=write_manager

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
    add_entities(sensors, True)

    # 6. Write-Register anlegen
    entities = []
    write_registers = write_manager.get_all_registers()
    _LOGGER.debug(f"write_registers: {write_registers}")
    for name, entry in write_registers.items():
        if entry["type"] == "number":
            _LOGGER.debug(f"Creating THZNumber for {name} with command {entry['command']}")
            entity = THZNumber(
                name=name,
                command=entry["command"],
                min_value=entry["min"],
                max_value=entry["max"],
                step=entry.get("step", 1),
                unit=entry.get("unit", ""),
                device_class=entry.get("device_class"),
                device=device,
                icon=entry.get("icon"),
                unique_id=f"thz_{name.lower().replace(' ', '_')}",
            )
            entities.append(entity)
        elif entry["type"] == "switch":
            _LOGGER.debug(f"Creating switch for {name} with command {entry['command']}")
            entity = THZSwitch(
                name=name,
                command=entry["command"],
                min_value=entry["min"],
                max_value=entry["max"],
                step=entry.get("step", 1),
                unit=entry.get("unit", ""),
                device_class=entry.get("device_class"),
                device=device,
                icon=entry.get("icon"),
                unique_id=f"thz_{name.lower().replace(' ', '_')}",
            )
            entities.append(entity)
        elif entry["type"] == "select":
            _LOGGER.debug(f"Creating select for {name} with command {entry['command']}")
            entity = THZSelect(
                name=name,
                command=entry["command"],
                min_value=entry["min"],
                max_value=entry["max"],
                step=entry.get("step", 1),
                unit=entry.get("unit", ""),
                device_class=entry.get("device_class"),
                device=device,
                icon=entry.get("icon"),
                decode_type=entry.get("decode_type"),
                unique_id=f"thz_{name.lower().replace(' ', '_')}",
            )
            entities.append(entity)
        else:
            _LOGGER.warning(f"Unsupported write register type: {entry['type']} for {name}")
        
    add_entities(entities, True)


def decode_value(raw: bytes, decode_type: str, factor: float = 1.0):
    if decode_type == "hex2int":
        #raw = raw[:2]  # Nur 2 Byte nutzen, Register meint mit 4 Anzahl Zeichen im Hex-String
        return int.from_bytes(raw, byteorder="big", signed=True) / factor
    elif decode_type == "hex":
        #raw = raw[:2]  # Nur 2 Byte nutzen, Register meint mit 4 Anzahl Zeichen im Hex-String
        return int.from_bytes(raw, byteorder="big")
    elif decode_type.startswith("bit"):
        bitnum = int(decode_type[3:])
        _LOGGER.debug(f"Decode bit {bitnum} from raw {raw.hex()}")
        return (raw[0] >> bitnum) & 0x01
    elif decode_type.startswith("nbit"):
        bitnum = int(decode_type[4:])
        _LOGGER.debug(f"Decode bit {bitnum} from raw {raw.hex()}")
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


    def update(self):
        payload = self._device.read_block_cached(self._block)
        #_LOGGER.debug(f"Updating sensor {self._name} with payload: {payload.hex()}, offset: {self._offset}, length: {self._length}")
        raw_bytes = payload[self._offset:self._offset + self._length]
        self._state = decode_value(raw_bytes, self._decode_type, self._factor)
        #_LOGGER.debug(f"Sensor {self._name} updated with state: {self._state}")
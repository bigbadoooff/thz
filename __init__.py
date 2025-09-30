from .const import DOMAIN, SERIAL_PORT
from .thz_device import THZDevice
from .register_maps.register_map_manager import RegisterMapManager, RegisterMapManager_Write

async def async_setup(hass, config_entry):
    # 1. Device "roh" initialisieren
    device = THZDevice(SERIAL_PORT)

    # 2. Firmware abfragen
    firmware_version = device.firmware_version  # z.B. "206"

    # 3. Mapping laden
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["write_manager"] = RegisterMapManager_Write(firmware_version)
    hass.data[DOMAIN]["register_manager"] = RegisterMapManager(firmware_version)

    # Forward setup to platforms
    for platform in ["sensor", "number", "switch", "select", "time"]:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(config_entry, platform)
        )

    # 4. Device speichern
    device.register_map_manager = hass.data[DOMAIN]["register_manager"]
    device.write_register_map_manager = hass.data[DOMAIN]["write_manager"]
    hass.data[DOMAIN]["device"] = device
    return True
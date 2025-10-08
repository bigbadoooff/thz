from homeassistant.config_entries import ConfigEntry # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant.core import HomeAssistant # pyright: ignore[reportMissingImports, reportMissingModuleSource]

from homeassistant.helpers.discovery import load_platform # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from .const import DOMAIN, SERIAL_PORT
from .thz_device import THZDevice
from .register_maps.register_map_manager import RegisterMapManager, RegisterMapManager_Write

firmware_version = ""  # leer, wird später überschrieben

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up THZ from config entry."""
    hass.data.setdefault(DOMAIN, {})

    data = config_entry.data
    conn_type = data["connection_type"]

    # 1. Device "roh" initialisieren
    if conn_type == "ip":
        device = THZDevice(connection="ip", host=data["host"], port=data["port"])
    elif conn_type == "usb":
        device = THZDevice(connection="usb", device_path=data["device"])
    else:
        raise ValueError("Ungültiger Verbindungstyp")


    # 2. Firmware abfragen
    firmware_version = device.firmware_version  # z.B. "206"

    # 3. Mapping laden
    write_manager = RegisterMapManager_Write(firmware_version)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["write_manager"] = write_manager
    hass.data[DOMAIN]["register_manager"] = RegisterMapManager(firmware_version)

    # 4. Device speichern
    device.register_map_manager = hass.data[DOMAIN]["register_manager"]
    device.write_register_map_manager = hass.data[DOMAIN]["write_manager"]
    hass.data[DOMAIN]["device"] = device
    

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(
        config_entry, ["sensor", "number", "switch", "select", "time"]
    )

    return True
async def async_unload_entry(hass, config_entry):
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, ["sensor", "number", "switch", "select", "time"]
    )
    return unload_ok
from homeassistant.config_entries import ConfigEntry # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant.core import HomeAssistant # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from datetime import timedelta

from homeassistant.helpers.discovery import load_platform # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from .const import DOMAIN
from .thz_device import THZDevice
from .register_maps.register_map_manager import RegisterMapManager, RegisterMapManager_Write
import logging
_LOGGER = logging.getLogger(__name__)



async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up THZ from config entry."""
    _LOGGER.debug("THZ async_setup_entry aufgerufen mit entry: %s", config_entry.as_dict())
    hass.data.setdefault(DOMAIN, {})

    data = config_entry.data
    conn_type = data["connection_type"]

    # 1. Device "roh" initialisieren
    if conn_type == "ip":
        device = THZDevice(connection="ip", host=data["host"], port=data["port"])
    elif conn_type == "usb":
        device = THZDevice(connection="usb", port=data["device"])
    else:
        raise ValueError("Ungültiger Verbindungstyp")
    
    await device.async_initialize(hass)

    _LOGGER.info("THZ-Device vollständig initialisiert (FW %s)", device.firmware_version)

    # 2. Firmware abfragen
    # firmware_version = await hass.async_add_executor_job(device.read_firmware_version)  # z.B. "206"

    # # 3. Mapping laden
    # write_manager = RegisterMapManager_Write(firmware_version)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["write_manager"] = device.write_register_map_manager
    hass.data[DOMAIN]["register_manager"] = device.register_map_manager

    # 4. Device speichern
    # device.register_map_manager = hass.data[DOMAIN]["register_manager"]
    # device.write_register_map_manager = hass.data[DOMAIN]["write_manager"]
    hass.data[DOMAIN]["device"] = device
    
    # 5. Prepare dict for storing all coordinators
    coordinators = {}
    refresh_intervals = config_entry.data.get("refresh_intervals", {})
    # Für jeden Block mit eigenem Intervall einen Coordinator anlegen
    for block, interval in refresh_intervals.items():
        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"THZ {block}",
            update_interval=timedelta(seconds=int(interval)),
            update_method=lambda b=block: _async_update_block(device, b),
        )
        await coordinator.async_config_entry_first_refresh()
        coordinators[block] = coordinator

    # im hass.data speichern
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "device": device,
        "coordinators": coordinators,
    }

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(
        config_entry, ["sensor", "number", "switch", "select", "time"]
    )

    return True

async def _async_update_block(device: THZDevice, block_name: str):
    """Wird vom Coordinator aufgerufen, um einen Block zu lesen."""
    block_bytes = bytes.fromhex(block_name.strip("pxx"))
    try:
        _LOGGER.debug("Lese Block %s ...", block_name)
        return await device.read_block(block_bytes, "get")
    except Exception as err:
        raise UpdateFailed(f"Fehler beim Lesen von {block_name}: {err}") from err


async def async_unload_entry(hass, entry):
    """Entferne Config Entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor", "select", "number", "time"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
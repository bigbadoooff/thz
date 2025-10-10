from homeassistant.components.time import TimeEntity    # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from datetime import time
from .register_maps.register_map_manager import RegisterMapManager_Write
from .thz_device import THZDevice
import asyncio

import logging
_LOGGER = logging.getLogger(__name__)

def time_to_quarters(t: time) -> int:
    if t is None:
        return 128  # 0x80
    return t.hour * 4 + (t.minute // 15)

def quarters_to_time(num: int) -> time:
    if num == 0x80:
        return None  # or time(0, 0) if you want a default
    quarters = num % 4
    hour = (num - quarters) // 4
    _LOGGER.debug(f"Converting {num} to time: {hour}:{quarters * 15}")
    return time(hour, quarters * 15)

async def async_setup_entry(hass, config_entry, async_add_entities):
    entities = []
    write_manager: RegisterMapManager_Write = hass.data["thz"]["write_manager"]
    device: THZDevice = hass.data["thz"]["device"]
    write_registers = write_manager.get_all_registers()
    _LOGGER.debug(f"write_registers: {write_registers}")
    for name, entry in write_registers.items():
        if entry["type"] == "time":
            _LOGGER.debug(f"Creating Time for {name} with command {entry['command']}")
            entity = THZTime(
                name=name,
                command=entry["command"],
                device=device,
                icon=entry.get("icon"),
                unique_id=f"thz_{name.lower().replace(' ', '_')}",
            )
            entities.append(entity)

    async_add_entities(entities, True)

class THZTime(TimeEntity):
    _attr_should_poll = True

    def __init__(self, name, command, device, icon=None, unique_id=None):
        self._attr_name = name
        self._command = command
        self._device = device
        self._attr_icon = icon or "mdi:clock"
        self._attr_unique_id = unique_id or f"thz_time_{command.lower()}_{name.lower().replace(' ', '_')}"
        self._attr_native_value = None

    @property
    def native_value(self):
        return self._attr_native_value

    async def async_update(self):
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(self._device.read_value, bytes.fromhex(self._command), "get", 4, 2)
        num = value_bytes[0]
        self._attr_native_value = quarters_to_time(num)

    async def async_set_native_value(self, value: str):
        num = time_to_quarters(value)
        self._device.write_value(bytes.fromhex(self._command), num)
        self._attr_native_value = value




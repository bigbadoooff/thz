from homeassistant.components.number import NumberEntity # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from .register_maps.register_map_manager import RegisterMapManager_Write
from .thz_device import THZDevice
from .const import DOMAIN
import asyncio

import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
# ... create THZNumber entities ...
    entities = []
    write_manager: RegisterMapManager_Write = hass.data[DOMAIN]["write_manager"]
    device: THZDevice = hass.data[DOMAIN]["device"]
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
        
    async_add_entities(entities)
class THZNumber(NumberEntity):
    def __init__(self, name:str, command:bytes, min_value, max_value, step, unit, device_class, device, icon=None, unique_id=None):
        self._attr_name = name
        self._command = command
        self._attr_native_min_value = float(min_value) if min_value != "" else None
        self._attr_native_max_value = float(max_value) if max_value != "" else None
        self._attr_native_step = float(step) if step != "" else 1
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._device = device
        self._attr_icon = icon or "mdi:eye"
        self._attr_unique_id = unique_id or f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"
        self._attr_native_value = None

    @property
    def native_value(self):
        return self._attr_native_value

    async def async_update(self):
        # _LOGGER.debug(f"Updating number {self._attr_name} with command {self._command}")
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(self._device.read_value, bytes.fromhex(self._command), "get", 4, 2)
        value = int.from_bytes(value_bytes, byteorder='big', signed=False)*self._attr_native_step
        self._attr_native_value = value

    async def async_set_native_value(self, value: float):
        value_int = int(value)
        async with self._device.lock:
            await self.hass.async_add_executor_job(self._device.write_value, bytes.fromhex(self._command), value_int/self._attr_native_step)
        self._attr_native_value = value


from homeassistant.components.switch import SwitchEntity
import logging

_LOGGER = logging.getLogger(__name__)

class THZSwitch(SwitchEntity):
    _attr_should_poll = True

    def __init__(self, name, command, min_value, max_value, step, unit, device_class, device, icon=None, unique_id=None):
        self._attr_name = name
        self._command = command
        self._device = device
        self._attr_icon = icon or "mdi:eye"
        self._attr_unique_id = unique_id or f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"
        self._is_on = False

    @property
    def is_on(self):
        return self._is_on

    async def async_update(self):
        # Read the value from the device and interpret as on/off
        _LOGGER.debug(f"Updating switch {self._attr_name} with command {self._command}")
        value_bytes = self._device.read_value(bytes.fromhex(self._command), "get", 4, 2)
        value = int.from_bytes(value_bytes, byteorder='big', signed=False)
        self._is_on = bool(value)

    def turn_on(self, **kwargs):
        self._device.write_value(bytes.fromhex(self._command), 1)
        self._is_on = True

    def turn_off(self, **kwargs):
        self._device.write_value(bytes.fromhex(self._command), 0)
        self._is_on = False
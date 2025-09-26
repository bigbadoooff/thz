from homeassistant.components.number import NumberEntity

class THZNumber(NumberEntity):
    def __init__(self, name:str, command:bytes, min_value, max_value, step, unit, device_class, device, icon=None, unique_id=None):
        self._attr_name = name
        self._command = command
        self._attr_min_value = float(min_value) if min_value != "" else None
        self._attr_max_value = float(max_value) if max_value != "" else None
        self._attr_step = float(step) if step != "" else 1
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._device = device
        self._attr_icon = icon or "mdi:eye"
        self._attr_unique_id = unique_id or f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"
        self._attr_native_value = None

    @property
    def native_value(self):
        return self._attr_native_value

    def async_update(self):
        # You may need to adapt the offset/length for your protocol
        value_bytes = self._device.read_value(bytes.fromhex(self._command), "get", 4, 2)
        value = int.from_bytes(value_bytes, byteorder='big', signed=False)
        self._attr_native_value = value

    def async_set_native_value(self, value: float):
        value_int = int(value)
        self._device.write_value(bytes.fromhex(self._command), value_int)
        self._attr_native_value = value
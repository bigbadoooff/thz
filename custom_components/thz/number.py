"""THZ Number Entity Platform."""
from datetime import timedelta
# Set update interval to 10 minutes
SCAN_INTERVAL = timedelta(minutes=10)
import asyncio
import logging

from homeassistant.components.number import ConfigEntry, NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .register_maps.register_map_manager import RegisterMapManagerWrite
from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up THZ number entities from config entry."""
    entities = []
    write_manager: RegisterMapManagerWrite = hass.data[DOMAIN]["write_manager"]
    device: THZDevice = hass.data[DOMAIN]["device"]
    write_registers = write_manager.get_all_registers()
    _LOGGER.debug("write_registers: %s", write_registers)
    for name, entry in write_registers.items():
        if entry["type"] == "number":
            _LOGGER.debug(
                "Creating THZNumber for %s with command %s", name, entry["command"]
            )
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
                decode_type=entry["decode_type"],
            )
            entities.append(entity)

    async_add_entities(entities)


class THZNumber(NumberEntity):
    """Representation of a THZ Number entity."""

    def __init__(
        self,
        name: str,
        command: str,
        min_value,
        max_value,
        step,
        unit,
        device_class,
        decode_type,
        device,
        icon=None,
        unique_id=None,
    ) -> None:
        """Initialize a new instance of the class.

        Args:
            name (str): The name of the number entity.
            command (str): The command associated with this entity.
            min_value: The minimum allowed value (can be empty string, defaults to 0.0).
            max_value: The maximum allowed value (can be empty string, defaults to 100.0).
            step: The step size for value changes (can be empty string, defaults to 1).
            unit: The unit of measurement for the value.
            device_class: The device class for the entity.
            decode_type: The type used for decoding values.
            device: The device instance this entity belongs to.
            icon (optional): The icon to use for this entity. Defaults to "mdi:eye".
            unique_id (optional): The unique identifier for this entity. If not provided, a unique ID is generated.
        """
        self._attr_name = name
        self._command = command
        self._attr_native_min_value = float(min_value) if min_value != "" else 0.0
        self._attr_native_max_value = float(max_value) if max_value != "" else 100.0
        self._attr_native_step = float(step) if step != "" else 1
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._decode_type = decode_type
        self._device = device
        self._attr_icon = icon or "mdi:eye"
        self._attr_unique_id = (
            unique_id or f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"
        )
        self._attr_native_value = None

    @property
    def native_value(self) -> float | None:
        """Return the native value of the number."""
        return self._attr_native_value


    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        # _LOGGER.debug("Updating number %s with command %s", self._attr_name, self._command)
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(
                self._device.read_value, bytes.fromhex(self._command), "get", 4, 2
            )
        value = (
            int.from_bytes(value_bytes, byteorder="big", signed=False)
            * self._attr_native_step
        )
        _LOGGER.debug("Recv number %s with value %s", self._attr_name, value_bytes)
        if self._decode_type != "0clean":
            value = (
                int.from_bytes(value_bytes, byteorder="big", signed=True)
                * self._attr_native_step
            )
        else:
            value = value_bytes[0]
        _LOGGER.debug("Recv number %s with real value %s", self._attr_name, value)
        self._attr_native_value = value


    async def async_set_native_value(self, value: float) -> None:
        """Set new value for the number."""
        value_int = int(value / self._attr_native_step)
        _LOGGER.debug("Send number %s with real value %s", self._attr_name, value_int)
        # value_bytes = value_int.to_bytes(2, byteorder='big', signed=True)) #_LOGGER.debug("Send number %s with value %s", self._attr_name, value_bytes)
        async with self._device.lock:
            if self._decode_type != "0clean":
                await self.hass.async_add_executor_job(
                    self._device.write_value,
                    bytes.fromhex(self._command),
                    value_int.to_bytes(2, byteorder="big", signed=True),
                )
            else:
                await self.hass.async_add_executor_job(
                    self._device.write_value,
                    bytes.fromhex(self._command),
                    value_int.to_bytes(1, byteorder="big", signed=True),
                )
            await asyncio.sleep(
                0.01
            )  # Kurze Pause, um sicherzustellen, dass das Gerät bereit ist
        self._attr_native_value = value

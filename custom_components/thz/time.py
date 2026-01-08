"""Time entity for THZ devices."""
from datetime import timedelta
# Set update interval to 10 minutes
SCAN_INTERVAL = timedelta(minutes=10)

import asyncio
from datetime import time
import logging

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .register_maps.register_map_manager import RegisterMapManagerWrite
from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)


def time_to_quarters(t: time | None) -> int:
    """Convert a time object to the number of 15-minute intervals since midnight.

    Parameters
    ----------
    t : datetime.time | None
        The time to convert. If None, a sentinel value of 128 (0x80) is returned.

    Returns:
    -------
    int
        The count of 15-minute intervals since midnight:
        - 0 represents 00:00,
        - each hour adds 4 intervals,
        - minutes are floored to the nearest 15-minute boundary (minute // 15).
        Valid normal values range from 0 to 95 (00:00 through 23:45). 128 is used as a special sentinel for unset/None.

    Examples:
    --------
    >>> from datetime import time
    >>> time_to_quarters(time(0, 0))
    0
    >>> time_to_quarters(time(1, 30))
    6
    >>> time_to_quarters(None)
    128
    """
    if t is None:
        return 128  # 0x80
    return t.hour * 4 + (t.minute // 15)


def quarters_to_time(num: int) -> time | None:
    """Convert a count of 15-minute intervals since midnight to a datetime.time.

    Parameters
    ----------
    num : int
        Number of 15-minute intervals (quarters) since midnight. The expected range is
        0–95 (0 => 00:00, 95 => 23:45). A special sentinel value 0x80 indicates "no time"
        and causes the function to return None.

    Returns:
    -------
    datetime.time | None
        A datetime.time representing the corresponding hour and minute, where the hour is
        computed as num // 4 and the minutes as (num % 4) * 15. If num == 0x80, returns None.

    Notes:
    -----
    - The function does not enforce the 0–95 range; values outside this range (including
      negative values) will be converted arithmetically and may produce hours outside 0–23.
    - If strict validation is required, validate num beforehand or modify the function to
      raise a ValueError for out-of-range inputs.

    Examples:
    --------
    >>> quarters_to_time(0)    # 00:00
    datetime.time(0, 0)
    >>> quarters_to_time(1)    # 00:15
    datetime.time(0, 15)
    >>> quarters_to_time(95)   # 23:45
    datetime.time(23, 45)
    >>> quarters_to_time(0x80) # sentinel for "no time"
    None
    """
    if num == 0x80:
        return None
    quarters = num % 4
    hour = (num - quarters) // 4
    _LOGGER.debug(f"Converting {num} to time: {hour}:{quarters * 15}")
    if hour == 24:
        hour = 23
        quarters = 3
    return time(hour, quarters * 15)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up THZ Time entities from a config entry.

    This function creates THZTime entities based on write registers of type "time"
    from the device's register map.

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry to set up.
        async_add_entities: Callback to add new entities.

    Returns:
        None. Entities are added via the async_add_entities callback.

    Note:
        - Requires 'write_manager' and 'device' to be present in hass.data['thz']
        - Creates a THZTime entity for each register with type 'time'
        - Entity IDs are generated from the register name, converted to lowercase with spaces replaced by underscores
    """
    entities = []
    write_manager: RegisterMapManagerWrite = hass.data["thz"]["write_manager"]
    device: THZDevice = hass.data["thz"]["device"]
    write_registers = write_manager.get_all_registers()
    _LOGGER.debug("write_registers: %s", write_registers)
    for name, entry in write_registers.items():
        if entry["type"] == "time":
            _LOGGER.debug(
                "Creating Time for %s with command %s", name, entry["command"]
            )
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
    """Time entity for THZ devices.

    This class represents a time entity that can read and write time values from/to THZ devices.
    It handles conversion between quarter-hour based time values used by the device and standard
    time format used by Home Assistant.

    Attributes:
        _attr_should_poll (bool): Indicates if entity should be polled for updates.
        _attr_name (str): Name of the entity.
        _command (str): Command hex string to communicate with device.
        _device (THZDevice): Device instance this entity belongs to.
        _attr_icon (str): Icon to display for this entity.
        _attr_unique_id (str): Unique ID for this entity.
        _attr_native_value (str): Current time value in HH:MM format.

    Args:
        name (str): Name of the time entity.
        command (str): Hex command string for device communication.
        device (THZDevice): THZ device instance.
        icon (str, optional): Custom icon for the entity. Defaults to "mdi:clock".
        unique_id (str, optional): Custom unique ID. Defaults to generated ID based on command and name.
    """

    _attr_should_poll = True

    def __init__(self, name, command, device, icon=None, unique_id=None) -> None:
        """Initialize a new instance of the class.

        Args:
            name (str): The name of the entity.
            command (str): The command associated with the entity.
            device: The device instance this entity is associated with.
            icon (str, optional): The icon to use for this entity. Defaults to "mdi:clock" if not provided.
            unique_id (str, optional): A unique identifier for this entity. If not provided, a unique ID is generated.
        """

        self._attr_name = name
        self._command = command
        self._device = device
        self._attr_icon = icon or "mdi:clock"
        self._attr_unique_id = (
            unique_id or f"thz_time_{command.lower()}_{name.lower().replace(' ', '_')}"
        )
        self._attr_native_value = None

    @property
    def native_value(self):
        """Return the native value of the time."""
        return self._attr_native_value

    async def async_update(self):
        """Fetch new state data for the time."""
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(
                self._device.read_value, bytes.fromhex(self._command), "get", 4, 2
            )
            await asyncio.sleep(
                0.01
            )  # Kurze Pause, um sicherzustellen, dass das Gerät bereit ist
        num = value_bytes[0]
        self._attr_native_value = quarters_to_time(num)

    async def async_set_native_value(self, value: str):
        """Set new value for the time."""

        # Convert string (e.g., "12:30") to datetime.time
        if value is None:
            t_value = None
        else:
            hour, minute = map(int, value.split(":"))
            t_value = time(hour, minute)
        num = time_to_quarters(t_value)
        num_bytes = num.to_bytes(2, byteorder="big", signed=False)
        async with self._device.lock:
            await self.hass.async_add_executor_job(
                self._device.write_value(bytes.fromhex(self._command), num_bytes)
            )
            await asyncio.sleep(
                0.01
            )  # Kurze Pause, um sicherzustellen, dass das Gerät bereit ist
        self._attr_native_value = t_value

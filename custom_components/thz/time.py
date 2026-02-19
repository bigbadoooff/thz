"""Time entity for THZ devices."""
from __future__ import annotations

import asyncio
import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZBaseEntity
from .const import (
    DOMAIN,
    TIME_VALUE_UNSET,
    WRITE_REGISTER_OFFSET,
    WRITE_REGISTER_LENGTH,
)
from .entity_translations import get_translation_key
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
        return TIME_VALUE_UNSET  # 0x80 sentinel value for "no time"
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
    - The function validates the 0–95 range and logs a warning for out-of-range values.
    - Invalid values are clamped to the valid range (0-95) to prevent crashes.

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
    if num == TIME_VALUE_UNSET:
        return None

    # Validate range and clamp if necessary
    if num < 0 or num > 95:
        _LOGGER.warning(
            "Invalid quarters value %s (expected 0-95). Value will be clamped. "
            "This may indicate a byte order issue in reading the time value.",
            num
        )
        num = max(0, min(95, num))

    quarters = num % 4
    hour = (num - quarters) // 4
    _LOGGER.debug("Converting %s to time: %s:%s", num, hour, quarters * 15)
    return time(hour, quarters * 15)




def _create_time_entities(name, entry, device, device_id, write_interval):
    """Factory function to create time entities, handling schedule types specially."""
    if entry["type"] == "schedule":
        # Create both start and end time entities for schedule type
        # Pass the base name to both so they can look up the base translation key
        return [
            THZScheduleTime(
                name=f"{name} Start",
                base_name=name,
                entry=entry,
                device=device,
                device_id=device_id,
                time_type="start",
                scan_interval=write_interval,
            ),
            THZScheduleTime(
                name=f"{name} End",
                base_name=name,
                entry=entry,
                device=device,
                device_id=device_id,
                time_type="end",
                scan_interval=write_interval,
            ),
        ]
    else:
        # Regular time entity
        return THZTime(
            name=name,
            entry=entry,
            device=device,
            device_id=device_id,
            scan_interval=write_interval,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up THZ Time entities from a config entry."""
    # Use platform setup for both "time" and "schedule" types
    write_manager: RegisterMapManagerWrite = hass.data[DOMAIN]["write_manager"]
    device: THZDevice = hass.data[DOMAIN]["device"]
    device_id = hass.data[DOMAIN]["device_id"]

    from .const import DEFAULT_UPDATE_INTERVAL
    write_interval = config_entry.data.get("write_interval", DEFAULT_UPDATE_INTERVAL)

    write_registers = write_manager.get_all_registers()
    _LOGGER.debug("Loading time platform with %d registers", len(write_registers))

    entities = []
    for name, entry in write_registers.items():
        if entry["type"] in ("time", "schedule"):
            _LOGGER.debug(
                "Creating time entities for %s (type: %s) with command %s",
                name, entry["type"], entry["command"]
            )
            new_entities = _create_time_entities(name, entry, device, device_id, write_interval)
            entities.extend(new_entities if isinstance(new_entities, list) else [new_entities])

    _LOGGER.info("Created %d time entities", len(entities))
    async_add_entities(entities, True)




class THZTime(THZBaseEntity, TimeEntity):
    """Time entity for THZ devices."""

    def __init__(
        self,
        name: str,
        entry: dict,
        device: THZDevice,
        device_id: str,
        scan_interval: int | None = None
    ) -> None:
        """Initialize a THZ time entity.

        Args:
            name: The name of the time entity.
            entry: The register entry dict containing configuration.
            device: THZ device instance.
            device_id: The device identifier for linking to device.
            scan_interval: The scan interval in seconds for polling updates.
        """
        # Initialize base class with common properties
        super().__init__(
            name=name,
            command=entry["command"],
            device=device,
            device_id=device_id,
            icon=entry.get("icon", "mdi:clock"),
            scan_interval=scan_interval,
            translation_key=get_translation_key(name),
        )

        # Override has_entity_name for time entities (always False for backward compatibility)
        self._attr_has_entity_name = True

        self._attr_native_value = None

    @property
    def name(self) -> str | None:
        """Return the name of the time entity.

        Always return the entity name since time entities don't use translation keys.
        """
        return self._attr_name

    @property
    def native_value(self):
        """Return the native value of the time."""
        return self._attr_native_value

    async def async_update(self):
        """Fetch new state data for the time."""
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(
                self._device.read_value,
                bytes.fromhex(self._command),
                "get",
                WRITE_REGISTER_OFFSET,
                WRITE_REGISTER_LENGTH,
            )
            # Short pause to ensure the device is ready
            await asyncio.sleep(0.01)

        # Time values are stored as single bytes (0-95 quarters)
        num = value_bytes[0]
        self._attr_native_value = quarters_to_time(num)
        _LOGGER.debug("Updated time %s: %s quarters -> %s", self._attr_name, num, self._attr_native_value)

    async def async_set_native_value(self, value: str):
        """Set new value for the time."""
        # Convert string (e.g., "12:30") to datetime.time
        if value is None:
            t_value = None
        else:
            hour, minute = map(int, value.split(":"))
            t_value = time(hour, minute)

        num = time_to_quarters(t_value)
        _LOGGER.debug("Setting time %s to %s (%s quarters)", self._attr_name, t_value, num)

        # Write as 2 bytes to match the protocol's read format (offset=4, length=2)
        # even though only the first byte contains the meaningful time value (0-95 quarters).
        # Second byte is set to 0 as it appears to be unused by the device.
        num_bytes = bytes([num, 0])

        async with self._device.lock:
            await self.hass.async_add_executor_job(
                self._device.write_value, bytes.fromhex(self._command), num_bytes
            )
            # Short pause to ensure the device is ready
            await asyncio.sleep(0.01)

        self._attr_native_value = t_value




class THZScheduleTime(THZBaseEntity, TimeEntity):
    """Time entity for THZ schedule start/end times."""

    def __init__(
        self,
        name: str,
        base_name: str,
        entry: dict,
        device: THZDevice,
        device_id: str,
        time_type: str,
        scan_interval: int | None = None
    ) -> None:
        """Initialize a THZ schedule time entity.

        Args:
            name: The display name of the time entity (e.g., "programHC1_Mo_0 Start").
            base_name: The base register name for translation lookup (e.g., "programHC1_Mo_0").
                This is used to construct the translation key as base_translation_key + "_start" or "_end".
            entry: The register entry dict containing configuration.
            device: THZ device instance.
            device_id: The device identifier for linking to device.
            time_type: Either "start" or "end".
            scan_interval: The scan interval in seconds for polling updates.
            
        Example:
            For base_name="programHC1_Mo_0" and time_type="start", the translation key
            becomes "programhc1_mo_0_start" which resolves to "HC1 Program Monday 1 Start".
        """
        # Get the base translation key and add _start or _end suffix
        base_translation_key = get_translation_key(base_name)
        if base_translation_key:
            translation_key = f"{base_translation_key}_{time_type}"
        else:
            translation_key = None
        
        # Initialize base class with common properties
        super().__init__(
            name=name,
            command=entry["command"],
            device=device,
            device_id=device_id,
            icon=entry.get("icon", "mdi:calendar-clock"),
            scan_interval=scan_interval,
            translation_key=translation_key,
        )

        # Override has_entity_name for time entities (always False for backward compatibility)
        self._attr_has_entity_name = True

        self._time_type = time_type
        self._attr_native_value = None

        # Override unique_id to include time_type
        self._attr_unique_id = f"thz_schedule_time_{self._command.lower()}_{name.lower().replace(' ', '_')}_{time_type}"

    @property
    def native_value(self):
        """Return the native value of the time."""
        return self._attr_native_value

    async def async_update(self):
        """Fetch new state data for the schedule time."""
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(
                self._device.read_value, bytes.fromhex(self._command), "get", 4, 4
            )
            # Short pause to ensure the device is ready
            await asyncio.sleep(0.01)

        # Schedule data format (from FHEM 7prog):
        # - Bytes 0-3: header/other data
        # - Byte 4 (offset 8 hex digits): start time (1 byte, 0-95 quarters)
        # - Byte 5 (offset 10 hex digits): end time (1 byte, 0-95 quarters)
        # However, read_value returns data starting at offset 4, so:
        # - value_bytes[0]: start time
        # - value_bytes[1]: end time
        if self._time_type == "start":
            num = value_bytes[0]
        else:  # "end"
            num = value_bytes[1]

        self._attr_native_value = quarters_to_time(num)
        _LOGGER.debug(
            "Updated schedule time %s (%s): %s quarters -> %s",
            self.name, self._time_type, num, self._attr_native_value
        )

    async def async_set_native_value(self, value: str):
        """Set new value for the schedule time."""
        # Convert string (e.g., "12:30") to datetime.time
        if value is None:
            t_value = None
        else:
            try:
                parts = value.split(":")
                if len(parts) != 2:
                    raise ValueError(f"Invalid time format: {value}")
                hour, minute = int(parts[0]), int(parts[1])
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError(f"Invalid time values: hour={hour}, minute={minute}")
                t_value = time(hour, minute)
            except (ValueError, AttributeError) as e:
                _LOGGER.error("Failed to parse time value '%s': %s", value, e)
                raise

        new_num = time_to_quarters(t_value)
        _LOGGER.debug(
            "Setting schedule time %s (%s) to %s (%s quarters)",
            self.name, self._time_type, t_value, new_num
        )

        # Read the current schedule data (4 bytes total)
        async with self._device.lock:
            current_bytes = await self.hass.async_add_executor_job(
                self._device.read_value, bytes.fromhex(self._command), "get", 4, 4
            )

        # Modify only the relevant byte (start or end time)
        schedule_bytes = bytearray(current_bytes)
        if self._time_type == "start":
            schedule_bytes[0] = new_num
        else:  # "end"
            schedule_bytes[1] = new_num

        # Write the modified schedule back
        async with self._device.lock:
            await self.hass.async_add_executor_job(
                self._device.write_value,
                bytes.fromhex(self._command),
                bytes(schedule_bytes)
            )
            # Short pause to ensure the device is ready
            await asyncio.sleep(0.01)

        self._attr_native_value = t_value

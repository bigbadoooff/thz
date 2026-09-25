"""Time entity for THZ devices."""

from __future__ import annotations

from datetime import time
import logging

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZBaseEntity, THZParameterEntity
from .const import (
    TIME_VALUE_UNSET,
)
from .devices import assign_subdevices
from .entity_translations import get_translation_key
from .parameter_io import async_read_parameter, async_write_parameter
from .parameter_poller import ReadKey
from .register_maps.model import WriteParam
from .register_maps.register_map_manager import RegisterMapManagerWrite
from .runtime_data import THZConfigEntry
from .thz_device import THZDevice
from .write_errors import raise_write_errors

_LOGGER = logging.getLogger(__name__)

# A schedule register's start and end bytes and the two after them.
SCHEDULE_OFFSET = 4
SCHEDULE_LENGTH = 4

# Values come from the parameter poller or a block coordinator; writes go
# to the device directly, one at a time.
PARALLEL_UPDATES = 1


def time_to_quarters(t: time | None, is_end_time: bool = False) -> int:
    """Convert a time object to the number of 15-minute intervals since midnight.

    Parameters
    ----------
    t : datetime.time | None
        The time to convert. If None, a sentinel value of 128 (0x80) is returned.
    is_end_time : bool
        When True, midnight (00:00) is treated as end-of-day (24:00) and encoded
        as 96 rather than 0. This is used for schedule end-time entities where
        a value of 00:00 means "until midnight / end of day".

    Returns:
    -------
    int
        The count of 15-minute intervals since midnight:
        - 0 represents 00:00 (start of day),
        - each hour adds 4 intervals,
        - minutes are floored to the nearest 15-minute boundary (minute // 15).
        - 96 represents 24:00 (end of day) when is_end_time=True and t == 00:00.
        Valid normal values range from 0 to 95 (00:00 through 23:45). 128 is used as
        a special sentinel for unset/None.

    Examples:
    --------
    >>> from datetime import time
    >>> time_to_quarters(time(0, 0))
    0
    >>> time_to_quarters(time(0, 0), is_end_time=True)
    96
    >>> time_to_quarters(time(1, 30))
    6
    >>> time_to_quarters(None)
    128
    """
    if t is None:
        return TIME_VALUE_UNSET  # 0x80 sentinel value for "no time"
    # For end-time entities, midnight represents end-of-day (24:00) -> 96
    if is_end_time and t.hour == 0 and t.minute == 0:
        return 96
    return t.hour * 4 + (t.minute // 15)


def quarters_to_time(num: int) -> time | None:
    """Convert a count of 15-minute intervals since midnight to a datetime.time.

    Parameters
    ----------
    num : int
        Number of 15-minute intervals (quarters) since midnight. The expected range is
        0-95 (0 => 00:00, 95 => 23:45). The special value 96 represents 24:00
        (end-of-day) and is returned as time(0, 0). A special sentinel value 0x80
        indicates "no time" and causes the function to return None.

    Returns:
    -------
    datetime.time | None
        A datetime.time representing the corresponding hour and minute. If num == 0x80,
        returns None. If num == 96, returns time(0, 0) representing end-of-day (24:00).

    Notes:
    -----
    - The function validates the 0-95 range (plus 96 for end-of-day) and logs a
      warning for other out-of-range values.
    - Invalid values outside 0-96 are clamped to the valid range (0-95) to prevent
      crashes.

    Examples:
    --------
    >>> quarters_to_time(0)    # 00:00
    datetime.time(0, 0)
    >>> quarters_to_time(1)    # 00:15
    datetime.time(0, 15)
    >>> quarters_to_time(95)   # 23:45
    datetime.time(23, 45)
    >>> quarters_to_time(96)   # 24:00 -> 00:00 (end of day)
    datetime.time(0, 0)
    >>> quarters_to_time(0x80) # sentinel for "no time"
    None
    """
    if num == TIME_VALUE_UNSET:
        return None

    # 96 represents 24:00 (end of day), which is expressed as 00:00 in HA
    if num == 96:
        _LOGGER.debug("Converting end-of-day value 96 (24:00) to 00:00")
        return time(0, 0)

    # Validate range and clamp if necessary
    if num < 0 or num > 95:
        _LOGGER.warning(
            "Invalid quarters value %s "
            "(expected 0-95 or 96 for end-of-day). Value will be clamped. "
            "This may indicate a byte order issue in reading the time value.",
            num,
        )
        num = max(0, min(95, num))

    quarters = num % 4
    hour = (num - quarters) // 4
    _LOGGER.debug("Converting %s to time: %s:%s", num, hour, quarters * 15)
    return time(hour, quarters * 15)


def time_byte_index(decode_type: str | None) -> int:
    """Return which of a time register's two data bytes holds the time.

    FHEM's parsing rules put the holiday times ("9holy") and the party start
    ("8party") in the second data byte (nibble offset 10); every other
    single time register uses the first one.
    """
    return 1 if decode_type in ("9holy", "8party") else 0


# Registers holding two times: the party start (second data byte) and end
# (first data byte), FHEM's "8party" parsing rule.
TWO_TIME_DECODE_TYPES = ("8party",)


def _create_time_entities(
    name: str,
    entry: WriteParam,
    device: THZDevice,
    device_id: str,
    entity_id_style: str = "default",
    entity_visibility: str = "default",
    entity_id_prefix: str | None = None,
) -> list[THZTime | THZScheduleTime]:
    """Factory function to create time entities, handling schedule types specially."""
    if entry.type == "schedule":
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
                entity_id_style=entity_id_style,
                entity_visibility=entity_visibility,
                entity_id_prefix=entity_id_prefix,
            ),
            THZScheduleTime(
                name=f"{name} End",
                base_name=name,
                entry=entry,
                device=device,
                device_id=device_id,
                time_type="end",
                entity_id_style=entity_id_style,
                entity_visibility=entity_visibility,
                entity_id_prefix=entity_id_prefix,
            ),
        ]

    def time_entity(
        entity_name: str, base_name: str | None = None, end: bool = False
    ) -> THZTime:
        return THZTime(
            name=entity_name,
            base_name=base_name,
            end=end,
            entry=entry,
            device=device,
            device_id=device_id,
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
        )

    if entry.decode_type in TWO_TIME_DECODE_TYPES:
        # The start keeps the parameter's own name (and unique id); the end
        # is a second entity on the other byte of the register.
        return [time_entity(name), time_entity(f"{name} End", name, end=True)]
    return [time_entity(name)]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up THZ Time entities from a config entry."""
    # Use platform setup for both "time" and "schedule" types
    entry_data = config_entry.runtime_data
    write_manager: RegisterMapManagerWrite = entry_data.write_manager
    device: THZDevice = entry_data.device
    device_id = entry_data.device_id
    entity_id_style = entry_data.entity_id_style
    entity_visibility = entry_data.entity_visibility
    entity_id_prefix = entry_data.entity_id_prefix

    params = write_manager.params()
    _LOGGER.debug("Loading time platform with %d registers", len(params))

    entities: list[THZTime | THZScheduleTime] = []
    for name, entry in params.items():
        if entry.type in ("time", "schedule"):
            _LOGGER.debug(
                "Creating time entities for %s (type: %s) with command %s",
                name,
                entry.type,
                entry.command,
            )
            new_entities = _create_time_entities(
                name,
                entry,
                device,
                device_id,
                entity_id_style,
                entity_visibility,
                entity_id_prefix,
            )
            entities.extend(new_entities)
    for entity in entities:
        entity._coordinators = entry_data.coordinators
        entity._poller = entry_data.poller

    _LOGGER.debug("Created %d time entities", len(entities))
    assign_subdevices(entities, config_entry.data)
    # Values arrive from the poller; see parameter_poller.py.
    async_add_entities(entities)

    # Home Assistant's built-in time.set_value service cannot represent "no
    # time" -- its schema requires a real datetime.time -- so there is no
    # way to send the device's own "unset" state through it. Expose a
    # dedicated entity service instead, targetable at any of this
    # platform's entities, that calls async_clear_value() directly.
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "clear_value",
        {},
        "async_clear_value",
    )


class THZTime(THZParameterEntity, TimeEntity):
    """Time entity for THZ devices."""

    def __init__(
        self,
        name: str,
        entry: WriteParam,
        device: THZDevice,
        device_id: str,
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
        base_name: str | None = None,
        end: bool = False,
    ) -> None:
        """Initialize a THZ time entity.

        Args:
            name: The name of the time entity.
            entry: The write-map parameter.
            device: THZ device instance.
            device_id: The device identifier for linking to device.
            entity_id_style: "default" or "fhem" (see base_entity.py).
            entity_visibility: "default"/"extended"/"all" (see base_entity.py).
            entity_id_prefix: Optional device alias prefix for "fhem"-style
                entity_ids (see base_entity.py).
            base_name: The parameter's name when ``name`` is derived from it
                (the end of a two-time register); used for the translation.
            end: This entity is the end time of a two-time register
                (TWO_TIME_DECODE_TYPES): first data byte, and 00:00 is
                written as 24:00 like a schedule's end.
        """
        translation_key = get_translation_key(base_name or name)
        if end and translation_key:
            translation_key = f"{translation_key}_end"
        # Initialize base class with common properties
        super().__init__(
            name=name,
            command=entry.command,
            device=device,
            device_id=device_id,
            icon=entry.icon,
            translation_key=translation_key,
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
            domain="time",
        )

        self._attr_native_value = None
        self._entry = entry
        self._end = end
        self._byte_index = 0 if end else time_byte_index(entry.decode_type)
        # The other byte holds a time of its own; keep it when writing.
        self._keep_other_byte = entry.decode_type in TWO_TIME_DECODE_TYPES

    @property
    def native_value(self) -> time | None:
        """Return the native value of the time."""
        return self._attr_native_value

    def _apply_value(self, value_bytes: bytes) -> None:
        """Decode the time from its byte of the register."""
        if len(value_bytes) <= self._byte_index:
            _LOGGER.warning("Too little data for time %s: %s", self.name, value_bytes)
            return
        num = value_bytes[self._byte_index]
        self._attr_native_value = quarters_to_time(num)
        _LOGGER.debug(
            "Updated time %s: %s quarters -> %s",
            self.name,
            num,
            self._attr_native_value,
        )

    async def async_set_value(self, value: time) -> None:
        """Set new value for the time.

        Home Assistant's ``time.set_value`` service already validates and
        parses its ``time`` field into a ``datetime.time`` object before
        calling this method (see the service's voluptuous schema), so
        ``value`` arrives ready to use -- no string parsing needed.

        Note: ``TimeEntity``'s override point is ``async_set_value``
        (unlike ``NumberEntity``/``SelectEntity``, which use
        ``async_set_native_value``/``async_select_option``). A previous
        version of this method was named ``async_set_native_value``, which
        is not a method ``TimeEntity`` calls at all -- every write silently
        fell through to the base class's own unimplemented ``set_value``
        and raised ``NotImplementedError`` before ever reaching the device.
        """
        t_value = value

        num = time_to_quarters(t_value, is_end_time=self._end)
        _LOGGER.debug("Setting time %s to %s (%s quarters)", self.name, t_value, num)

        with raise_write_errors(self.name):
            await self._async_write_quarters(num)

        # Reflect what was actually written (quantized to a 15-minute
        # "quarter"), not the raw value passed in -- the device can only
        # store 15-minute increments, so e.g. 14:37 is stored as 14:30.
        # Round-tripping through quarters_to_time() keeps this in sync with
        # what the next poll would read back anyway.
        self._attr_native_value = quarters_to_time(num)
        self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        await self._async_after_write()

    async def _async_write_quarters(self, num: int) -> None:
        """Write ``num`` into this entity's byte of the 2-byte register.

        Registers whose time lives in the second byte (see time_byte_index)
        and the two-time registers keep the other byte as read from the
        device, e.g. the party end next to the party start; the others are
        written as ``[num, 0]``.
        """
        if self._byte_index == 0 and not self._keep_other_byte:
            payload = bytearray([num, 0])
        else:
            current = await async_read_parameter(self.hass, self._device, self._entry)
            payload = bytearray(current or b"") + bytearray(2)
            payload = payload[:2]
            payload[self._byte_index] = num
        await async_write_parameter(
            self.hass, self._device, self._entry, bytes(payload)
        )

    async def async_clear_value(self) -> None:
        """Clear this time back to the device's own "unset" state.

        Exposed as the ``thz.clear_value`` entity service (see
        async_setup_entry above) rather than through HA's built-in
        ``time.set_value`` service, since that service's schema requires a
        real ``datetime.time`` and has no way to express "no time set".
        """
        _LOGGER.debug("Clearing time %s to unset", self.name)

        # Same payload shape as async_set_value, with the sentinel value in
        # place of a real quarters count.
        with raise_write_errors(self.name):
            await self._async_write_quarters(TIME_VALUE_UNSET)

        self._attr_native_value = None
        self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        await self._async_after_write()


class THZScheduleTime(THZBaseEntity, TimeEntity):
    """Time entity for THZ schedule start/end times."""

    def __init__(
        self,
        name: str,
        base_name: str,
        entry: WriteParam,
        device: THZDevice,
        device_id: str,
        time_type: str,
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize a THZ schedule time entity.

        Args:
            name: The display name of the time entity (e.g., "programHC1_Mo_0 Start").
            base_name: The base register name for translation lookup
                (e.g., "programHC1_Mo_0").
                This is used to construct the translation key as
                base_translation_key + "_start" or "_end".
            entry: The write-map parameter.
            device: THZ device instance.
            device_id: The device identifier for linking to device.
            time_type: Either "start" or "end".
            entity_id_style: "default" or "fhem" (see base_entity.py). Applied
                using the full ``name`` (already including the " Start"/" End"
                suffix), so the FHEM-style entity_id naturally ends in
                "_start"/"_end" too.
            entity_visibility: "default"/"extended"/"all" (see base_entity.py).
            entity_id_prefix: Optional device alias prefix for "fhem"-style
                entity_ids (see base_entity.py).

        Example:
            For base_name="programHC1_Mo_0" and time_type="start", the translation key
            becomes "programhc1_mo_0_start" which resolves to
            "HC1 Program Monday 1 Start".
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
            command=entry.command,
            device=device,
            device_id=device_id,
            icon=entry.icon,
            translation_key=translation_key,
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
            domain="time",
        )

        self._time_type = time_type
        self._attr_native_value = None

        # Override unique_id to include time_type
        normalized_name = name.lower().replace(" ", "_")
        self._attr_unique_id = (
            f"thz_{device_id}_schedule_time_{self._command.lower()}_"
            f"{normalized_name}_{time_type}"
        )

    @property
    def native_value(self) -> time | None:
        """Return the native value of the time."""
        return self._attr_native_value

    def _poll_key(self) -> ReadKey:
        """Return the schedule's four data bytes; start and end share them.

        Schedules exist only as 4.x/5.x registers whose data bytes hold
        start and end together, so they are read and written whole here
        rather than as one parameter through parameter_io.
        """
        return self._command, SCHEDULE_OFFSET, SCHEDULE_LENGTH

    def _apply_value(self, value_bytes: bytes) -> None:
        """Decode the start (first byte) or end (second byte) time."""
        # FHEM 7prog: start at nibble offset 8 (byte 4), end at nibble
        # offset 10 (byte 5); the read starts at byte 4.
        if len(value_bytes) < 2:
            _LOGGER.warning(
                "No data received for schedule time %s (%s), keeping previous value",
                self.name,
                self._time_type,
            )
            return

        num = value_bytes[0] if self._time_type == "start" else value_bytes[1]

        self._attr_native_value = quarters_to_time(num)
        _LOGGER.debug(
            "Updated schedule time %s (%s): %s quarters -> %s",
            self.name,
            self._time_type,
            num,
            self._attr_native_value,
        )

    async def async_set_value(self, value: time) -> None:
        """Set new value for the schedule time.

        Home Assistant's ``time.set_value`` service already validates and
        parses its ``time`` field into a ``datetime.time`` object before
        calling this method, so ``value`` arrives ready to use -- no string
        parsing needed. See ``THZTime.async_set_value`` above for why this
        method must be named ``async_set_value`` (not
        ``async_set_native_value``): that's the override point
        ``TimeEntity`` actually calls, and the previous name was silently
        never invoked at all, raising ``NotImplementedError`` on every
        write attempt before ever reaching the device.
        """
        t_value = value

        new_num = time_to_quarters(t_value, is_end_time=(self._time_type == "end"))
        _LOGGER.debug(
            "Setting schedule time %s (%s) to %s (%s quarters)",
            self.name,
            self._time_type,
            t_value,
            new_num,
        )

        with raise_write_errors(self.name):
            # Read the current schedule data (4 bytes total)
            current_bytes = await self._device.async_execute(
                self._device.read_value,
                bytes.fromhex(self._command),
                "get",
                SCHEDULE_OFFSET,
                SCHEDULE_LENGTH,
            )

            # Modify only the relevant byte (start or end time)
            schedule_bytes = bytearray(current_bytes)
            if self._time_type == "start":
                schedule_bytes[0] = new_num
            else:  # "end"
                schedule_bytes[1] = new_num

            # Write the modified schedule back
            await self._device.async_execute(
                self._device.write_value,
                bytes.fromhex(self._command),
                bytes(schedule_bytes),
            )

        # Reflect what was actually written (quantized to a 15-minute
        # "quarter", with the same end-of-day 96 -> 00:00 handling
        # _apply_value applies), not the raw value passed in.
        self._attr_native_value = quarters_to_time(new_num)
        self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        await self._async_after_write()

    async def async_clear_value(self) -> None:
        """Clear this schedule start/end time to the device's own "unset" state.

        Exposed as the ``thz.clear_value`` entity service -- see
        ``THZTime.async_clear_value`` for why this can't go through HA's
        built-in ``time.set_value`` service.
        """
        _LOGGER.debug(
            "Clearing schedule time %s (%s) to unset", self.name, self._time_type
        )

        # Read the current schedule data (4 bytes total) so only the
        # relevant byte (start or end) is touched, same as async_set_value.
        with raise_write_errors(self.name):
            current_bytes = await self._device.async_execute(
                self._device.read_value,
                bytes.fromhex(self._command),
                "get",
                SCHEDULE_OFFSET,
                SCHEDULE_LENGTH,
            )

            schedule_bytes = bytearray(current_bytes)
            if self._time_type == "start":
                schedule_bytes[0] = TIME_VALUE_UNSET
            else:  # "end"
                schedule_bytes[1] = TIME_VALUE_UNSET

            await self._device.async_execute(
                self._device.write_value,
                bytes.fromhex(self._command),
                bytes(schedule_bytes),
            )

        self._attr_native_value = None
        self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        await self._async_after_write()

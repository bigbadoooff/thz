# custom_components/thz/sensor.py
"""THZ Sensor Platform for Home Assistant.

This module provides the sensor platform for the THZ integration in Home Assistant.
It defines the setup routine for sensor entities, decoding logic for raw sensor
data, and a generic sensor entity class for representing THZ device sensors.

Key Components:
    - async_setup_entry: Asynchronous setup for THZ sensor entities.
    - decode_value: Utility function to decode raw bytes from the device.
    - normalize_entry: Helper to standardize sensor entry definitions.
    - THZGenericSensor: Entity class representing a generic THZ sensor.

The integration reads register mappings from the THZ device, decodes sensor
values according to their metadata, and exposes them as HA sensor entities.
"""
from __future__ import annotations

import logging
import struct

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, should_hide_entity_by_default
from .register_maps.register_map_manager import RegisterMapManager
from .sensor_meta import SENSOR_META

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up THZ sensor entities from a config entry.

    This function initializes sensor entities for the THZ integration by
    retrieving register mappings, creating sensor metadata, and adding
    the entities to Home Assistant.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry for this integration.
        async_add_entities: Callback to add entities to Home Assistant.

    Returns:
        None
    """
    # Get data from hass.data
    register_manager: RegisterMapManager = hass.data[DOMAIN]["register_manager"]
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators = entry_data["coordinators"]
    device_id = hass.data[DOMAIN]["device_id"]

    # Create sensors
    sensors = []
    seen_sensor_names = set()  # Track sensor names to avoid duplicates
    all_registers = register_manager.get_all_registers()
    for block, entries in all_registers.items():
        # Get the coordinator for this block
        coordinator = coordinators.get(block)
        if coordinator is None:
            _LOGGER.warning(
                "No coordinator found for block %s, skipping sensors", block
            )
            continue

        block_hex = block.removeprefix("pxx")  # Remove "pxx" prefix
        block_bytes = bytes.fromhex(block_hex)
        for name, offset, length, decode_type, factor in entries:
            # Strip whitespace and trailing colons from sensor name
            sensor_name = name.strip().rstrip(':')

            # Skip duplicate sensor names - only create the first occurrence
            if sensor_name in seen_sensor_names:
                _LOGGER.debug(
                    "Skipping duplicate sensor '%s' in block %s (already created)",
                    sensor_name,
                    block,
                )
                continue

            seen_sensor_names.add(sensor_name)

            meta = SENSOR_META.get(sensor_name, {})
            entry = {
                "name": sensor_name,
                "offset": offset // 2,  # Register offset in bytes
                "length": (length + 1)
                // 2,  # Register length in bytes; +1 to always have >=1 byte
                "decode": decode_type,
                "factor": factor,
                "unit": meta.get("unit"),
                "device_class": meta.get("device_class"),
                "state_class": meta.get("state_class"),
                "icon": meta.get("icon"),
                "translation_key": meta.get("translation_key"),
            }
            sensors.append(
                THZGenericSensor(
                    coordinator, entry=entry, block=block_bytes, device_id=device_id
                )
            )
    async_add_entities(sensors, True)


def decode_value(
    raw: bytes, decode_type: str, factor: float = 1.0
) -> int | float | bool | str:
    """Decode a raw byte value according to the specified decode type.

    Args:
        raw: The raw bytes to decode.
        decode_type: The type of decoding to apply. Supported types:
            - "hex2int": Signed integer divided by factor.
            - "hex": Unsigned integer.
            - "bitX": Extracts bit number X (e.g., "bit3").
            - "nbitX": Negation of bit X (e.g., "nbit2").
            - "esp_mant": Mantissa and exponent representation.
            - Any other: Returns hexadecimal representation.
        factor: The divisor for "hex2int" decoding. Defaults to 1.0.

    Returns:
        The decoded value (int, float, bool, or str).
    """
    if decode_type == "hex2int":
        # Only use 2 bytes; register indicates 4 chars in hex string
        return int.from_bytes(raw, byteorder="big", signed=True) / factor
    if decode_type == "hex":
        # Only use 2 bytes; register indicates 4 chars in hex string
        return int.from_bytes(raw, byteorder="big")
    if decode_type.startswith("bit"):
        bitnum = int(decode_type[3:])
        return bool((raw[0] >> bitnum) & 0x01)
    if decode_type.startswith("nbit"):
        bitnum = int(decode_type[4:])
        return not bool((raw[0] >> bitnum) & 0x01)
    if decode_type == "esp_mant":
        # FHEM code reverses bytes and unpacks, equivalent to big-endian
        mant = struct.unpack('>f', raw)[0]
        return round(mant, 3)

    return raw.hex()


def normalize_entry(entry):
    """Normalize a sensor entry to a standard dictionary format.

    This function accepts either a tuple or a dictionary representing a
    sensor entry. If a tuple is provided, it is unpacked into a dictionary
    with predefined keys. If a dictionary is provided, it is returned as-is.

    Args:
        entry: The sensor entry to normalize. If a tuple, it should contain
            (name, offset, length, decode, factor).

    Returns:
        A dictionary containing the normalized sensor entry.

    Raises:
        ValueError: If the entry is not a tuple or dictionary.
    """
    if isinstance(entry, tuple):
        name, offset, length, decode, factor = entry
        return {
            "name": name.strip(),
            "offset": offset,
            "length": length,
            "decode": decode,
            "factor": factor,
            "unit": None,
            "device_class": None,
            "state_class": None,
            "icon": None,
            "translation_key": None,
        }
    if isinstance(entry, dict):
        return entry

    raise ValueError("Unsupported sensor entry format.")


class THZGenericSensor(CoordinatorEntity, SensorEntity):
    """Represents a generic sensor entity for the THZ integration.

    This class is responsible for managing the state and properties of a
    sensor associated with a THZ device. It uses a coordinator to poll data
    from the device at configurable intervals, then decodes the relevant
    bytes for this sensor.

    Attributes:
        _block: Block identifier associated with the sensor.
        _offset: Offset within the block for sensor data.
        _length: Length of the sensor data in bytes.
        _decode_type: Type used to decode the sensor data.
        _factor: Factor to apply to the decoded value.
        _entity_name: Internal name used for logging and unique_id.
        _unit: Unit of measurement for the sensor.
        _device_class: Device class for the sensor.
        _icon: Icon representing the sensor.

    Note:
        Translation is handled via _attr_translation_key when available.
        Setting _attr_name blocks translation, so we only set it when
        no translation is available.
    """

    def __init__(self, coordinator, entry, block, device_id) -> None:
        """Initialize a sensor instance with the provided configuration.

        Args:
            coordinator: The DataUpdateCoordinator for this sensor's block.
            entry: The configuration entry dict for the sensor.
            block: The block associated with the sensor.
            device_id: The unique device identifier.

        Note:
            When translation_key is available, only _attr_translation_key is set.
            When no translation is available, _attr_name is set as fallback.
            This is required because setting _attr_name blocks HA's translation.
        """
        super().__init__(coordinator)

        e = normalize_entry(entry)
        self._block = block
        self._offset = e["offset"]
        self._length = e["length"]
        self._decode_type = e["decode"]
        self._factor = e["factor"]
        self._unit = e.get("unit")
        self._device_class = e.get("device_class")
        self._state_class = e.get("state_class")
        self._icon = e.get("icon")
        self._device_id = device_id

        # Store the name for later use in unique_id and visibility checks
        self._entity_name = e["name"]

        # Handle translation: don't set _attr_name when translation_key exists
        # Setting _attr_name blocks HA's translation lookup
        translation_key = e.get("translation_key")
        if translation_key is not None:
            self._attr_translation_key = translation_key
            self._attr_has_entity_name = True
        else:
            # No translation available: use name as fallback
            self._attr_name = e["name"]

        # Set default visibility based on entity naming conventions
        self._attr_entity_registry_enabled_default = (
            not should_hide_entity_by_default(self._entity_name)
        )



    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the registry."""
        return self._attr_entity_registry_enabled_default

    @property
    def native_value(self) -> StateType | int | float | bool | str | None:
        """Return the native value of the sensor.

        Returns:
        -------
        StateType | int | float | bool | str | None
            The native value of the sensor.
        """
        if self.coordinator.data is None:
            return None

        try:
            payload = self.coordinator.data
            # Validate payload length before slicing
            if len(payload) < self._offset + self._length:
                _LOGGER.warning(
                    "Payload too short for sensor %s: "
                    "expected at least %d bytes, got %d",
                    self._entity_name,
                    self._offset + self._length,
                    len(payload),
                )
                return None
            raw_bytes = payload[self._offset : self._offset + self._length]
            return decode_value(raw_bytes, self._decode_type, self._factor)
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error(
                "Error decoding sensor %s: %s", self._entity_name, err, exc_info=True
            )
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the native unit of measurement for this sensor.

        This property provides the unit in which the sensor's value is
        measured natively, such as "°C" for temperature or "%" for humidity.

        Returns:
            The native unit of measurement, or None if not set.
        """
        return self._unit

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class of the sensor.

        Returns:
            The device class, or None if not set.
        """
        return self._device_class

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return the state class of the sensor.

        Returns:
            The state class for long-term statistics, or None if not set.
        """
        return self._state_class

    @property
    def icon(self) -> str | None:
        """Return the icon to use in the frontend.

        Returns:
            The icon string, or None if no icon is set.
        """
        return self._icon

    @property
    def unique_id(self) -> str | None:
        """Return a unique identifier for the sensor entity.

        Returns:
            A string representing the unique ID of the sensor.
        """
        entity_key = self._entity_name.lower().replace(' ', '_')
        return f"thz_{self._block}_{self._offset}_{entity_key}"

    @property
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

"""THZ Binary Sensor Platform for Home Assistant.

This module provides the binary sensor platform for the THZ integration.
It creates BinarySensorEntity instances for all register map entries that
use bit-decoded types (``bit*`` / ``nbit*``), such as compressor state,
pump activity, filter alarms, valve positions, and similar on/off signals.

These were previously exposed as regular SensorEntity values (True/False).
The binary_sensor platform gives them proper HA device classes and enables
native automations and notifications (e.g., filter-change reminders).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ENTITY_ID_STYLE_DEFAULT,
    ENTITY_VISIBILITY_DEFAULT,
    should_hide_entity,
)
from .entity_id_style import resolve_suggested_object_id
from .register_maps.register_map_manager import RegisterMapManager
from .value_codec import decode_raw_value

_LOGGER = logging.getLogger(__name__)


def _is_bit_decode_type(decode_type: str) -> bool:
    """Return True if the decode type extracts a single bit (boolean value)."""
    return decode_type.startswith("bit") or decode_type.startswith("nbit")


def _get_device_class(name: str) -> BinarySensorDeviceClass | None:
    """Return the appropriate BinarySensorDeviceClass for the given entity name.

    Args:
        name: The internal entity name (e.g. "compressor", "filterBoth").

    Returns:
        A BinarySensorDeviceClass value, or None for generic on/off sensors.
    """
    n = name.lower()
    # Running: compressor, pumps
    if any(x in n for x in ["pump", "compressor"]):
        return BinarySensorDeviceClass.RUNNING
    # Problem: filters, service flag
    if any(x in n for x in ["filter", "service"]):
        return BinarySensorDeviceClass.PROBLEM
    # Window contact
    if "window" in n:
        return BinarySensorDeviceClass.WINDOW
    # Opening: valves and mixer
    if any(x in n for x in ["valve", "mixer"]):
        return BinarySensorDeviceClass.OPENING
    # Heat: active heating signals
    if "heating" in n:
        return BinarySensorDeviceClass.HEAT
    # Cold: active cooling or defrost
    if any(x in n for x in ["cooling", "defrost"]):
        return BinarySensorDeviceClass.COLD
    # Default: no device class (shows generic on/off)
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up THZ binary sensor entities from a config entry.

    Iterates all register map entries for the current firmware and creates
    one THZBinarySensor per entry whose decode type is ``bit*`` or ``nbit*``.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry for this integration.
        async_add_entities: Callback to add entities to Home Assistant.
    """
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    register_manager: RegisterMapManager = entry_data["register_manager"]
    coordinators = entry_data["coordinators"]
    device_id = entry_data["device_id"]
    entity_id_style = entry_data.get("entity_id_style", ENTITY_ID_STYLE_DEFAULT)
    entity_visibility = entry_data.get("entity_visibility", ENTITY_VISIBILITY_DEFAULT)
    entity_id_prefix = entry_data.get("entity_id_prefix")

    entities: list[THZBinarySensor] = []
    seen_sensor_names: set[str] = set()
    all_registers = register_manager.get_all_registers()

    for block, entries in all_registers.items():
        coordinator = coordinators.get(block)
        if coordinator is None:
            _LOGGER.warning(
                "No coordinator found for block %s, skipping binary sensors", block
            )
            continue

        block_hex = block.removeprefix("pxx")
        block_bytes = bytes.fromhex(block_hex)

        for entry_tuple in entries:
            name, offset, length, decode_type, factor = entry_tuple[:5]
            tuple_meta = entry_tuple[5] if len(entry_tuple) > 5 else {}

            # Only handle bit-decoded entries
            if not _is_bit_decode_type(decode_type):
                continue

            sensor_name = name.strip().rstrip(":")

            # Skip duplicate sensor names
            if sensor_name in seen_sensor_names:
                _LOGGER.debug(
                    "Skipping duplicate binary sensor '%s' in block %s",
                    sensor_name,
                    block,
                )
                continue
            seen_sensor_names.add(sensor_name)

            # Apply nibble-offset adjustment (same logic as sensor.py).
            # Register offsets are nibble positions (4-bit units); two nibbles
            # share one byte.  An even nibble offset means the value lives in
            # the high nibble, so bit numbers must be shifted up by 4.
            effective_decode = decode_type
            if length == 1 and offset % 2 == 0:
                if decode_type.startswith("bit") and not decode_type.startswith("nbit"):
                    bitnum = int(decode_type[3:])
                    effective_decode = f"bit{bitnum + 4}"
                elif decode_type.startswith("nbit"):
                    bitnum = int(decode_type[4:])
                    effective_decode = f"nbit{bitnum + 4}"

            entry = {
                "name": sensor_name,
                "offset": offset // 2,
                "length": (length + 1) // 2,
                "decode": effective_decode,
                "icon": tuple_meta.get("icon"),
                "translation_key": tuple_meta.get("translation_key"),
            }
            entities.append(
                THZBinarySensor(
                    coordinator,
                    entry=entry,
                    block=block_bytes,
                    device_id=device_id,
                    entity_id_style=entity_id_style,
                    entity_visibility=entity_visibility,
                    entity_id_prefix=entity_id_prefix,
                )
            )

    _LOGGER.info("Created %d binary sensor entities", len(entities))
    async_add_entities(entities, True)


class THZBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Represents a binary (on/off) sensor entity for the THZ integration.

    Reads a single bit from a coordinator-provided register block and
    exposes it as a Home Assistant BinarySensorEntity with an appropriate
    device class where possible.

    Attributes:
        _block: Register block bytes identifying the data source.
        _offset: Byte offset within the block payload.
        _length: Number of bytes to read (always 1 for bit sensors).
        _decode_type: Effective decode type after nibble-offset adjustment.
        _entity_name: Internal name used for unique_id and visibility checks.
    """

    def __init__(
        self,
        coordinator: Any,
        entry: dict[str, Any],
        block: bytes,
        device_id: str,
        entity_id_style: str = ENTITY_ID_STYLE_DEFAULT,
        entity_visibility: str = ENTITY_VISIBILITY_DEFAULT,
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize a THZBinarySensor.

        Args:
            coordinator: The DataUpdateCoordinator providing block data.
            entry: Dict with keys: name, offset, length, decode, icon,
                translation_key.
            block: Block address bytes (hex) identifying the register.
            device_id: Device identifier for linking this entity to the device.
            entity_id_style: "default" or "fhem" (see entity_id_style.py).
            entity_visibility: "default"/"extended"/"all" (see const.py's
                should_hide_entity()).
            entity_id_prefix: Optional device alias prefix for "fhem"-style
                entity_ids (see entity_id_style.py).
        """
        super().__init__(coordinator)

        self._block = block
        self._offset = entry["offset"]
        self._length = entry["length"]
        self._decode_type = entry["decode"]
        self._icon = entry.get("icon")
        self._device_id = device_id
        self._entity_name = entry["name"]

        # Translation: set only translation_key when available so HA can look
        # up the name; setting _attr_name would block translation lookup.
        translation_key = entry.get("translation_key")
        if translation_key is not None:
            self._attr_translation_key = translation_key
            self._attr_has_entity_name = True
        else:
            self._attr_name = entry["name"]

        # Device class improves UI representation and enables automations
        self._attr_device_class = _get_device_class(self._entity_name)

        # Visibility: hide advanced/technical entities per the configured tier
        self._attr_entity_registry_enabled_default = (
            not should_hide_entity(self._entity_name, entity_visibility)
        )

        # Entity-ID naming style: independent of translation_key/unique_id.
        # NOTE: Home Assistant has no "_attr_suggested_object_id" hook --
        # Entity.suggested_object_id is a read-only @property, never backed by
        # an "_attr_*" instance attribute. Setting self.entity_id directly
        # (before this entity is added to hass) is the actually-supported way
        # to seed a custom initial object_id -- see base_entity.py's
        # THZBaseEntity.__init__ for the full explanation.
        suggested_object_id = resolve_suggested_object_id(
            self._entity_name, entity_id_style, device_prefix=entity_id_prefix
        )
        if suggested_object_id:
            self.entity_id = f"binary_sensor.{suggested_object_id}"

    @property
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is active (bit is set).

        Returns:
            True/False for on/off state, or None if data is unavailable.
        """
        if self.coordinator.data is None:
            return None

        try:
            payload = self.coordinator.data
            if len(payload) < self._offset + self._length:
                _LOGGER.warning(
                    "Payload too short for binary sensor %s: "
                    "expected at least %d bytes, got %d",
                    self._entity_name,
                    self._offset + self._length,
                    len(payload),
                )
                return None
            raw_bytes = payload[self._offset : self._offset + self._length]
            return bool(decode_raw_value(raw_bytes, self._decode_type))
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error(
                "Error decoding binary sensor %s: %s",
                self._entity_name,
                err,
                exc_info=True,
            )
            return None

    @property
    def icon(self) -> str | None:
        """Return the icon to use in the frontend."""
        return self._icon

    @property
    def unique_id(self) -> str | None:
        """Return a unique identifier for this entity."""
        name_slug = self._entity_name.lower().replace(" ", "_")
        return f"thz_bin_{self._block.hex()}_{self._offset}_{name_slug}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return register metadata as extra state attributes."""
        return {
            "register_block": "pxx" + self._block.hex().upper(),
            "register_offset": self._offset,
            "register_length": self._length,
            "register_decode_type": self._decode_type,
        }

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information to link this entity to the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

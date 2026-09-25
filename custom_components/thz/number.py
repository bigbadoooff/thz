"""THZ Number Entity Platform."""

from __future__ import annotations

import logging
from typing import cast

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZParameterEntity
from .entity_translations import get_translation_key
from .parameter_io import async_write_parameter, parameter_length
from .platform_setup import async_setup_write_platform
from .register_maps.model import WriteParam
from .thz_device import THZDevice
from .value_codec import THZValueCodec
from .write_errors import raise_write_errors

_LOGGER = logging.getLogger(__name__)

# Values come from the parameter poller or a block coordinator; writes go
# to the device directly, one at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up THZ number entities from config entry."""
    await async_setup_write_platform(
        hass, config_entry, async_add_entities, THZNumber, "number"
    )


class THZNumber(THZParameterEntity, NumberEntity):
    """Representation of a THZ Number entity."""

    def __init__(
        self,
        name: str,
        entry: WriteParam,
        device: THZDevice,
        device_id: str,
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize a THZ number entity.

        Args:
            name: The name of the number entity.
            entry: The write-map parameter.
            device: The device instance this entity belongs to.
            device_id: The device identifier for linking to device.
            entity_id_style: "default" or "fhem" (see base_entity.py).
            entity_visibility: "default"/"extended"/"all" (see base_entity.py).
            entity_id_prefix: Optional device alias prefix for "fhem"-style
                entity_ids (see base_entity.py).
        """
        # Initialize base class with common properties
        super().__init__(
            name=name,
            command=entry.command,
            device=device,
            device_id=device_id,
            icon=entry.icon,
            translation_key=get_translation_key(name),
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
            domain="number",
        )

        # Number-specific attributes
        min_value, max_value = entry.min_value, entry.max_value
        self._attr_native_min_value = min_value if min_value is not None else 0.0
        self._attr_native_max_value = max_value if max_value is not None else 100.0
        self._attr_native_step = entry.step if entry.step is not None else 1.0
        self._attr_native_unit_of_measurement = entry.unit
        # The map's text ("temperature", or "" for none) as Home Assistant's
        # device class string.
        self._attr_device_class = cast("NumberDeviceClass | None", entry.device_class)
        self._attr_mode = NumberMode.BOX
        self._decode_type = entry.decode_type
        self._attr_native_value = None

        # Reads/writes go through parameter_io, which handles both direct
        # registers and 2xx block parameters (entry.block).
        self._entry = entry
        self._read_length = parameter_length(entry)

    @property
    def native_value(self) -> float | None:
        """Return the native value of the number."""
        return self._attr_native_value

    def _apply_value(self, value_bytes: bytes) -> None:
        """Decode the parameter's bytes into the number."""
        _LOGGER.debug("Received bytes for %s: %s", self.name, value_bytes.hex())
        try:
            value = THZValueCodec.decode_number(
                value_bytes,
                self._attr_native_step,
                self._decode_type,
                self._entry.signed,
            )
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error("Error decoding number %s: %s", self.name, err, exc_info=True)
            return  # keep the previous value
        _LOGGER.debug("Decoded value for %s: %s", self.name, value)
        self._attr_native_value = value

    async def async_set_native_value(self, value: float) -> None:
        """Set new value for the number."""
        _LOGGER.debug("Setting value for %s to %s", self.name, value)

        with raise_write_errors(self.name):
            # Pass the register length so 2xx block parameters (which may be
            # 1 or 4 bytes) are encoded correctly.
            value_bytes = THZValueCodec.encode_number(
                value,
                self._attr_native_step,
                self._decode_type,
                self._read_length,
            )
            await async_write_parameter(self._device, self._entry, value_bytes)

        self._attr_native_value = value
        self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        await self._async_after_write()

"""THZ Number Entity Platform."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZBaseEntity
from .entity_translations import get_translation_key
from .const import (
    WRITE_REGISTER_OFFSET,
    WRITE_REGISTER_LENGTH,
)
from .platform_setup import async_setup_write_platform
from .thz_device import THZDevice
from .value_codec import THZValueCodec

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up THZ number entities from config entry."""
    await async_setup_write_platform(
        hass, config_entry, async_add_entities, THZNumber, "number"
    )


class THZNumber(THZBaseEntity, NumberEntity):
    """Representation of a THZ Number entity."""

    def __init__(
        self,
        name: str,
        entry: dict,
        device: THZDevice,
        device_id: str,
        scan_interval: int | None = None,
    ) -> None:
        """Initialize a THZ number entity.

        Args:
            name: The name of the number entity.
            entry: The register entry dict containing configuration.
            device: The device instance this entity belongs to.
            device_id: The device identifier for linking to device.
            scan_interval: Poll interval in seconds for periodic updates.
        """
        # Initialize base class with common properties
        super().__init__(
            name=name,
            command=entry["command"],
            device=device,
            device_id=device_id,
            icon=entry.get("icon"),
            scan_interval=scan_interval,
            translation_key=get_translation_key(name),
        )

        # Number-specific attributes
        min_value = entry["min"]
        max_value = entry["max"]
        step = entry.get("step", 1)

        self._attr_native_min_value = float(min_value) if min_value != "" else 0.0
        self._attr_native_max_value = float(max_value) if max_value != "" else 100.0
        self._attr_native_step = float(step) if step != "" else 1.0
        self._attr_native_unit_of_measurement = entry.get("unit", "")
        self._attr_device_class = entry.get("device_class")
        self._attr_mode = NumberMode.BOX  # Use box input instead of slider
        self._decode_type = entry["decode_type"]
        self._attr_native_value = None

    @property
    def native_value(self) -> float | None:
        """Return the native value of the number."""
        return self._attr_native_value

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(
                self._device.read_value,
                bytes.fromhex(self._command),
                "get",
                WRITE_REGISTER_OFFSET,
                WRITE_REGISTER_LENGTH,
            )

        # Validate that we received data
        if not value_bytes:
            _LOGGER.warning(
                "No data received for number %s, keeping previous value", self.name
            )
            return

        _LOGGER.debug("Received bytes for %s: %s", self.name, value_bytes.hex())

        try:
            # Use centralized codec for decoding
            value = THZValueCodec.decode_number(
                value_bytes,
                self._attr_native_step,
                self._decode_type
            )
            _LOGGER.debug("Decoded value for %s: %s", self.name, value)
            self._attr_native_value = value
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error(
                "Error decoding number %s: %s", self.name, err, exc_info=True
            )
            # Keep previous value on error

    async def async_set_native_value(self, value: float) -> None:
        """Set new value for the number."""
        _LOGGER.debug("Setting value for %s to %s", self.name, value)

        try:
            # Use centralized codec for encoding
            value_bytes = THZValueCodec.encode_number(
                value,
                self._attr_native_step,
                self._decode_type
            )

            async with self._device.lock:
                await self.hass.async_add_executor_job(
                    self._device.write_value,
                    bytes.fromhex(self._command),
                    value_bytes,
                )
                # Short pause to ensure the device is ready
                await asyncio.sleep(0.01)

            self._attr_native_value = value
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error encoding number %s value %s: %s",
                self.name, value, err, exc_info=True
            )

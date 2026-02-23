"""Select entity for THZ integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.select import SelectEntity
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
from .value_maps import SELECT_MAP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create THZSelect entities."""
    await async_setup_write_platform(
        hass, config_entry, async_add_entities, THZSelect, "select"
    )




class THZSelect(THZBaseEntity, SelectEntity):
    """Representation of a THZ Select entity."""

    def __init__(
        self,
        name: str,
        entry: dict,
        device: THZDevice,
        device_id: str,
    ) -> None:
        """Initialize a THZ select entity.

        Args:
            name: The name of the select entity.
            entry: The register entry dict containing configuration.
            device: The device instance this select entity belongs to.
            device_id: The device identifier for linking to device.
        """
        # Initialize base class with common properties
        super().__init__(
            name=name,
            command=entry.get("command"),
            device=device,
            device_id=device_id,
            icon=entry.get("icon"),
            translation_key=get_translation_key(name),
        )

        # Select-specific attributes
        self._decode_type = entry.get("decode_type")

        # Set available options based on decode_type
        if self._decode_type and self._decode_type in SELECT_MAP:
            self._attr_options = list(SELECT_MAP[self._decode_type].values())
            _LOGGER.debug(
                "Options for %s (%s): %s", name, self._decode_type, self._attr_options
            )
        else:
            self._attr_options = []
            _LOGGER.warning(
                "No options found for select %s with decode_type %s",
                name, self._decode_type
            )

        self._attr_current_option = None

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        return self._attr_current_option

    async def async_update(self) -> None:
        """Fetch new state data for the select."""
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
                "No data received for select %s, keeping previous value", self.name
            )
            return

        _LOGGER.debug(
            "Received bytes for %s: %s",
            self.name,
            value_bytes.hex()
        )

        try:
            # Use centralized codec for decoding
            option = THZValueCodec.decode_select(value_bytes, self._decode_type)
            if option:
                self._attr_current_option = option
                _LOGGER.debug(
                    "Decoded option for %s: %s", self.name, option
                )
            else:
                _LOGGER.warning(
                    "Could not map value to option for %s", self.name
                )
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error(
                "Error decoding select %s: %s", self.name, err, exc_info=True
            )
            # Keep previous value on error

    async def async_select_option(self, option: str) -> None:
        """Set the selected option."""
        _LOGGER.debug("Setting %s to option %s", self.name, option)

        try:
            # Use centralized codec for encoding
            value_bytes = THZValueCodec.encode_select(option, self._decode_type)
            _LOGGER.debug("Encoded value bytes: %s", value_bytes.hex())

            async with self._device.lock:
                await self.hass.async_add_executor_job(
                    self._device.write_value,
                    bytes.fromhex(self._command),
                    value_bytes,
                )
                # Short pause to ensure the device is ready
                await asyncio.sleep(0.01)

            self._attr_current_option = option
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error encoding select %s to option %s: %s",
                self.name, option, err, exc_info=True
            )

"""THZ Switch Entity Platform."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up switch entities for the THZ integration."""
    await async_setup_write_platform(
        hass, config_entry, async_add_entities, THZSwitch, "switch"
    )




class THZSwitch(THZBaseEntity, SwitchEntity):
    """Representation of a THZ Switch entity."""

    def __init__(
        self,
        name: str,
        entry: dict,
        device: THZDevice,
        device_id: str,
        scan_interval: int | None = None,
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize a THZ switch entity.

        Args:
            name: The name of the switch.
            entry: The register entry dict containing configuration.
            device: The device instance this switch is associated with.
            device_id: The device identifier for linking to device.
            scan_interval: The scan interval in seconds for polling updates.
            entity_id_style: "default" or "fhem" (see base_entity.py).
            entity_visibility: "default"/"extended"/"all" (see base_entity.py).
            entity_id_prefix: Optional device alias prefix for "fhem"-style
                entity_ids (see base_entity.py).
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
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
            domain="switch",
        )

        # Switch-specific attributes
        self._is_on = False

    @property
    def is_on(self) -> bool | None:
        """Return whether the switch is currently on."""
        return self._is_on

    async def async_update(self) -> None:
        """Update the switch state by reading the current value from the device."""
        _LOGGER.debug(
            "Updating switch %s with command %s", self.name, self._command
        )

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
                "No data received for switch %s, keeping previous value", self.name
            )
            return

        _LOGGER.debug("Received bytes for %s: %s", self.name, value_bytes.hex())

        try:
            # Use centralized codec for decoding
            self._is_on = THZValueCodec.decode_switch(value_bytes)
            _LOGGER.debug("Decoded switch state for %s: %s", self.name, self._is_on)
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error(
                "Error decoding switch %s: %s", self.name, err, exc_info=True
            )
            # Keep previous value on error

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch by sending a command to the device."""
        _LOGGER.debug("Turning on switch %s", self.name)

        try:
            # Use centralized codec for encoding
            value_bytes = THZValueCodec.encode_switch(True)

            async with self._device.lock:
                await self.hass.async_add_executor_job(
                    self._device.write_value,
                    bytes.fromhex(self._command),
                    value_bytes,
                )

            self._is_on = True
            self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error encoding switch %s to turn on: %s",
                self.name, err, exc_info=True
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch by sending a command to the device."""
        _LOGGER.debug("Turning off switch %s", self.name)

        try:
            # Use centralized codec for encoding
            value_bytes = THZValueCodec.encode_switch(False)

            async with self._device.lock:
                await self.hass.async_add_executor_job(
                    self._device.write_value,
                    bytes.fromhex(self._command),
                    value_bytes,
                )

            self._is_on = False
            self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error encoding switch %s to turn off: %s",
                self.name, err, exc_info=True
            )

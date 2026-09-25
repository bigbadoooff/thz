"""THZ Switch Entity Platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZParameterEntity
from .entity_translations import get_translation_key
from .parameter_io import async_write_parameter
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
    """Set up switch entities for the THZ integration."""
    await async_setup_write_platform(
        hass, config_entry, async_add_entities, THZSwitch, "switch"
    )


class THZSwitch(THZParameterEntity, SwitchEntity):
    """Representation of a THZ Switch entity."""

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
        """Initialize a THZ switch entity.

        Args:
            name: The name of the switch.
            entry: The write-map parameter.
            device: The device instance this switch is associated with.
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
            domain="switch",
        )

        # Switch-specific attributes
        self._entry = entry
        self._is_on = False

    @property
    def is_on(self) -> bool | None:
        """Return whether the switch is currently on."""
        return self._is_on

    def _apply_value(self, value_bytes: bytes) -> None:
        """Decode the parameter's bytes into the switch state."""
        _LOGGER.debug("Received bytes for %s: %s", self.name, value_bytes.hex())
        try:
            self._is_on = THZValueCodec.decode_switch(value_bytes)
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error("Error decoding switch %s: %s", self.name, err, exc_info=True)
            return  # keep the previous value
        _LOGGER.debug("Decoded switch state for %s: %s", self.name, self._is_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch by sending a command to the device."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch by sending a command to the device."""
        await self._async_set(False)

    async def _async_set(self, is_on: bool) -> None:
        """Write the switch state; raise HomeAssistantError if that fails."""
        _LOGGER.debug("Turning %s switch %s", "on" if is_on else "off", self.name)
        with raise_write_errors(self.name):
            await async_write_parameter(
                self.hass,
                self._device,
                self._entry,
                THZValueCodec.encode_switch(is_on),
            )

        self._is_on = is_on
        self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        await self._async_after_write()

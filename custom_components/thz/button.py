"""THZ Button Entity Platform.

This module provides the button platform for the THZ integration.
Button entities represent one-shot write commands that can be triggered
from the Home Assistant UI or automations.

Currently exposed buttons:
  - zResetLast10errors: clears the on-device fault log (all firmware).
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZBaseEntity
from .const import DOMAIN
from .entity_translations import get_translation_key
from .exceptions import DEVICE_ERRORS
from .parameter_io import async_write_parameter
from .platform_setup import async_setup_write_platform
from .register_maps.model import WriteParam
from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# Buttons write to the device directly (no coordinator, no polling); limit
# to one in-flight press at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up THZ button entities from a config entry."""
    await async_setup_write_platform(
        hass, config_entry, async_add_entities, THZButton, "button"
    )


class THZButton(THZBaseEntity, ButtonEntity):
    """Representation of a THZ Button entity.

    A button entity sends a fixed write command to the device when pressed.
    There is no readable state; the button simply triggers a one-shot action.
    """

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
        """Initialize a THZ button entity.

        Args:
            name: The name of the button.
            entry: The write-map parameter.
            device: The device instance this button communicates with.
            device_id: The device identifier for registry linking.
            entity_id_style: "default" or "fhem" (see base_entity.py).
            entity_visibility: "default"/"extended"/"all" (see base_entity.py).
            entity_id_prefix: Optional device alias prefix for "fhem"-style
                entity_ids (see base_entity.py).
        """
        super().__init__(
            name=name,
            command=entry.command,
            device=device,
            device_id=device_id,
            icon=entry.icon or "mdi:gesture-tap-button",
            translation_key=get_translation_key(name),
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
            domain="button",
        )
        self._entry = entry

    async def async_update(self) -> None:
        """Buttons have no readable state (and no _poll_key: nothing is polled)."""
        return

    async def async_press(self) -> None:
        """Handle the button press by sending the write command to the device.

        Sends the configured command with a zero-value payload.  The device
        interprets such commands as a one-shot trigger (e.g. clearing the
        fault log).
        """
        _LOGGER.debug("Pressing button %s (command: %s)", self.name, self._command)
        try:
            await async_write_parameter(self.hass, self._device, self._entry, b"\x00")
            _LOGGER.debug("Button %s pressed successfully", self.name)
        except (ValueError, TypeError, *DEVICE_ERRORS) as err:
            _LOGGER.error("Error pressing button %s: %s", self.name, err, exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="button_press_failed",
                translation_placeholders={"name": str(self.name)},
            ) from err

"""THZ Button Entity Platform.

This module provides the button platform for the THZ integration.
Button entities represent one-shot write commands that can be triggered
from the Home Assistant UI or automations.

Currently exposed buttons:
  - zResetLast10errors: clears the on-device fault log (all firmware).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZBaseEntity
from .entity_translations import get_translation_key
from .platform_setup import async_setup_write_platform
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
        entry: dict[str, Any],
        device: THZDevice,
        device_id: str,
        scan_interval: int | None = None,
    ) -> None:
        """Initialize a THZ button entity.

        Args:
            name: The name of the button.
            entry: The register entry dict from the write map.
            device: The device instance this button communicates with.
            device_id: The device identifier for registry linking.
            scan_interval: Not used for buttons; accepted for API compatibility.
        """
        super().__init__(
            name=name,
            command=entry["command"],
            device=device,
            device_id=device_id,
            icon=entry.get("icon") or "mdi:gesture-tap-button",
            scan_interval=scan_interval,
            translation_key=get_translation_key(name),
        )

    async def async_added_to_hass(self) -> None:
        """Skip base periodic polling setup for stateless buttons."""
        # Intentionally do not call super().async_added_to_hass() here because
        # THZBaseEntity schedules a periodic update timer that is not needed
        # for write-only button entities without readable state.
        return

    async def async_update(self) -> None:
        """Buttons have no readable state; override to suppress polling."""
        return

    async def async_press(self) -> None:
        """Handle the button press by sending the write command to the device.

        Sends the configured command with a zero-value payload.  The device
        interprets such commands as a one-shot trigger (e.g. clearing the
        fault log).
        """
        _LOGGER.debug("Pressing button %s (command: %s)", self.name, self._command)
        try:
            await self._device.async_execute(
                self.hass,
                self._device.write_value,
                bytes.fromhex(self._command),
                b"\x00",
            )
            _LOGGER.info("Button %s pressed successfully", self.name)
        except (ValueError, TypeError, OSError, RuntimeError, ConnectionError) as err:
            _LOGGER.error(
                "Error pressing button %s: %s", self.name, err, exc_info=True
            )
            raise HomeAssistantError(
                f"Unable to execute THZ button '{self.name}'"
            ) from err

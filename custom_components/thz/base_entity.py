"""Base entity classes for THZ integration.

This module provides base classes for THZ entities to reduce code duplication
across entity platforms (number, switch, select, time).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.helpers.entity import Entity

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN, should_hide_entity_by_default

if TYPE_CHECKING:
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)


class THZBaseEntity(Entity):
    """Base class for all THZ write entities (number, switch, select, time).

    This class provides common properties and initialization logic shared
    across all THZ entity types that communicate with write registers.

    Write entities use a self-managed timer (async_track_time_interval) for
    periodic polling instead of HA's built-in polling mechanism.  This is
    because HA's polling scheduler reads SCAN_INTERVAL from the class or the
    platform module — not from instance attributes — so all entities in a
    platform would share the same interval, preventing per-config intervals
    from working correctly.  With _attr_should_poll = False and a timer
    registered in async_added_to_hass, each entity polls at the interval
    specified by the write_interval config option.
    """

    _attr_should_poll = False

    def __init__(
        self,
        name: str,
        command: str,
        device: THZDevice,
        device_id: str,
        icon: str | None = None,
        unique_id: str | None = None,
        scan_interval: int | None = None,
        translation_key: str | None = None,
    ) -> None:
        """Initialize base THZ entity.

        Args:
            name: The display name of the entity.
            command: The hex command string for device communication.
            device: The THZ device instance.
            device_id: The device identifier for registry linking.
            icon: Optional icon override (defaults to "mdi:eye").
            unique_id: Optional unique ID (auto-generated if not provided).
            scan_interval: Poll interval in seconds. Defaults to
                DEFAULT_UPDATE_INTERVAL. Used to schedule async_update calls
                via async_track_time_interval.
            translation_key: Optional translation key for localization.
        """
        self._command = command
        self._device = device
        self._device_id = device_id
        self._attr_icon = icon or "mdi:eye"

        # Per Home Assistant documentation, has_entity_name=True is MANDATORY for new integrations.
        # See: https://developers.home-assistant.io/docs/core/entity/#entity-naming
        #
        # CRITICAL: Home Assistant ignores translation_key when _attr_name is set!
        # The fix: Only set _attr_translation_key (not _attr_name) when translation is available.
        # When no translation: set _attr_name as fallback.
        if translation_key is not None:
            self._attr_translation_key = translation_key
            self._attr_has_entity_name = True
            # Do NOT set _attr_name - it blocks translation lookup!
        else:
            self._attr_name = name
            # has_entity_name not set for legacy entities without translations

        # Generate unique ID if not provided
        self._attr_unique_id = (
            unique_id or self._generate_unique_id(command, name)
        )

        # Debug log entity attributes
        _LOGGER.debug(
            "Entity %s initialized: has_entity_name=%s, name=%s, translation_key=%s",
            name, getattr(self, '_attr_has_entity_name', False),
            getattr(self, '_attr_name', None),
            getattr(self, '_attr_translation_key', None)
        )

        # Store poll interval for use in async_added_to_hass
        self._scan_interval = timedelta(
            seconds=scan_interval if scan_interval is not None else DEFAULT_UPDATE_INTERVAL
        )
        self._unsub_poll: Callable[[], None] | None = None

        # Set default visibility based on entity naming conventions
        self._attr_entity_registry_enabled_default = not should_hide_entity_by_default(name)

    async def async_added_to_hass(self) -> None:
        """Register a periodic update timer when the entity is added to HA."""
        from homeassistant.helpers.event import async_track_time_interval

        async def _scheduled_update(_now) -> None:
            try:
                await self.async_update()
                self.async_write_ha_state()
            except Exception:
                _LOGGER.exception(
                    "Error updating write entity %s",
                    self._attr_unique_id,
                )

        self._unsub_poll = async_track_time_interval(
            self.hass, _scheduled_update, self._scan_interval
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the periodic update timer when the entity is removed."""
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None

    def _generate_unique_id(self, command: str, name: str) -> str:
        """Generate a unique identifier for the entity.

        Args:
            command: The command hex string.
            name: The entity name.

        Returns:
            A unique identifier string.
        """
        return f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"

    # No property overrides needed!
    # Home Assistant uses ONLY the _attr_* attributes for translation:
    # - _attr_translation_key: triggers translation lookup in strings.json
    # - _attr_name: fallback name when no translation_key is set
    # - _attr_has_entity_name: must be True for entities with translations
    #
    # IMPORTANT: Setting _attr_name blocks translation_key from working!
    # Properties are NOT evaluated by HA's translation system.

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the registry."""
        return self._attr_entity_registry_enabled_default

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes including register information.

        Returns:
            A dictionary containing register metadata for this entity,
            visible as attributes in the Home Assistant UI.
        """
        return {
            "register_command": self._command,
        }

    @property
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

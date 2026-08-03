"""Base entity classes for THZ integration.

This module provides base classes for THZ entities to reduce code duplication
across entity platforms (number, switch, select, time).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN, should_hide_entity_by_default

if TYPE_CHECKING:
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)


class THZBaseEntity(Entity):
    """Base class for all THZ write entities (number, switch, select, time).

    This class provides common properties and initialization logic shared
    across all THZ entity types that communicate with write registers.
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
            scan_interval: Update interval in seconds (uses DEFAULT_UPDATE_INTERVAL if
                not provided).
            translation_key: Optional translation key for localization.
        """
        self._command = command
        self._device = device
        self._device_id = device_id
        self._attr_icon = icon or "mdi:eye"
        self._attr_available = True

        # Per Home Assistant documentation, has_entity_name=True is MANDATORY for
        # new integrations.
        # See: https://developers.home-assistant.io/docs/core/entity/#entity-naming
        #
        # CRITICAL: Home Assistant ignores translation_key when _attr_name is set!
        # The fix: Only set _attr_translation_key (not _attr_name) when translation
        # is available.
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

        # Store update interval for use in async_added_to_hass
        interval = (
            scan_interval if scan_interval is not None else DEFAULT_UPDATE_INTERVAL
        )
        self._update_interval = timedelta(seconds=interval)
        self._unsub_update: Callable[[], None] | None = None

        # Set default visibility based on entity naming conventions
        # Uses HA's standard _attr_ pattern – do NOT add an explicit @property
        # override; it conflicts with HA's __init_subclass__ CachedProperty
        # mechanism and can silently default to True on derived entity classes.
        self._attr_entity_registry_enabled_default = not should_hide_entity_by_default(
            name
        )

        _LOGGER.debug(
            "Entity %s: entity_registry_enabled_default=%s (hide=%s)",
            name,
            self._attr_entity_registry_enabled_default,
            should_hide_entity_by_default(name),
        )

    def _generate_unique_id(self, command: str, name: str) -> str:
        """Generate a unique identifier for the entity.

        Args:
            command: The command hex string.
            name: The entity name.

        Returns:
            A unique identifier string.
        """
        return f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"

    async def async_added_to_hass(self) -> None:
        """Schedule periodic updates when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._unsub_update = async_track_time_interval(
            self.hass,
            self._async_scheduled_update,
            self._update_interval,
        )

    async def _async_scheduled_update(self, _now: datetime) -> None:
        """Trigger an update from the periodic timer."""
        await self.async_update_ha_state(force_refresh=True)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the periodic update timer when entity is removed."""
        if self._unsub_update is not None:
            self._unsub_update()
            self._unsub_update = None
        await super().async_will_remove_from_hass()

    # No property overrides needed!
    # Home Assistant uses ONLY the _attr_* attributes for translation:
    # - _attr_translation_key: triggers translation lookup in strings.json
    # - _attr_name: fallback name when no translation_key is set
    # - _attr_has_entity_name: must be True for entities with translations
    #
    # IMPORTANT: Setting _attr_name blocks translation_key from working!
    # Properties are NOT evaluated by HA's translation system.
    #
    # NOTE: Do NOT define @property entity_registry_enabled_default here!
    # HA's Entity.__init_subclass__ creates CachedProperty descriptors for
    # _attr_* backed properties.  An explicit @property on this base class
    # can be shadowed by a CachedProperty that __init_subclass__ installs
    # on a *derived* class (e.g. THZScheduleTime), causing the derived
    # class's descriptor to ignore _attr_entity_registry_enabled_default
    # and default to True.  Letting HA resolve the _attr_ pattern natively
    # is the correct approach for HA >= 2023.

    @property
    def available(self) -> bool:
        """Return True if the device was reachable on the last update."""
        return self._attr_available

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

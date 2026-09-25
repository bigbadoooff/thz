"""Base entity classes for THZ integration.

This module provides base classes for THZ entities to reduce code duplication
across entity platforms (number, switch, select, time).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import (
    ENTITY_ID_STYLE_DEFAULT,
    ENTITY_VISIBILITY_DEFAULT,
    should_hide_entity,
    should_hide_entity_by_default,
)
from .devices import thz_device_info
from .entity_id_style import resolve_suggested_object_id
from .exceptions import DEVICE_ERRORS
from .parameter_io import (
    block_coordinator_key,
    parameter_from_block,
    parameter_from_read,
    parameter_read_key,
)

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .parameter_poller import ParameterPoller, ReadKey
    from .register_maps.model import WriteParam
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)


class THZBaseEntity(Entity):
    """Base class for all THZ write entities (number, switch, select, time).

    This class provides common properties and initialization logic shared
    across all THZ entity types that communicate with write registers.
    """

    _attr_should_poll = False
    # Names are the entity's part only; Home Assistant prefixes the device
    # name (https://developers.home-assistant.io/docs/core/entity/#entity-naming).
    _attr_has_entity_name = True
    # Block coordinators by key ("pxx17"), set by the platform setup; lets
    # 2xx block parameters read from data that is already being polled.
    _coordinators: Mapping[str, Any] = MappingProxyType({})
    # The poller of the config entry, set by the platform setup.
    _poller: ParameterPoller | None = None

    def __init__(
        self,
        name: str,
        command: str,
        device: THZDevice,
        device_id: str,
        icon: str | None = None,
        unique_id: str | None = None,
        translation_key: str | None = None,
        entity_id_style: str = ENTITY_ID_STYLE_DEFAULT,
        entity_visibility: str = ENTITY_VISIBILITY_DEFAULT,
        entity_id_prefix: str | None = None,
        domain: str | None = None,
    ) -> None:
        """Initialize base THZ entity.

        Args:
            name: The display name of the entity.
            command: The hex command string for device communication.
            device: The THZ device instance.
            device_id: The device identifier for registry linking.
            icon: Optional icon override, used only when translation_key is
                None (defaults to "mdi:eye"). Translated entities get their
                icon from icons.json instead.
            unique_id: Optional unique ID (auto-generated if not provided).
            translation_key: Optional translation key for localization.
            entity_id_style: One of the ``ENTITY_ID_STYLE_*`` values from
                const.py. "fhem" sets ``self.entity_id`` directly from the
                raw ``name`` so a brand-new entity's entity_id reads like the
                FHEM/Stiebel field name; the displayed name and unique_id are
                unaffected either way. See entity_id_style.py.
            entity_visibility: One of the ``ENTITY_VISIBILITY_*`` values from
                const.py, controlling whether this entity starts out enabled
                or disabled in the entity registry. See should_hide_entity().
            entity_id_prefix: Optional device name/alias (e.g. "lwz") to
                prepend to the FHEM-style entity_id, e.g.
                "lwz_p99start_unsched_vent". Only used when entity_id_style
                is "fhem"; ignored otherwise. See resolve_suggested_object_id().
            domain: The HA entity platform domain this entity belongs to
                (e.g. "number", "switch"). Required for entity_id_style
                "fhem" to take effect -- see the ``self.entity_id`` note
                below. Each concrete subclass hardcodes its own domain when
                calling super().__init__().
        """
        self._command = command
        self._device = device
        self._device_id = device_id
        self._attr_available = True

        # Home Assistant ignores translation_key when _attr_name is set, so
        # only one of the two is set: the translation key when there is one,
        # otherwise the name as a fallback (tests_ha checks that every
        # entity has a translation key).
        #
        # Icon: entities with a translation_key get their icon from
        # icons.json (icon translations) instead of a hardcoded _attr_icon,
        # per HA's icon-translations quality-scale rule. Entities without a
        # translation_key fall back to the icon passed in (or "mdi:eye").
        if translation_key is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = name
            self._attr_icon = icon or "mdi:eye"

        # Generate unique ID if not provided
        self._attr_unique_id = unique_id or self._generate_unique_id(command, name)

        # Entity-ID naming style: independent of unique_id/translation_key
        # (see resolve_suggested_object_id's docstring for details). Only
        # takes effect the first time HA creates this entity.
        #
        # IMPORTANT: Home Assistant's Entity class has no "_attr_suggested_object_id"
        # hook -- Entity.suggested_object_id is a read-only @property computed from
        # self.name/translations, and never reads any "_attr_*" instance attribute.
        # Setting one is a silent no-op: HA falls straight through to its own
        # has_entity_name/device-name/area-based naming instead.
        #
        # The actually-supported mechanism (see entity_platform.py's
        # EntityPlatform._async_add_entity) is to set self.entity_id directly
        # *before* the entity is added to hass: if entity.entity_id is already set,
        # HA uses it verbatim as the suggested object_id instead of deriving one.
        suggested_object_id = resolve_suggested_object_id(
            name, entity_id_style, device_prefix=entity_id_prefix
        )
        if suggested_object_id and domain:
            self.entity_id = f"{domain}.{suggested_object_id}"

        # Debug log entity attributes
        _LOGGER.debug(
            "Entity %s initialized: has_entity_name=%s, name=%s, translation_key=%s",
            name,
            getattr(self, "_attr_has_entity_name", False),
            getattr(self, "_attr_name", None),
            getattr(self, "_attr_translation_key", None),
        )

        self._unsub_poll: Callable[[], None] | None = None

        # Set default visibility based on entity naming conventions and the
        # configured entity_visibility tier.
        # Uses HA's standard _attr_ pattern - do NOT add an explicit @property
        # override; it conflicts with HA's __init_subclass__ CachedProperty
        # mechanism and can silently default to True on derived entity classes.
        self._attr_entity_registry_enabled_default = not should_hide_entity(
            name, entity_visibility
        )

        # Advanced/technician-mode parameters (also hidden by default above)
        # are configuration values from the user's point of view.
        if should_hide_entity_by_default(name):
            self._attr_entity_category = EntityCategory.CONFIG

        _LOGGER.debug(
            "Entity %s: entity_registry_enabled_default=%s (hide=%s, visibility=%s)",
            name,
            self._attr_entity_registry_enabled_default,
            should_hide_entity(name, entity_visibility),
            entity_visibility,
        )

    def _generate_unique_id(self, command: str, name: str) -> str:
        """Generate a unique identifier for the entity.

        Args:
            command: The command hex string.
            name: The entity name.

        Returns:
            A unique identifier string.
        """
        name_slug = name.lower().replace(" ", "_")
        return f"thz_{self._device_id}_set_{command.lower()}_{name_slug}"

    # Where the entity's value comes from: a 2.x parameter inside a polled
    # block listens to the block's coordinator; any other entity with a
    # _poll_key subscribes it at the poller. Buttons have neither.

    def _poll_key(self) -> ReadKey | None:
        """Return the register read the poller does for this entity."""
        return None

    def _block_coordinator(self) -> DataUpdateCoordinator[Any] | None:
        """Return the block coordinator this entity reads its value from."""
        return None

    def _value_from_poll(self, raw: bytes) -> bytes:
        """Return the value bytes from the bytes read for _poll_key."""
        return raw

    def _value_from_block(self, block_data: bytes) -> bytes | None:
        """Return the value bytes from the block coordinator's data."""
        return None

    def _apply_value(self, value_bytes: bytes) -> None:
        """Decode value bytes into the entity's state."""

    async def async_added_to_hass(self) -> None:
        """Start listening to the block coordinator or the poller."""
        await super().async_added_to_hass()
        coordinator = self._block_coordinator()
        if coordinator is not None:
            self._unsub_poll = coordinator.async_add_listener(self._handle_block_update)
            self._update_from_block(coordinator)
            return
        key = self._poll_key()
        if key is None or self._poller is None:
            return
        self._unsub_poll = self._poller.async_subscribe(key, self._handle_poll)
        if key in self._poller.data:
            self._update_from_poll(self._poller.data[key])

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None
        await super().async_will_remove_from_hass()

    async def async_update(self) -> None:
        """Read the value from the device now (homeassistant.update_entity)."""
        value_bytes = await self._async_guarded_read(self._async_read_value())
        if value_bytes is not None:
            self._apply_value(value_bytes)

    @callback
    def _handle_poll(self, raw: bytes | None) -> None:
        """Take a poller result and write the state."""
        self._update_from_poll(raw)
        self.async_write_ha_state()

    @callback
    def _handle_block_update(self) -> None:
        """Take new block data and write the state."""
        coordinator = self._block_coordinator()
        if coordinator is not None:
            self._update_from_block(coordinator)
        self.async_write_ha_state()

    def _update_from_poll(self, raw: bytes | None) -> None:
        """Apply a poller result: None is a failed read, b"" keeps the value."""
        if raw is None:
            # The poller logs the failed read.
            self._set_unavailable("read failed", logging.DEBUG)
            return
        self._attr_available = True
        if not raw:
            _LOGGER.warning(
                "No data received for %s, keeping previous value", self.name
            )
            return
        self._apply_value(self._value_from_poll(raw))

    def _update_from_block(self, coordinator: DataUpdateCoordinator[Any]) -> None:
        """Apply the block coordinator's data, if it has any."""
        if not coordinator.last_update_success:
            # The coordinator logs the failed read.
            self._set_unavailable("block read failed", logging.DEBUG)
            return
        if not coordinator.data:
            return
        value_bytes = self._value_from_block(coordinator.data)
        if value_bytes is None:
            return
        self._attr_available = True
        self._apply_value(value_bytes)

    def _set_unavailable(self, reason: object, level: int = logging.WARNING) -> None:
        """Mark the entity unavailable, logging only the transition."""
        if self._attr_available:
            _LOGGER.log(level, "%s became unavailable: %s", self.name, reason)
        self._attr_available = False

    async def _async_after_write(self) -> None:
        """Keep the polled data in step with a value just written.

        The block is re-read, so its other listeners do not show the old
        value until the next poll; a polled key's last result is dropped,
        so an entity added later does not start with the old value.
        """
        coordinator = self._block_coordinator()
        if coordinator is not None:
            await coordinator.async_request_refresh()
            return
        key = self._poll_key()
        if key is not None and self._poller is not None:
            self._poller.async_invalidate(key)

    # No property overrides needed!
    # Home Assistant uses ONLY the _attr_* attributes for translation:
    # - _attr_translation_key: triggers translation lookup in strings.json
    # - _attr_name: fallback name when no translation_key is set
    # - _attr_has_entity_name: True for every entity (class attribute)
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

    async def _async_read_value(self) -> bytes:
        """Read the value bytes of _poll_key from the device."""
        key = self._poll_key()
        if key is None:
            return b""
        command, offset, length = key
        raw: bytes = await self._device.async_execute(
            self._device.read_value,
            bytes.fromhex(command),
            "get",
            offset,
            length,
        )
        return self._value_from_poll(raw) if raw else raw

    async def _async_guarded_read(
        self, read: Coroutine[Any, Any, bytes]
    ) -> bytes | None:
        """Await a device read, tracking availability along the way.

        On a device error, marks the entity unavailable (logging once on
        the transition) and returns None. An empty answer logs a warning
        and also returns None: nothing to decode, keep the previous value.
        """
        try:
            value_bytes = await read
        except DEVICE_ERRORS as err:
            self._set_unavailable(err)
            return None
        self._attr_available = True

        if not value_bytes:
            _LOGGER.warning(
                "No data received for %s, keeping previous value", self.name
            )
            return None

        return value_bytes

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

    # Sub-device group, set by devices.assign_subdevices before the entity
    # is added; None links the entity to the heat pump itself.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
        )


class THZParameterEntity(THZBaseEntity):
    """Base class for entities showing one write-map parameter.

    The parameter's access mode (own register or inside a 2.x block) is
    handled by parameter_io; subclasses set ``_entry`` and decode the value
    bytes in _apply_value.
    """

    _entry: WriteParam

    def _poll_key(self) -> ReadKey | None:
        """Return the register read that holds the parameter."""
        return parameter_read_key(self._entry)

    def _value_from_poll(self, raw: bytes) -> bytes:
        """Return the parameter's bytes (a flag's bit) from the read."""
        return parameter_from_read(self._entry, raw)

    def _block_coordinator(self) -> DataUpdateCoordinator[Any] | None:
        """Return the coordinator polling this 2.x parameter's block, if any.

        A block the firmware does not have (read fine, but no data) does not
        count: the parameter is then polled on its own and shows the
        device's answer.
        """
        key = block_coordinator_key(self._entry)
        coordinator = self._coordinators.get(key) if key else None
        if (
            coordinator is not None
            and coordinator.last_update_success
            and coordinator.data is None
        ):
            return None
        return coordinator

    def _value_from_block(self, block_data: bytes) -> bytes | None:
        """Cut the parameter out of the block data."""
        return parameter_from_block(self._entry, block_data)

"""Select entity for THZ integration."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZBaseEntity
from .entity_translations import get_translation_key
from .exceptions import DEVICE_ERRORS
from .parameter_io import async_read_parameter, async_write_parameter
from .platform_setup import async_setup_write_platform
from .register_maps.model import WriteParam
from .thz_device import THZDevice
from .value_codec import THZValueCodec
from .value_maps import SELECT_MAP, select_slugs, state_slug

_LOGGER = logging.getLogger(__name__)

# Each entity polls and writes to the device directly (no coordinator);
# limit to one in-flight update/service call at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create THZSelect entities."""
    await async_setup_write_platform(
        hass, config_entry, async_add_entities, THZSelect, "select"
    )


def _options_within_bounds(
    options: dict[str, str], low: str | None, high: str | None
) -> dict[str, str]:
    """Return the raw {key: value} table entries whose key lies within bounds.

    The value tables are shared across firmwares, but a firmware may allow
    fewer values (e.g. p75passiveCooling is 0..2 on 4.39 and 0..4 on 5.39).
    """
    try:
        low_value = int(low) if low not in (None, "") else None
        high_value = int(high) if high not in (None, "") else None
    except ValueError:
        return dict(options)
    return {
        key: option
        for key, option in options.items()
        if (low_value is None or int(key) >= low_value)
        and (high_value is None or int(key) <= high_value)
    }


class THZSelect(THZBaseEntity, SelectEntity):
    """Representation of a THZ Select entity."""

    def __init__(
        self,
        name: str,
        entry: WriteParam,
        device: THZDevice,
        device_id: str,
        scan_interval: int | None = None,
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize a THZ select entity.

        Args:
            name: The name of the select entity.
            entry: The write-map parameter.
            device: The device instance this select entity belongs to.
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
            command=entry.command,
            device=device,
            device_id=device_id,
            icon=entry.icon,
            scan_interval=scan_interval,
            translation_key=get_translation_key(name),
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
            domain="select",
        )

        # Select-specific attributes
        self._entry = entry
        self._decode_type = entry.decode_type

        # Set available options based on decode_type, bounded by the entry's
        # min/max (a firmware may allow fewer values than the shared table).
        # Options are translation keys (slugs); _table_values maps them back
        # to the SELECT_MAP values the codec works with.
        self._table_values: dict[str, str] = {}
        if self._decode_type and self._decode_type in SELECT_MAP:
            bounded = _options_within_bounds(
                SELECT_MAP[self._decode_type], entry.min, entry.max
            )
            self._table_values = select_slugs(bounded)
            self._attr_options = list(self._table_values)
            _LOGGER.debug(
                "Options for %s (%s): %s", name, self._decode_type, self._attr_options
            )
        else:
            self._attr_options = []
            _LOGGER.warning(
                "No options found for select %s with decode_type %s",
                name,
                self._decode_type,
            )

        self._attr_current_option = None

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        return self._attr_current_option

    async def async_update(self) -> None:
        """Fetch new state data for the select."""
        value_bytes = await self._async_guarded_read(
            async_read_parameter(self.hass, self._device, self._entry)
        )
        if value_bytes is None:
            return

        _LOGGER.debug("Received bytes for %s: %s", self.name, value_bytes.hex())

        try:
            # Use centralized codec for decoding
            option = THZValueCodec.decode_select(value_bytes, self._decode_type)
            if option:
                option = state_slug(option)
                self._attr_current_option = option
                _LOGGER.debug("Decoded option for %s: %s", self.name, option)
            else:
                _LOGGER.warning("Could not map value to option for %s", self.name)
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error("Error decoding select %s: %s", self.name, err, exc_info=True)
            # Keep previous value on error

    async def async_select_option(self, option: str) -> None:
        """Set the selected option."""
        _LOGGER.debug("Setting %s to option %s", self.name, option)

        try:
            # Use centralized codec for encoding
            value_bytes = THZValueCodec.encode_select(
                self._table_values.get(option, option), self._decode_type
            )
            _LOGGER.debug("Encoded value bytes: %s", value_bytes.hex())

            await async_write_parameter(
                self.hass, self._device, self._entry, value_bytes
            )

            self._attr_current_option = option
            self.async_write_ha_state()  # Optimistically update UI; next poll confirms
        except (ValueError, TypeError, *DEVICE_ERRORS) as err:
            _LOGGER.error(
                "Error setting select %s to option %s: %s",
                self.name,
                option,
                err,
                exc_info=True,
            )

"""THZ Number Entity Platform."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import THZBaseEntity
from .entity_translations import get_translation_key
from .parameter_io import (
    async_read_parameter,
    async_write_parameter,
    block_coordinator_key,
    parameter_from_block,
    parameter_length,
)
from .platform_setup import async_setup_write_platform
from .thz_device import THZDevice
from .value_codec import THZValueCodec

_LOGGER = logging.getLogger(__name__)

# Each entity polls and writes to the device directly (no coordinator);
# limit to one in-flight update/service call at a time.
PARALLEL_UPDATES = 1


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
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize a THZ number entity.

        Args:
            name: The name of the number entity.
            entry: The register entry dict containing configuration.
            device: The device instance this entity belongs to.
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
            domain="number",
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
        self._attr_mode = NumberMode.BOX
        self._decode_type = entry["decode_type"]
        self._attr_native_value = None

        # Reads/writes go through parameter_io, which handles both direct
        # registers and 2xx block parameters (see write_mode="block").
        self._entry = entry
        self._read_length = parameter_length(entry)

    @property
    def native_value(self) -> float | None:
        """Return the native value of the number."""
        return self._attr_native_value

    def _block_coordinator(self):
        """Return the coordinator polling this 2xx parameter's block, if any."""
        key = block_coordinator_key(self._entry)
        return self._coordinators.get(key) if key else None

    async def async_update(self) -> None:
        """Fetch new state data for the number.

        2xx block parameters are taken from the block's coordinator when it
        has fresh data, instead of reading the whole block from the device
        once per parameter; otherwise the device is read directly.
        """
        value_bytes = None
        coordinator = self._block_coordinator()
        if (
            coordinator is not None
            and coordinator.last_update_success
            and coordinator.data
        ):
            value_bytes = parameter_from_block(self._entry, coordinator.data)
        if value_bytes is None:
            value_bytes = await self._async_guarded_read(
                async_read_parameter(self.hass, self._device, self._entry)
            )
        if value_bytes is None:
            return

        _LOGGER.debug("Received bytes for %s: %s", self.name, value_bytes.hex())

        try:
            # Use centralized codec for decoding
            value = THZValueCodec.decode_number(
                value_bytes,
                self._attr_native_step,
                self._decode_type,
                self._entry.get("signed", True),
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
            # Use centralized codec for encoding; pass the register length so 2xx
            # firmware block parameters (which may be 4 bytes) are encoded correctly.
            value_bytes = THZValueCodec.encode_number(
                value,
                self._attr_native_step,
                self._decode_type,
                self._read_length,
            )

            await async_write_parameter(
                self.hass, self._device, self._entry, value_bytes
            )

            self._attr_native_value = value
            self.async_write_ha_state()  # Optimistically update UI; next poll confirms
            coordinator = self._block_coordinator()
            if coordinator is not None:
                # Keep the block data this entity reads from in step with
                # the write, so the next update does not show the old value.
                await coordinator.async_request_refresh()
        except (ValueError, TypeError, ConnectionError, RuntimeError, OSError) as err:
            _LOGGER.error(
                "Error encoding number %s value %s: %s",
                self.name, value, err, exc_info=True
            )

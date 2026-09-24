"""Event entities automations can trigger on: a new fault and a filter change.

- **Fault** (``pxxD1``, firmware 4.x/5.x): fires ``fault`` for every record
  that appears in the heat pump's fault memory, with its code, name, time
  and date.
- **Filter** (``pxx0A0176``): fires ``filter_both``, ``filter_up`` or
  ``filter_down`` when the heat pump starts asking for that filter change.

Both read data their block coordinators poll anyway, so they add no serial
traffic. What is already there when Home Assistant starts (the fault history,
a filter that is already due) sets the baseline and fires nothing; the
fault sensors and filter binary sensors show that state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .devices import assign_subdevices, thz_device_info
from .fault_memory import decode_fault_memory, record_fingerprints
from .fault_sensor import D1_BLOCK, supports_fault_memory
from .register_maps.model import ReadField
from .value_codec import decode_raw_value

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ._typing_compat import AddConfigEntryEntitiesCallback
    from .runtime_data import THZConfigEntry

_LOGGER = logging.getLogger(__name__)

# Events come from coordinator data; nothing is read or written here.
PARALLEL_UPDATES = 0

FILTER_BLOCK = "pxx0A0176"
# Filter flag in the read map → event type.
FILTER_FIELDS = {
    "filterBoth": "filter_both",
    "filterUp": "filter_up",
    "filterDown": "filter_down",
}
EVENT_FAULT = "fault"
# Fault record keys passed on as event attributes.
FAULT_ATTRIBUTES = ("fault_number", "fault_code", "description", "time", "date")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entities whose data is polled."""
    entry_data = config_entry.runtime_data
    register_manager = entry_data.register_manager
    device_id = entry_data.device_id
    entities: list[_THZEvent] = []

    fault_coordinator = entry_data.coordinators.get(D1_BLOCK)
    if fault_coordinator is not None and supports_fault_memory(register_manager):
        entities.append(THZFaultEvent(fault_coordinator, device_id))

    filter_coordinator = entry_data.coordinators.get(FILTER_BLOCK)
    filters = {
        event_type: read_field
        for name, event_type in FILTER_FIELDS.items()
        if (read_field := register_manager.find_field(FILTER_BLOCK, name))
    }
    if filter_coordinator is not None and filters:
        entities.append(THZFilterEvent(filter_coordinator, device_id, filters))

    assign_subdevices(entities, config_entry.data)
    async_add_entities(entities)


class _THZEvent(CoordinatorEntity, EventEntity):
    """An event entity fed by a block coordinator."""

    _attr_has_entity_name = True
    KEY = ""
    UNIQUE_SUFFIX = ""

    # Sub-device group, set by devices.assign_subdevices.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None

    def __init__(self, coordinator: Any, device_id: str) -> None:
        """Initialise the entity for ``device_id``."""
        super().__init__(coordinator)
        self._device_id = device_id
        # No "event" in the id: its "vent" would put it on the ventilation
        # sub-device (devices.subdevice_for).
        self._attr_unique_id = f"thz_{device_id}_{self.UNIQUE_SUFFIX}"
        self._attr_translation_key = self.KEY

    @property
    def device_info(self) -> DeviceInfo:
        """Link the entity to the heat pump or its sub-device."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
        )

    async def async_added_to_hass(self) -> None:
        """Take what the block holds now as the baseline."""
        await super().async_added_to_hass()
        self._process(self.coordinator.data, fire=False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire events for what changed since the last data."""
        self._process(self.coordinator.data, fire=True)
        self.async_write_ha_state()

    def _process(self, data: bytes | None, *, fire: bool) -> None:
        """Compare ``data`` with the last data; fire events if ``fire``."""
        raise NotImplementedError


class THZFaultEvent(_THZEvent):
    """Fires for every record that appears in the fault memory."""

    KEY = "fault"
    UNIQUE_SUFFIX = "new_fault"
    _attr_event_types = [EVENT_FAULT]  # noqa: RUF012

    def __init__(self, coordinator: Any, device_id: str) -> None:
        """Initialise with no known records."""
        super().__init__(coordinator, device_id)
        self._known: set[str] | None = None

    def _process(self, data: bytes | None, *, fire: bool) -> None:
        if not data:
            return
        decoded = decode_fault_memory(bytes(data))
        if not decoded["valid"]:
            return
        entries = [e for e in decoded["entries"] if e.get("complete")]
        fingerprints = record_fingerprints(entries)
        known, self._known = self._known, set(fingerprints)
        if known is None or not fire:
            return
        for entry, fingerprint in zip(entries, fingerprints, strict=True):
            if fingerprint not in known:
                _LOGGER.debug("New fault in the fault memory: %s", entry)
                self._trigger_event(
                    EVENT_FAULT, {key: entry.get(key) for key in FAULT_ATTRIBUTES}
                )


class THZFilterEvent(_THZEvent):
    """Fires when the heat pump starts asking for a filter change."""

    KEY = "filter"
    UNIQUE_SUFFIX = "filter_change"

    def __init__(
        self, coordinator: Any, device_id: str, filters: dict[str, ReadField]
    ) -> None:
        """Watch the filter flags ``filters`` (event type → read field)."""
        super().__init__(coordinator, device_id)
        self._filters = filters
        self._attr_event_types = list(filters)
        self._due: dict[str, bool] | None = None

    def _process(self, data: bytes | None, *, fire: bool) -> None:
        if not data:
            return
        due: dict[str, bool] = {}
        for event_type, read_field in self._filters.items():
            raw = data[read_field.byte_offset : read_field.byte_offset + 1]
            if not raw:
                return
            # The flag's bit in the whole byte, as the binary sensors read it.
            due[event_type] = bool(decode_raw_value(raw, read_field.byte_decode_type))
        before, self._due = self._due, due
        if before is None or not fire:
            return
        for event_type, is_due in due.items():
            if is_due and not before.get(event_type, False):
                _LOGGER.debug("Filter change due: %s", event_type)
                self._trigger_event(event_type)
